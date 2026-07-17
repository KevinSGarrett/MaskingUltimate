from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.daz.multi_person_validation import (
    MultiPersonIdentityValidationError,
    evaluate_multi_person_identity,
    load_multi_person_identity_policy,
    publish_multi_person_identity_report,
    validate_multi_person_identity_policy,
    validate_multi_person_identity_report,
)
from maskfactory.daz.render import derive_scene_packages
from maskfactory.validation import ArtifactValidationError
from test_daz_package_derivation import _d8_fixture

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "multi_person_identity_validation.yaml"


def _fixture(tmp_path: Path) -> tuple[dict, dict]:
    (
        derivation_policy,
        contract,
        _arrays,
        source_paths,
        protected_paths,
        assignment,
        construction_map,
    ) = _d8_fixture(tmp_path)
    derivation_report, derived_root, _published = derive_scene_packages(
        contract,
        source_paths=source_paths,
        protected_paths=protected_paths,
        output_root=tmp_path / "derived",
        policy=derivation_policy,
        p_index_construction_map_path=construction_map,
    )
    arguments = {
        "contract": contract,
        "derivation_report": derivation_report,
        "assignment": assignment,
        "construction_map_path": construction_map,
        "instance_map_path": source_paths["instance"],
        "derived_scene_root": derived_root,
        "policy": load_multi_person_identity_policy(POLICY),
    }
    return arguments, derivation_report


def _results(report: dict) -> dict[str, dict]:
    return {row["validator_id"]: row for row in report["results"]}


def _mask(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image).copy() == 255


def _write_mask(path: Path, mask: np.ndarray) -> None:
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L").save(path, format="PNG")


def test_policy_is_closed_and_all_v7_checks_block() -> None:
    policy = load_multi_person_identity_policy(POLICY)
    validate_multi_person_identity_policy(policy)
    assert policy["required_validators"] == [f"DAZ-V7-{index:03d}" for index in range(1, 9)]
    assert all(policy["requirements"].values())
    invalid = copy.deepcopy(policy)
    invalid["requirements"]["exact_target_owner_masks"] = False
    with pytest.raises(MultiPersonIdentityValidationError, match="policy_identity_invalid"):
        validate_multi_person_identity_policy(invalid)


def test_clean_scene_passes_identity_exclusivity_bleed_and_grouping(tmp_path: Path) -> None:
    arguments, _derivation = _fixture(tmp_path)
    report = evaluate_multi_person_identity(**arguments)
    validate_multi_person_identity_report(report)
    assert report["summary"] == {
        "passed": True,
        "acceptance_eligible": True,
        "required_count": 8,
        "passed_count": 8,
        "failed_count": 0,
    }
    error_metrics = {
        key: value
        for key, value in report["metrics"].items()
        if key.endswith("pixels") and key != "visible_person_pixels"
    }
    assert all(value == 0 for value in error_metrics.values())
    assert report["metrics"]["package_hash_failures"] == 0
    assert report["metrics"]["shared_rgb_failures"] == 0
    assert all(row["status"] == "pass" for row in report["results"])


def test_duplicate_owner_pixel_fails_exclusivity_and_acceptance(tmp_path: Path) -> None:
    arguments, _derivation = _fixture(tmp_path)
    root = arguments["derived_scene_root"]
    p0 = root / "packages" / "p0" / "full_body.png"
    p1 = root / "packages" / "p1" / "full_body.png"
    target0 = _mask(p0)
    target1 = _mask(p1)
    y, x = np.argwhere(target1)[0]
    target0[y, x] = True
    _write_mask(p0, target0)
    report = evaluate_multi_person_identity(**arguments)
    results = _results(report)
    assert report["metrics"]["duplicate_ownership_pixels"] == 1
    assert results["DAZ-V7-004"]["status"] == "fail"
    assert results["DAZ-V7-003"]["status"] == "fail"
    assert results["DAZ-V7-007"]["status"] == "fail"
    assert report["summary"]["acceptance_eligible"] is False


