import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

import maskfactory.models.registry as registry_module
from maskfactory.cli import main
from maskfactory.models.ontology_contract import (
    V1_ONTOLOGY_VERSION,
    V1_PART_CLASS_NAMES,
    class_names_sha256,
)
from maskfactory.models.registry import (
    ModelRegistryError,
    load_promotion_transaction,
    production_bodypart_serving_smoke,
    promote_custom_segmenter_role,
    rollback_custom_segmenter_role,
)
from maskfactory.training.promotion_policy import (
    CERTIFICATE_AUTHORITY,
    REQUIRED_CERTIFICATE_IDENTITY_HASHES,
    REQUIRED_RESULT_INPUT_HASHES,
    load_custom_segmenter_margin_manifest,
)
from registry_helpers import ALLOWED_CONTENT, governed_file_model, governed_registry


def _sha256(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _digest(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _legacy_certificate() -> dict:
    certificate = {
        "schema_version": "1.0.0",
        "target_role": "champion_bodypart",
        "primary_win_or_labor_reduction": True,
        "hard_bucket_results": [
            {
                "bucket": "fixture",
                "observed_delta": 0.01,
                "noninferiority_margin": 0.0,
                "passed": True,
            }
        ],
        "frozen_eval_sha256": "a" * 64,
        "issued_at": "2026-07-15T05:30:00Z",
    }
    certificate["sha256"] = _sha256(certificate)
    return certificate


def _certificate(candidate_hash: str) -> tuple[dict, dict]:
    manifest, margins = load_custom_segmenter_margin_manifest()
    input_hashes = {key: _digest(key) for key in REQUIRED_RESULT_INPUT_HASHES}
    results = {
        "schema_version": "1.0.0",
        "benchmark_id": "custom-segmenter-transaction-fixture-v1",
        "role": "custom_segmenter",
        "margin_manifest_sha256": manifest["sha256"],
        "results_opened_at": "2026-07-15T05:30:00Z",
        "input_hashes": input_hashes,
        "primary_objective_result": {
            "metric": manifest["role"]["primary_objective"]["metric"],
            "observed_improvement": 0.005,
            "minimum_improvement": manifest["role"]["primary_objective"]["minimum_improvement"],
            "passed": True,
        },
        "labor_objective_result": {
            "metric": manifest["role"]["labor_objective"]["metric"],
            "observed_improvement": 0.0,
            "minimum_improvement": manifest["role"]["labor_objective"]["minimum_improvement"],
            "passed": False,
        },
        "rows": [
            {
                "bucket": bucket,
                "observed_delta": 0.0,
                "noninferiority_margin": margin,
                "passed": True,
            }
            for bucket, margin in sorted(margins.items())
        ],
    }
    results["sha256"] = _sha256(results)
    identities = {key: _digest(key) for key in REQUIRED_CERTIFICATE_IDENTITY_HASHES}
    identities.update(input_hashes)
    identities["benchmark_results_sha256"] = results["sha256"]
    identities["checkpoint_sha256"] = candidate_hash
    certificate = {
        "schema_version": "1.0.0",
        "authority": CERTIFICATE_AUTHORITY,
        "candidate_key": "eomt_dinov3_fixture",
        "target_role": "custom_segmenter",
        "lifecycle_state": "benchmarked",
        "identity_hashes": identities,
        "content_compatibility": dict(ALLOWED_CONTENT),
        "license_gate": {"verify_license": False, "checkpoint_decision": "allowed"},
        "benchmark_results": results,
        "rollback_evidence": {
            "candidate_provider": "eomt_dinov3_fixture",
            "incumbent_provider": "segformer_b2_fixture",
            "target_role": "custom_segmenter",
            "one_command": "maskfactory models rollback-custom-segmenter TRANSACTION_ID",
            "rollback_observed": True,
            "restore_observed": True,
            "result": "pass",
            "tested_at": "2026-07-15T05:45:00Z",
            "evidence_sha256": _digest("rollback"),
        },
    }
    certificate["sha256"] = _sha256(certificate)
    return certificate, copy.deepcopy(identities)


def _workspace(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    models_root = tmp_path / "models"
    models_root.mkdir()
    candidate_checkpoint = models_root / "candidate.pth"
    incumbent_checkpoint = models_root / "incumbent.pth"
    candidate_config = models_root / "candidate.py"
    incumbent_config = models_root / "incumbent.py"
    candidate_checkpoint.write_bytes(b"candidate-checkpoint")
    incumbent_checkpoint.write_bytes(b"incumbent-checkpoint")
    candidate_config.write_text("model = dict(type='candidate')\n", encoding="utf-8")
    incumbent_config.write_text("model = dict(type='incumbent')\n", encoding="utf-8")
    common = {
        "ontology_version": V1_ONTOLOGY_VERSION,
        "class_names": list(V1_PART_CLASS_NAMES),
        "class_names_sha256": class_names_sha256(list(V1_PART_CLASS_NAMES)),
        "benchmark_certificate": _legacy_certificate(),
    }
    candidate_hash = _digest(candidate_checkpoint.read_bytes())
    incumbent_hash = _digest(incumbent_checkpoint.read_bytes())
    candidate_config_hash = _digest(candidate_config.read_bytes())
    incumbent_config_hash = _digest(incumbent_config.read_bytes())
    candidate = governed_file_model(
        key="eomt_dinov3_fixture",
        role="challenger_bodypart",
        file="models/candidate.pth",
        sha256=candidate_hash,
        lifecycle_state="benchmarked",
        inference_config="models/candidate.py",
        inference_config_sha256=candidate_config_hash,
        artifact_hashes={
            "checkpoint_sha256": candidate_hash,
            "inference_config_sha256": candidate_config_hash,
        },
        **common,
    )
    incumbent = governed_file_model(
        key="segformer_b2_fixture",
        role="champion_bodypart",
        file="models/incumbent.pth",
        sha256=incumbent_hash,
        lifecycle_state="promoted",
        inference_config="models/incumbent.py",
        inference_config_sha256=incumbent_config_hash,
        artifact_hashes={
            "checkpoint_sha256": incumbent_hash,
            "inference_config_sha256": incumbent_config_hash,
        },
        **common,
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry([candidate, incumbent])), encoding="utf-8")
    certificate, identities = _certificate(candidate_hash)
    return registry, models_root, certificate, identities


def _passing_smoke(calls: list[tuple[str, str]]):
    def run(registry: Path, _models: Path, role: str, expected: str) -> dict:
        document = json.loads(registry.read_text(encoding="utf-8"))
        owner = next(entry for entry in document["models"] if entry["role"] == role)
        assert owner["key"] == expected
        calls.append((role, expected))
        return {"result": "pass", "runtime": "pytest", "model_key": expected}

    return run


def test_production_smoke_runs_fixed_image_through_serving_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, models_root, _, _ = _workspace(tmp_path)
    closed: list[bool] = []

    class Slot:
        class_names = tuple(V1_PART_CLASS_NAMES)

        def __call__(self, image: np.ndarray, requested: tuple[str, ...]):
            return {name: np.zeros(image.shape[:2], dtype=bool) for name in requested}

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        "maskfactory.serve.providers.load_production_mmseg_slot",
        lambda *_args, **_kwargs: Slot(),
    )
    result = production_bodypart_serving_smoke(
        registry, models_root, "champion_bodypart", "segformer_b2_fixture"
    )
    assert result["result"] == "pass"
    assert result["smoke"] == "production_fixed_image_inference"
    assert len(result["output_map_sha256"]) == 64
    assert len(result["output_provenance_sha256"]) == 64
    assert closed == [True]


def test_custom_segmenter_promotion_and_rollback_are_transactional(tmp_path: Path) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    history = tmp_path / "history.jsonl"
    calls: list[tuple[str, str]] = []
    record = promote_custom_segmenter_role(
        "eomt_dinov3_fixture",
        certificate,
        identities,
        registry_path=registry,
        models_root=models_root,
        history_path=history,
        smoke_runner=_passing_smoke(calls),
        promoted_at="2026-07-15T06:00:00Z",
    )
    promoted = {entry["key"]: entry for entry in json.loads(registry.read_text())["models"]}
    assert (
        promoted["eomt_dinov3_fixture"]["role"],
        promoted["eomt_dinov3_fixture"]["lifecycle_state"],
    ) == ("champion_bodypart", "promoted")
    assert (
        promoted["segformer_b2_fixture"]["role"],
        promoted["segformer_b2_fixture"]["lifecycle_state"],
    ) == ("challenger_bodypart", "benchmarked")
    assert load_promotion_transaction(record["transaction_id"], history_path=history) == record

    rollback = rollback_custom_segmenter_role(
        record,
        registry_path=registry,
        models_root=models_root,
        history_path=history,
        smoke_runner=_passing_smoke(calls),
        rolled_back_at="2026-07-15T06:05:00Z",
    )
    restored = {entry["key"]: entry for entry in json.loads(registry.read_text())["models"]}
    assert (
        restored["eomt_dinov3_fixture"]["role"],
        restored["eomt_dinov3_fixture"]["lifecycle_state"],
    ) == ("challenger_bodypart", "benchmarked")
    assert (
        restored["segformer_b2_fixture"]["role"],
        restored["segformer_b2_fixture"]["lifecycle_state"],
    ) == ("champion_bodypart", "promoted")
    assert rollback["promotion_transaction_id"] == record["transaction_id"]
    assert calls == [
        ("champion_bodypart", "eomt_dinov3_fixture"),
        ("champion_bodypart", "segformer_b2_fixture"),
    ]
    assert len(history.read_text().splitlines()) == 2
    with pytest.raises(ModelRegistryError, match="already rolled back"):
        load_promotion_transaction(record["transaction_id"], history_path=history)


def test_promotion_smoke_failure_leaves_registry_and_history_untouched(tmp_path: Path) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    original = registry.read_bytes()
    history = tmp_path / "history.jsonl"

    def fail(*_args) -> dict:
        raise RuntimeError("fixture runtime failed")

    with pytest.raises(ModelRegistryError, match="serving smoke failed"):
        promote_custom_segmenter_role(
            "eomt_dinov3_fixture",
            certificate,
            identities,
            registry_path=registry,
            models_root=models_root,
            history_path=history,
            smoke_runner=fail,
        )
    assert registry.read_bytes() == original
    assert not history.exists()


def test_history_failure_restores_registry(tmp_path: Path) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    original = json.loads(registry.read_text())
    history = tmp_path / "history-directory"
    history.mkdir()
    with pytest.raises(ModelRegistryError, match="history failed; registry restored"):
        promote_custom_segmenter_role(
            "eomt_dinov3_fixture",
            certificate,
            identities,
            registry_path=registry,
            models_root=models_root,
            history_path=history,
            smoke_runner=_passing_smoke([]),
        )
    assert json.loads(registry.read_text()) == original


def test_rollback_rejects_tamper_or_post_promotion_registry_change(tmp_path: Path) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    record = promote_custom_segmenter_role(
        "eomt_dinov3_fixture",
        certificate,
        identities,
        registry_path=registry,
        models_root=models_root,
        history_path=tmp_path / "history.jsonl",
        smoke_runner=_passing_smoke([]),
    )
    tampered = copy.deepcopy(record)
    tampered["incumbent_key"] = "attacker"
    with pytest.raises(ModelRegistryError, match="record hash mismatch"):
        rollback_custom_segmenter_role(tampered, registry_path=registry)
    document = json.loads(registry.read_text())
    document["models"][0]["version_tag"] = "changed-after-promotion"
    registry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="registry changed"):
        rollback_custom_segmenter_role(record, registry_path=registry)


