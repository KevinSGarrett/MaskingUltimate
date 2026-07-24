from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

from maskfactory.vlm.critic_catalog import canonical_sha256
from maskfactory.vlm.critic_protocol_v3 import CHECK_KEYS
from maskfactory.vlm.critic_protocol_v3_control_screening import (
    CriticProtocolV3ControlScreeningError,
    build_control_screening_execution,
    control_registry_sha256,
    derive_control_screening_verdict,
    parse_control_screening_response,
    validate_control_screening_registry,
)

ROOT = Path(__file__).resolve().parents[1]
PANELS = ("source", "binary_mask", "overlay", "contour", "full_context", "target_zoom")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry() -> dict:
    return yaml.safe_load(
        (ROOT / "configs/visual_critic_protocol_v3_session_agent_control_screening.yaml").read_text()
    )


def _record(root: Path, sample_id: str, partition: str, outcome: str, defect: str | None, seed: int) -> dict:
    files, hashes = {}, {}
    for name in PANELS:
        path = root / sample_id / "panels" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("L" if name == "binary_mask" else "RGB", (12, 10), color=0)
        if name == "binary_mask":
            for x in range(3, 8):
                for y in range(2, 7):
                    image.putpixel((x, y), 255)
        else:
            image.paste((seed, 30, 40), (0, 0, 12, 10))
        image.save(path, format="PNG", optimize=False)
        image.close()
        files[name] = f"panels/{name}.png"
        hashes[name] = _sha(path)
    return {
        "sample_id": sample_id,
        "partition": partition,
        "canonical_label": "hair",
        "expected_outcome": outcome,
        "defect_type": defect,
        "critic_corpus_control_eligible": True,
        "critic_role_authority": False,
        "gold_or_production_authority": False,
        "identity_id": seed,
        "split_group_id": f"group-{sample_id}",
        "panel_files": files,
        "panel_sha256s": hashes,
    }


def _admission(root: Path) -> dict:
    records = [
        _record(root, "cal-good-a", "calibration", "valid_mask", None, 10),
        _record(root, "cal-good-b", "calibration", "valid_mask", None, 20),
        _record(root, "cal-bad", "calibration", "known_defect", "boundary", 30),
        _record(root, "hold-good-a", "qualification_holdout", "valid_mask", None, 40),
        _record(root, "hold-good-b", "qualification_holdout", "valid_mask", None, 50),
        _record(root, "hold-bad", "qualification_holdout", "known_defect", "missing_area", 60),
    ]
    value = {
        "schema_version": "maskfactory.celebamask_control_admission.v1",
        "critic_corpus_controls_frozen": True,
        "critic_role_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "records": records,
        "excluded_records": [],
        "admitted_count": len(records),
        "excluded_count": 0,
    }
    value["self_sha256"] = canonical_sha256(value)
    return value


def _response(severity: str, localization: list[int] | None) -> dict:
    return {
        "description": "The two boards show the candidate and reference panels.",
        "findings": {
            key: {
                "severity": severity if key == "boundary" else "none",
                "cited_evidence_panels": ["source", "target_zoom"] if key == "boundary" and severity != "none" else [],
                "localization_xyxy": localization if key == "boundary" and severity != "none" else None,
            }
            for key in CHECK_KEYS
        },
    }


def test_registry_blocks_all_authority_and_fitting() -> None:
    registry = _registry()
    validate_control_screening_registry(registry)
    assert len(control_registry_sha256(registry)) == 64
    registry["calibration_fitting_allowed"] = True
    with pytest.raises(CriticProtocolV3ControlScreeningError, match="drifted"):
        validate_control_screening_registry(registry)


def test_execution_binds_every_control_to_image_disjoint_reference(tmp_path: Path) -> None:
    admission = _admission(tmp_path)
    admission_path = tmp_path / "admission.json"
    admission_path.write_text(json.dumps(admission), encoding="utf-8")
    execution = build_control_screening_execution(
        admission=admission,
        admission_file_sha256=_sha(admission_path),
        panel_root=tmp_path,
        registry=_registry(),
    )
    assert execution["case_count"] == 6
    assert execution["authority_claimed"] is False
    assert execution["calibration_fitting_allowed"] is False
    assert all(case["case_id"] != case["reference_case_id"] for case in execution["cases"])


def test_minor_is_a_screening_defect_and_offboard_evidence_abstains() -> None:
    result = derive_control_screening_verdict(
        response=parse_control_screening_response(json.dumps(_response("minor", [1, 1, 5, 5]))),
        geometry_wh=[12, 10],
    )
    assert result["screening_outcome"] == "screening_defect"
    assert result["authority_claimed"] is False
    offboard = derive_control_screening_verdict(response=_response("serious", [50, 50, 60, 60]), geometry_wh=[12, 10])
    assert offboard["screening_outcome"] == "abstain"