def test_coherent_limb_owner_swap_evades_exclusivity_but_fails_identity_bleed(
    tmp_path: Path,
) -> None:
    arguments, _derivation = _fixture(tmp_path)
    root = arguments["derived_scene_root"]
    paths = {
        p_index: {
            "target": root / "packages" / p_index / "full_body.png",
            "other": root / "packages" / p_index / "other_person.png",
        }
        for p_index in ("p0", "p1")
    }
    target0 = _mask(paths["p0"]["target"])
    target1 = _mask(paths["p1"]["target"])
    p0_y, p0_x = np.argwhere(target0)[0]
    p1_y, p1_x = np.argwhere(target1)[0]
    target0[p0_y, p0_x] = False
    target1[p0_y, p0_x] = True
    target1[p1_y, p1_x] = False
    target0[p1_y, p1_x] = True
    visible = target0 | target1
    _write_mask(paths["p0"]["target"], target0)
    _write_mask(paths["p1"]["target"], target1)
    _write_mask(paths["p0"]["other"], visible & ~target0)
    _write_mask(paths["p1"]["other"], visible & ~target1)
    report = evaluate_multi_person_identity(**arguments)
    results = _results(report)
    assert report["metrics"]["duplicate_ownership_pixels"] == 0
    assert report["metrics"]["missing_ownership_pixels"] == 0
    assert report["metrics"]["complement_mismatch_pixels"] == 0
    assert report["metrics"]["identity_bleed_pixels"] == 4
    assert results["DAZ-V7-003"]["status"] == "fail"
    assert results["DAZ-V7-004"]["status"] == "pass"
    assert results["DAZ-V7-005"]["status"] == "pass"
    assert results["DAZ-V7-006"]["status"] == "pass"
    assert report["summary"]["acceptance_eligible"] is False


def test_assignment_or_derivation_rebinding_fails_before_semantic_acceptance(
    tmp_path: Path,
) -> None:
    arguments, _derivation = _fixture(tmp_path)
    tampered_assignment = copy.deepcopy(arguments["assignment"])
    tampered_assignment["mapping"].reverse()
    arguments["assignment"] = tampered_assignment
    with pytest.raises(MultiPersonIdentityValidationError, match="assignment_invalid"):
        evaluate_multi_person_identity(**arguments)
    arguments, _derivation = _fixture(tmp_path / "derivation")
    arguments["derivation_report"]["image_id"] = "rebound"
    with pytest.raises(MultiPersonIdentityValidationError, match="document_hash_invalid"):
        evaluate_multi_person_identity(**arguments)


def test_report_schema_hash_and_publication_are_fail_closed(tmp_path: Path) -> None:
    arguments, _derivation = _fixture(tmp_path)
    report = evaluate_multi_person_identity(**arguments)
    tampered = copy.deepcopy(report)
    tampered["undeclared"] = True
    with pytest.raises(ArtifactValidationError, match="Additional properties"):
        validate_multi_person_identity_report(tampered)
    tampered = copy.deepcopy(report)
    tampered["summary"]["passed_count"] -= 1
    with pytest.raises(MultiPersonIdentityValidationError, match="document_hash_invalid"):
        validate_multi_person_identity_report(tampered)
    target, published = publish_multi_person_identity_report(report, tmp_path / "reports")
    assert published is True
    assert publish_multi_person_identity_report(report, tmp_path / "reports") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(MultiPersonIdentityValidationError, match="publication_conflict"):
        publish_multi_person_identity_report(report, tmp_path / "reports")


def test_cli_publishes_and_replays_blocking_v7_report(tmp_path: Path) -> None:
    arguments, derivation_report = _fixture(tmp_path)
    paths = {}
    for name, document in {
        "contract": arguments["contract"],
        "derivation": derivation_report,
        "assignment": arguments["assignment"],
    }.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "reports"
    command = [
        "daz",
        "recipes",
        "validate-multi-person-identity",
        "--contract",
        str(paths["contract"]),
        "--derivation-report",
        str(paths["derivation"]),
        "--assignment",
        str(paths["assignment"]),
        "--construction-map",
        str(arguments["construction_map_path"]),
        "--instance-map",
        str(arguments["instance_map_path"]),
        "--derived-scene-root",
        str(arguments["derived_scene_root"]),
        "--policy",
        str(POLICY),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_multi_person_identity_valid"
    assert payload["data"]["summary"]["passed"] is True
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
