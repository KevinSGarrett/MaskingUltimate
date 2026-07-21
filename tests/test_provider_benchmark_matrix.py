from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.provider_matrix import (
    POLICY_SHA256,
    PROVIDER_ARTIFACT_KEYS,
    ProviderMatrixError,
    canonical_sha256,
    expected_enrichment_cells,
    expected_screening_cells,
    load_policy,
    measurement_bundle_sha256,
    seal_manifest,
    validate_manifest,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _draft(selected: tuple[str, ...] = ("sam2_1_only",)) -> dict[str, object]:
    policy = load_policy()
    shared = {
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "image_disjoint": True,
        "evaluation_set_sha256": _hash("evaluation"),
        "prompt_set_sha256": _hash("prompts"),
        "part_set_sha256": _hash("parts"),
        "hardware_profile_sha256": _hash("hardware"),
        "qa_sha256": policy["source_hashes"]["configs/qa.yaml"],
        "pipeline_sha256": policy["source_hashes"]["configs/pipeline.yaml"],
        "ontology_sha256": policy["source_hashes"]["configs/ontology_v2.yaml"],
        "measurement_bundle_sha256": measurement_bundle_sha256(policy),
        "provider_artifact_sha256": {
            key: _hash(f"artifact-{key}") for key in PROVIDER_ARTIFACT_KEYS
        },
    }
    shared_sha = canonical_sha256(shared)
    return {
        "schema_version": "1.0.0",
        "matrix_id": "provider_benchmark_matrix_v1",
        "opened_at": "2026-07-15T11:06:00Z",
        "policy_sha256": POLICY_SHA256,
        "authority": "immutable_matrix_identity_only_no_metric_result_or_authority",
        "shared_identity": shared,
        "screening_cells": expected_screening_cells(shared_sha),
        "finalist_selection": {
            "screening_result_sha256": _hash("sealed-screening-result"),
            "selected_routes": list(selected),
        },
        "enrichment_cells": expected_enrichment_cells(selected, shared_sha),
    }


def _rehash(document: dict[str, object]) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )


def test_policy_is_frozen_before_results_and_sources_are_exact() -> None:
    policy = load_policy()
    validate_policy(policy)
    assert policy["sha256"] == POLICY_SHA256
    assert len(policy["screening_routes"]) == 6
    assert len(policy["required_measurements"]) == 19


def test_one_finalist_expands_exact_sixty_cell_grid() -> None:
    manifest = seal_manifest(_draft())
    validate_manifest(manifest)
    assert len(manifest["screening_cells"]) == 6
    assert len(manifest["enrichment_cells"]) == 60
    assert manifest["authority"] == "immutable_matrix_identity_only_no_metric_result_or_authority"


def test_every_selected_finalist_expands_the_full_grid() -> None:
    selected = ("sam2_1_only", "rfdetr_detection_sam3_1_refinement")
    manifest = seal_manifest(_draft(selected))
    assert len(manifest["enrichment_cells"]) == 120
    assert {row["base_route_id"] for row in manifest["enrichment_cells"]} == set(selected)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("truth_tier", "autonomous_certified_gold"),
        ("truth_partition", "train"),
        ("image_disjoint", False),
        ("qa_sha256", "0" * 64),
        ("pipeline_sha256", "0" * 64),
        ("ontology_sha256", "0" * 64),
        ("measurement_bundle_sha256", "0" * 64),
    ],
)
def test_shared_identity_drift_fails_closed(field: str, value: object) -> None:
    manifest = seal_manifest(_draft())
    manifest["shared_identity"][field] = value
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError):
        validate_manifest(manifest)


def test_shared_identity_hashes_cannot_be_conflated() -> None:
    manifest = seal_manifest(_draft())
    manifest["shared_identity"]["prompt_set_sha256"] = manifest["shared_identity"][
        "evaluation_set_sha256"
    ]
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="conflated"):
        validate_manifest(manifest)


def test_provider_artifact_set_and_hashes_are_exact() -> None:
    manifest = seal_manifest(_draft())
    del manifest["shared_identity"]["provider_artifact_sha256"]["sam3_1"]
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError):
        validate_manifest(manifest)

    manifest = seal_manifest(_draft())
    manifest["shared_identity"]["provider_artifact_sha256"]["sam3_1"] = "z" * 64
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError):
        validate_manifest(manifest)


def test_screening_cell_missing_reordered_or_substituted_fails() -> None:
    manifest = seal_manifest(_draft())
    manifest["screening_cells"][0]["provider_artifact_keys"] = ["sam3_1"]
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="screening cells"):
        validate_manifest(manifest)

    manifest = seal_manifest(_draft())
    manifest["screening_cells"].reverse()
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="screening cells"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "selected",
    [
        [],
        ["unknown_route"],
        ["sam2_1_only", "sam2_1_only"],
    ],
)
def test_invalid_finalist_selection_fails_closed(selected: list[str]) -> None:
    manifest = seal_manifest(_draft())
    manifest["finalist_selection"]["selected_routes"] = selected
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError):
        validate_manifest(manifest)


def test_screening_result_hash_is_mandatory() -> None:
    manifest = seal_manifest(_draft())
    manifest["finalist_selection"]["screening_result_sha256"] = "z" * 64
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError):
        validate_manifest(manifest)


def test_enrichment_cell_missing_or_substituted_fails_closed() -> None:
    manifest = seal_manifest(_draft(("sam2_1_only", "rfdetr_detection_sam3_1_refinement")))
    manifest["enrichment_cells"].pop()
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="enrichment grid"):
        validate_manifest(manifest)

    manifest = seal_manifest(_draft())
    manifest["enrichment_cells"][0]["pose"] = "unapproved_pose"
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="enrichment grid"):
        validate_manifest(manifest)


def test_policy_and_open_time_must_predate_manifest() -> None:
    manifest = seal_manifest(_draft())
    manifest["opened_at"] = "2026-07-15T11:04:59Z"
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="before policy freeze"):
        validate_manifest(manifest)

    manifest = seal_manifest(_draft())
    manifest["policy_sha256"] = "0" * 64
    _rehash(manifest)
    with pytest.raises(ProviderMatrixError, match="policy hash"):
        validate_manifest(manifest)


def test_manifest_hash_tamper_and_presealed_draft_fail() -> None:
    manifest = seal_manifest(_draft())
    manifest["sha256"] = "0" * 64
    with pytest.raises(ProviderMatrixError, match="manifest hash"):
        validate_manifest(manifest)
    with pytest.raises(ProviderMatrixError, match="already sealed"):
        seal_manifest(manifest)


def test_policy_semantic_drift_fails_even_when_rehashed() -> None:
    policy = copy.deepcopy(load_policy())
    policy["finalist_contract"]["minimum_count"] = 0
    _rehash(policy)
    with pytest.raises(ProviderMatrixError, match="finalist contract"):
        validate_policy(policy, expected_sha256=None)


def test_cli_seals_and_verifies_manifest(tmp_path: Path) -> None:
    draft = tmp_path / "draft.json"
    manifest = tmp_path / "manifest.json"
    draft.write_text(json.dumps(_draft()), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/provider_benchmark_matrix.py"),
        str(draft),
        "--output",
        str(manifest),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/provider_benchmark_matrix.py"),
            str(manifest),
            "--verify",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
