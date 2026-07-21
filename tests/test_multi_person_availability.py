from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.autonomy.multi_person_availability import (
    DEFAULT_MODEL_REGISTRY,
    DEFAULT_POLICY,
    DEFAULT_RUNTIME_MATRIX,
    LOCKED_POLICY_SHA256,
    MultiPersonAvailabilityError,
    build_multi_person_availability_snapshot,
)
from maskfactory.providers.provider_matrix import canonical_sha256
from maskfactory.validation import validate_document


def _write_runtime(tmp_path: Path, mutation=None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    document = json.loads(DEFAULT_RUNTIME_MATRIX.read_text(encoding="utf-8"))
    if mutation is not None:
        mutation(document)
    document["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    path = tmp_path / "provider_runtime_matrix.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _write_registry(tmp_path: Path, mutation) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    document = json.loads(DEFAULT_MODEL_REGISTRY.read_text(encoding="utf-8"))
    mutation(document)
    path = tmp_path / "model_registry.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _models(document: dict, *keys: str) -> list[dict]:
    wanted = set(keys)
    return [row for row in document["models"] if row["key"] in wanted]


def test_locked_policy_and_live_repository_snapshot_are_exact() -> None:
    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    assert not validate_document(policy, "multi_person_family_availability_policy")
    assert policy["sha256"] == LOCKED_POLICY_SHA256
    snapshot = build_multi_person_availability_snapshot()
    expected = {
        "deterministic_repair": True,
        "fusion": True,
        "geometry": True,
        "pose": True,
        "rf_detr_detection": True,
        "sam21_refinement": True,
        "sam31_exhaustive_discovery": False,
        "sam31_refinement": False,
        "silhouette": True,
        "specialist": True,
    }
    assert {key: row["available"] for key, row in snapshot["families"].items()} == expected
    assert snapshot["sha256"] == canonical_sha256(
        {key: value for key, value in snapshot.items() if key != "sha256"}
    )


def test_qualified_runtime_makes_both_sam31_routes_available(tmp_path: Path) -> None:
    def qualify(document: dict) -> None:
        row = next(item for item in document["runtimes"] if item["provider"] == "sam3_1")
        row.update(
            status="live_smoke_passed",
            checkpoint_status="installed",
            smoke_status="pass",
        )
        row.pop("needs_kevin", None)

    snapshot = build_multi_person_availability_snapshot(
        runtime_matrix_path=_write_runtime(tmp_path, qualify)
    )
    assert snapshot["families"]["sam31_exhaustive_discovery"]["available"] is True
    assert snapshot["families"]["sam31_refinement"]["available"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: [row.update(lifecycle_state="planned") for row in rows],
        lambda rows: [row.update(verified=False) for row in rows],
        lambda rows: [row["license_review"].update(status="pending") for row in rows],
        lambda rows: [row.pop("sha256", None) for row in rows],
    ],
)
def test_registry_lifecycle_verification_license_and_hash_gate_availability(
    tmp_path: Path, mutation
) -> None:
    def change(document: dict) -> None:
        mutation(_models(document, "sam2_1_hiera_large", "sam2_1_hiera_base_plus"))

    snapshot = build_multi_person_availability_snapshot(
        model_registry_path=_write_registry(tmp_path, change)
    )
    family = snapshot["families"]["sam21_refinement"]
    assert family["available"] is False
    assert family["reason_code"] == "no_governed_source_eligible"


def test_runtime_status_checkpoint_and_smoke_are_all_required(tmp_path: Path) -> None:
    for index, field in enumerate(("status", "checkpoint_status", "smoke_status")):
        folder = tmp_path / str(index)
        folder.mkdir()

        def change(document: dict, field=field) -> None:
            row = next(item for item in document["runtimes"] if item["provider"] == "rfdetr")
            row[field] = "not_qualified"

        snapshot = build_multi_person_availability_snapshot(
            runtime_matrix_path=_write_runtime(folder, change)
        )
        assert snapshot["families"]["rf_detr_detection"]["available"] is False


def test_runtime_artifact_hash_manifest_and_locked_policy_tampering_fail(tmp_path: Path) -> None:
    def stale_artifact(document: dict) -> None:
        row = next(item for item in document["runtimes"] if item["provider"] == "rfdetr")
        row["artifacts"][0]["sha256"] = "0" * 64

    with pytest.raises(MultiPersonAvailabilityError, match="artifact is missing or stale"):
        build_multi_person_availability_snapshot(
            runtime_matrix_path=_write_runtime(tmp_path / "artifact", stale_artifact)
        )

    runtime = _write_runtime(tmp_path / "manifest")
    document = json.loads(runtime.read_text(encoding="utf-8"))
    document["runtimes"][0]["status"] = "rebound"
    runtime.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MultiPersonAvailabilityError, match="manifest hash drifted"):
        build_multi_person_availability_snapshot(runtime_matrix_path=runtime)

    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    policy["families"]["fusion"]["clauses"][0]["keys"] = ["different.py"]
    policy["sha256"] = canonical_sha256(
        {key: value for key, value in policy.items() if key != "sha256"}
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(MultiPersonAvailabilityError, match="policy hash drifted"):
        build_multi_person_availability_snapshot(policy_path=policy_path)


def test_missing_governed_source_is_unavailable_not_fabricated(tmp_path: Path) -> None:
    def remove_runtime(document: dict) -> None:
        document["runtimes"] = [row for row in document["runtimes"] if row["provider"] != "rfdetr"]

    snapshot = build_multi_person_availability_snapshot(
        runtime_matrix_path=_write_runtime(tmp_path, remove_runtime)
    )
    clause = snapshot["families"]["rf_detr_detection"]["clauses"][0]
    assert clause["eligible"] is False
    assert clause["evidence"] == [{"key": "rfdetr", "status": "missing", "identity_sha256": None}]
