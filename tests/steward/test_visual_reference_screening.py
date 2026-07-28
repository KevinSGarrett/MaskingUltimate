from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from maskfactory.steward.continuous_contract import canonical_sha256
from maskfactory.steward.visual_reference_screening import (
    VisualReferenceScreeningError,
    validate_direct_reference_screening,
)


def _receipt(tmp_path: Path, *, decision: str = "reference_only_visual_target_confirmed") -> dict:
    repository_root = tmp_path / "repo"
    readiness_path = repository_root / "qa" / "readiness.json"
    readiness_path.parent.mkdir(parents=True)
    readiness = {
        "self_sha256": "r" * 64,
        "authority_boundary": {"promotion_allowed": False},
        "readiness": {"metadata_candidate_selection_requires_direct_visual_confirmation": True},
    }
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    materialized_root = tmp_path / "references"
    image_path = materialized_root / "benchmark_reference" / "candidate.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (12, 8), "white").save(image_path)
    receipt = {
        "authority_boundary": {
            "candidate_materialization_allowed": False,
            "critic_qualification_allowed": False,
            "mask_generation_allowed": False,
            "promotion_allowed": False,
            "reason": "reference-only",
        },
        "reference_readiness_binding": {
            "path": "qa/readiness.json",
            "raw_sha256": hashlib.sha256(readiness_path.read_bytes()).hexdigest(),
            "self_sha256": readiness["self_sha256"],
        },
        "review": {
            "decision": decision,
            "evidence_basis": "direct_pixel_review",
            "metadata_hint": "hands_visible",
            "observed_content": "A hand is visible.",
            "reviewer": "test",
            "target_role": "part_hand_fingers",
            **(
                {"reason": "metadata_tag_not_visually_confirmed"}
                if decision == "rejected_for_hand_finger_candidate_selection"
                else {}
            ),
        },
        "schema_version": "maskfactory.visual_reference_direct_screening.v1",
        "screened_image": {
            "bytes": image_path.stat().st_size,
            "dimensions": {"height": 8, "width": 12},
            "materialized_relative_path": "benchmark_reference/candidate.png",
            "relative_path": "source/candidate.png",
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "source_group": "test",
        },
        "self_sha256": "0" * 64,
    }
    receipt["self_sha256"] = canonical_sha256(receipt)
    return receipt


def test_validates_confirmed_reference_without_authority(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    validate_direct_reference_screening(
        receipt,
        repository_root=tmp_path / "repo",
        materialized_root=tmp_path / "references",
    )


def test_validates_rejection_with_required_reason(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path, decision="rejected_for_hand_finger_candidate_selection")
    validate_direct_reference_screening(
        receipt,
        repository_root=tmp_path / "repo",
        materialized_root=tmp_path / "references",
    )


def test_rejects_authority_escalation(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    receipt["authority_boundary"]["promotion_allowed"] = True
    receipt["self_sha256"] = canonical_sha256({**receipt, "self_sha256": "0" * 64})
    with pytest.raises(VisualReferenceScreeningError, match="authority boundary"):
        validate_direct_reference_screening(
            receipt,
            repository_root=tmp_path / "repo",
            materialized_root=tmp_path / "references",
        )


def test_rejects_image_hash_drift(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    image = tmp_path / "references" / "benchmark_reference" / "candidate.png"
    image.write_bytes(b"drift")
    with pytest.raises(VisualReferenceScreeningError, match="image binding drifted"):
        validate_direct_reference_screening(
            receipt,
            repository_root=tmp_path / "repo",
            materialized_root=tmp_path / "references",
        )