def test_rollback_smoke_failure_preserves_promoted_state(tmp_path: Path) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    history = tmp_path / "history.jsonl"
    record = promote_custom_segmenter_role(
        "eomt_dinov3_fixture",
        certificate,
        identities,
        registry_path=registry,
        models_root=models_root,
        history_path=history,
        smoke_runner=_passing_smoke([]),
    )
    promoted = registry.read_bytes()
    with pytest.raises(ModelRegistryError, match="serving smoke did not return"):
        rollback_custom_segmenter_role(
            record,
            registry_path=registry,
            models_root=models_root,
            history_path=history,
            smoke_runner=lambda *_args: {"result": "fail"},
        )
    assert registry.read_bytes() == promoted
    assert len(history.read_text().splitlines()) == 1


def test_rollback_history_failure_restores_promoted_registry(tmp_path: Path) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    history = tmp_path / "history.jsonl"
    record = promote_custom_segmenter_role(
        "eomt_dinov3_fixture",
        certificate,
        identities,
        registry_path=registry,
        models_root=models_root,
        history_path=history,
        smoke_runner=_passing_smoke([]),
    )
    promoted = json.loads(registry.read_text())
    history.unlink()
    history.mkdir()
    with pytest.raises(ModelRegistryError, match="history failed; promoted registry restored"):
        rollback_custom_segmenter_role(
            record,
            registry_path=registry,
            models_root=models_root,
            history_path=history,
            smoke_runner=_passing_smoke([]),
        )
    assert json.loads(registry.read_text()) == promoted


def test_cli_provides_one_command_rollback_with_runtime_smoke_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, models_root, certificate, identities = _workspace(tmp_path)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(registry_module, "production_bodypart_serving_smoke", _passing_smoke(calls))
    history = tmp_path / "history.jsonl"
    certificate_path = tmp_path / "certificate.json"
    identities_path = tmp_path / "identities.json"
    certificate_path.write_text(json.dumps(certificate), encoding="utf-8")
    identities_path.write_text(json.dumps(identities), encoding="utf-8")
    runner = CliRunner()
    promoted = runner.invoke(
        main,
        [
            "models",
            "promote-custom-segmenter",
            "eomt_dinov3_fixture",
            "--certificate",
            str(certificate_path),
            "--identity-hashes",
            str(identities_path),
            "--registry",
            str(registry),
            "--models-root",
            str(models_root),
            "--history",
            str(history),
        ],
    )
    assert promoted.exit_code == 0, promoted.output
    transaction_id = json.loads(promoted.output)["transaction_id"]
    rolled_back = runner.invoke(
        main,
        [
            "models",
            "rollback-custom-segmenter",
            transaction_id,
            "--registry",
            str(registry),
            "--models-root",
            str(models_root),
            "--history",
            str(history),
        ],
    )
    assert rolled_back.exit_code == 0, rolled_back.output
    assert json.loads(rolled_back.output)["action"] == "rollback"
    assert calls == [
        ("champion_bodypart", "eomt_dinov3_fixture"),
        ("champion_bodypart", "segformer_b2_fixture"),
    ]
