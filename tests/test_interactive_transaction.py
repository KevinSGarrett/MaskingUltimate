import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.orchestrator import load_pipeline_config
from maskfactory.providers.interactive_promotion import build_interactive_promotion_certificate
from maskfactory.providers.interactive_transaction import (
    InteractiveProviderTransactionError,
    build_smoke_evidence,
    load_interactive_promotion,
    promote_interactive_provider,
    rollback_interactive_provider,
)
from maskfactory.providers.provider_matrix import (
    canonical_sha256,
    expected_enrichment_cells,
    expected_screening_cells,
    seal_manifest,
)
from maskfactory.providers.provider_matrix_metrics import build_report
from maskfactory.providers.selection import validate_provider_selection
from maskfactory.validation import validate_document
from test_matrix_promotion import ROLE_ARTIFACTS, _build, _bundle, _fixture
from test_provider_benchmark_matrix_metrics import _observations

ROOT = Path(__file__).resolve().parents[1]


def _seal(value: dict) -> None:
    value["sha256"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "sha256"}
    )


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_smoke_evidence(
    path: Path,
    *,
    pipeline_path: Path,
    external_path: Path,
    model_path: Path,
    smoke: dict,
) -> None:
    document = build_smoke_evidence(
        pipeline_path=pipeline_path,
        external_registry_path=external_path,
        model_registry_path=model_path,
        smoke=smoke,
    )
    path.write_text(json.dumps(document), encoding="utf-8")


def _transaction_fixture(tmp_path: Path) -> dict:
    project = tmp_path / "project"
    configs = project / "configs"
    models_root = project / "models"
    env = project / "env"
    configs.mkdir(parents=True)
    env.mkdir(parents=True)
    candidate_path = models_root / "sam3" / "candidate.pt"
    incumbent_path = models_root / "sam2" / "incumbent.pt"
    candidate_path.parent.mkdir(parents=True)
    incumbent_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(b"official-sam31-candidate-fixture")
    incumbent_path.write_bytes(b"sam21-incumbent-fixture")
    candidate_sha = _sha(candidate_path.read_bytes())
    incumbent_sha = _sha(incumbent_path.read_bytes())
    runtime_lock = env / "sam31_runtime.lock.json"
    runtime_lock.write_text('{"provider":"sam3_1","fixture":true}\n', encoding="utf-8")
    runtime_sha = _sha(runtime_lock.read_bytes())

    matrix = _fixture(tmp_path / "matrix")
    old_manifest = matrix["matrix_manifest"]
    draft = copy.deepcopy({key: value for key, value in old_manifest.items() if key != "sha256"})
    artifacts = draft["shared_identity"]["provider_artifact_sha256"]
    artifacts["sam3_1"] = candidate_sha
    artifacts["sam2_1"] = incumbent_sha
    shared_sha = canonical_sha256(draft["shared_identity"])
    selected = tuple(draft["finalist_selection"]["selected_routes"])
    draft["screening_cells"] = expected_screening_cells(shared_sha)
    draft["enrichment_cells"] = expected_enrichment_cells(selected, shared_sha)
    manifest = seal_manifest(draft)
    observations = _observations(manifest)
    report = build_report(observations, manifest)
    matrix["matrix_manifest"] = manifest
    matrix["matrix_observations"] = observations
    matrix["matrix_report"] = report
    for role, artifact_key in ROLE_ARTIFACTS.items():
        if artifact_key in {"sam3_1", "sam2_1"}:
            packet = matrix["specialist_packets"][role]
            packet["identity_hashes"]["checkpoint_sha256"] = artifacts[artifact_key]
            _seal(packet)
    aggregate = _build(matrix)
    bundle = _bundle(tmp_path / "bundle", matrix, aggregate)

    pipeline = load_pipeline_config(ROOT / "configs" / "pipeline.yaml")
    pipeline_path = configs / "pipeline.yaml"
    pipeline_path.write_text(
        yaml.safe_dump(pipeline, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    external = yaml.safe_load((ROOT / "configs/external_sources.yaml").read_text(encoding="utf-8"))
    candidate = external["providers"]["sam3_1"]
    candidate["lifecycle_state"] = "benchmarked"
    candidate["checkpoint"]["sha256"] = candidate_sha
    candidate["checkpoint"]["size_bytes"] = candidate_path.stat().st_size
    candidate["runtime_lock"] = "env/sam31_runtime.lock.json"
    candidate["license_layers"] = copy.deepcopy(
        external["providers"]["sam3_litetext_s0"]["license_layers"]
    )
    benchmark = {
        "schema_version": "1.0.0",
        "target_role": "interactive_segmenter",
        "primary_win_or_labor_reduction": True,
        "hard_bucket_results": [
            {
                "bucket": "hands_feet_multi_person",
                "observed_delta": 0.01,
                "noninferiority_margin": 0.02,
                "passed": True,
            }
        ],
        "frozen_eval_sha256": report["sha256"],
        "issued_at": "2026-07-17T00:00:00Z",
    }
    _seal(benchmark)
    candidate["benchmark_certificate"] = benchmark
    external_path = configs / "external_sources.yaml"
    external_path.write_text(
        yaml.safe_dump(external, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    model_registry = json.loads((ROOT / "models/model_registry.json").read_text(encoding="utf-8"))
    incumbent = next(row for row in model_registry["models"] if row["key"] == "sam2_1_hiera_large")
    incumbent["file"] = "models/sam2/incumbent.pt"
    incumbent["sha256"] = incumbent_sha
    incumbent["lifecycle_state"] = "promoted"
    model_path = models_root / "model_registry.json"
    model_path.write_text(
        json.dumps(model_registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    before_pipeline = pipeline_path.read_bytes()
    proposed_pipeline = copy.deepcopy(pipeline)
    role = proposed_pipeline["provider_roles"]["interactive_segmenter"]
    role["active"] = "sam3_1"
    role["challengers"] = [
        "sam2_1_large",
        *[key for key in role["challengers"] if key not in {"sam3_1", "sam2_1_large"}],
    ]
    role["rollback"] = "sam2_1_large"
    proposed_pipeline["stages"]["S07"]["primary_model"] = "sam3_1"
    promoted_pipeline = yaml.safe_dump(
        proposed_pipeline, sort_keys=False, allow_unicode=True
    ).encode("utf-8")
    rollback = {
        "schema_version": "1.0.0",
        "target_role": "interactive_segmenter",
        "candidate_provider": "sam3_1",
        "incumbent_provider": "sam2_1_large",
        "pipeline_before_sha256": _sha(before_pipeline),
        "pipeline_promoted_sha256": _sha(promoted_pipeline),
        "pipeline_restored_sha256": _sha(before_pipeline),
        "candidate_smoke_sha256": "3" * 64,
        "incumbent_smoke_sha256": "4" * 64,
        "rollback_observed": True,
        "restore_observed": True,
        "tested_at": "2026-07-17T01:00:00Z",
    }
    _seal(rollback)
    certificate = build_interactive_promotion_certificate(
        reviewer="pytest-governance",
        private_key_path=matrix["private_key_path"],
        matrix_bundle_root=bundle,
        benchmark_certificate=benchmark,
        rollback_evidence=rollback,
        candidate_key="sam3_1",
        incumbent_key="sam2_1_large",
        candidate_artifact_key="sam3_1",
        incumbent_artifact_key="sam2_1",
        candidate_checkpoint_sha256=candidate_sha,
        incumbent_checkpoint_sha256=incumbent_sha,
        candidate_runtime_lock_sha256=runtime_sha,
        issued_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    incumbent_runtime_sha = hashlib.sha256(incumbent["runtime"].encode()).hexdigest()

    def smoke(_pipeline, _external, _models, provider_key: str, action: str):
        return {
            "result": "pass",
            "action": action,
            "role": "interactive_segmenter",
            "provider_key": provider_key,
            "checkpoint_sha256": candidate_sha if action == "promote" else incumbent_sha,
            "runtime_sha256": runtime_sha if action == "promote" else incumbent_runtime_sha,
            "output_sha256": hashlib.sha256(f"{action}-{provider_key}".encode()).hexdigest(),
        }

    return {
        "candidate_key": "sam3_1",
        "promotion_certificate": certificate,
        "matrix_bundle_root": bundle,
        "candidate_checkpoint_path": candidate_path,
        "candidate_runtime_lock_path": runtime_lock,
        "smoke_runner": smoke,
        "pipeline_path": pipeline_path,
        "external_registry_path": external_path,
        "model_registry_path": model_path,
        "history_path": project / "runs/interactive_history.jsonl",
        "snapshot_root": project / "runs/transactions",
        "project_root": project,
        "promoted_at": "2026-07-18T01:00:00Z",
    }


def test_interactive_promotion_and_rollback_restore_three_exact_files(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    paths = [
        fixture["pipeline_path"],
        fixture["external_registry_path"],
        fixture["model_registry_path"],
    ]
    before = {path: path.read_bytes() for path in paths}
    record = promote_interactive_provider(**fixture)

    assert not validate_document(record, "interactive_provider_transaction")
    assert (
        load_interactive_promotion(record["transaction_id"], history_path=fixture["history_path"])
        == record
    )
    selection = validate_provider_selection(
        yaml.safe_load(fixture["pipeline_path"].read_text(encoding="utf-8")),
        external_registry_path=fixture["external_registry_path"],
        model_registry_path=fixture["model_registry_path"],
    )
    assert selection["active"]["interactive_segmenter"] == "sam3_1"
    assert selection["rollback"]["interactive_segmenter"] == "sam2_1_large"
    assert selection["fallbacks"]["interactive_segmenter"]["oom_fallback"] == ("sam2_1_base_plus")

    rollback = rollback_interactive_provider(
        record["transaction_id"],
        smoke_runner=fixture["smoke_runner"],
        pipeline_path=fixture["pipeline_path"],
        external_registry_path=fixture["external_registry_path"],
        model_registry_path=fixture["model_registry_path"],
        history_path=fixture["history_path"],
        snapshot_root=fixture["snapshot_root"],
        rolled_back_at="2026-07-18T02:00:00Z",
    )

    assert not validate_document(rollback, "interactive_provider_rollback")
    assert all(path.read_bytes() == before[path] for path in paths)
    with pytest.raises(InteractiveProviderTransactionError, match="already rolled back"):
        load_interactive_promotion(record["transaction_id"], history_path=fixture["history_path"])


def test_interactive_promotion_rejects_failed_smoke_without_mutation(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    before = {
        key: fixture[key].read_bytes()
        for key in ("pipeline_path", "external_registry_path", "model_registry_path")
    }

    passing_smoke = fixture["smoke_runner"]

    def failed(*_args):
        value = passing_smoke(*_args)
        value["result"] = "fail"
        return value

    fixture["smoke_runner"] = failed
    with pytest.raises(InteractiveProviderTransactionError, match="serving smoke"):
        promote_interactive_provider(**fixture)
    assert all(fixture[key].read_bytes() == value for key, value in before.items())
    assert not fixture["history_path"].exists()


def test_interactive_rollback_refuses_live_or_snapshot_drift(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    record = promote_interactive_provider(**fixture)
    fixture["pipeline_path"].write_text("drift: true\n", encoding="utf-8")
    with pytest.raises(InteractiveProviderTransactionError, match="changed after promotion"):
        rollback_interactive_provider(
            record["transaction_id"],
            smoke_runner=fixture["smoke_runner"],
            pipeline_path=fixture["pipeline_path"],
            external_registry_path=fixture["external_registry_path"],
            model_registry_path=fixture["model_registry_path"],
            history_path=fixture["history_path"],
            snapshot_root=fixture["snapshot_root"],
        )


def test_concurrent_interactive_promotions_serialize_to_one_transaction(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)

    def attempt():
        try:
            return "pass", promote_interactive_provider(**fixture)["transaction_id"]
        except InteractiveProviderTransactionError as exc:
            return "fail", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), range(2)))

    assert [status for status, _detail in results].count("pass") == 1
    assert [status for status, _detail in results].count("fail") == 1
    history = fixture["history_path"].read_text(encoding="utf-8").splitlines()
    assert len(history) == 1


def test_interactive_history_failure_restores_exact_inputs(tmp_path: Path, monkeypatch) -> None:
    fixture = _transaction_fixture(tmp_path)
    before = {
        key: fixture[key].read_bytes()
        for key in ("pipeline_path", "external_registry_path", "model_registry_path")
    }

    def fail_history(*_args, **_kwargs):
        raise OSError("seeded history failure")

    monkeypatch.setattr(
        "maskfactory.providers.interactive_transaction._append_history", fail_history
    )
    with pytest.raises(InteractiveProviderTransactionError, match="exact inputs restored"):
        promote_interactive_provider(**fixture)
    assert all(fixture[key].read_bytes() == value for key, value in before.items())


def test_cli_rolls_back_interactive_transaction_by_id(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    before = {
        key: fixture[key].read_bytes()
        for key in ("pipeline_path", "external_registry_path", "model_registry_path")
    }
    record = promote_interactive_provider(**fixture)
    snapshot = fixture["snapshot_root"] / record["transaction_id"]
    smoke = fixture["smoke_runner"](
        snapshot / "before.pipeline",
        snapshot / "before.external_registry",
        snapshot / "before.model_registry",
        "sam2_1_large",
        "rollback",
    )
    evidence = tmp_path / "rollback_smoke.json"
    _write_smoke_evidence(
        evidence,
        pipeline_path=snapshot / "before.pipeline",
        external_path=snapshot / "before.external_registry",
        model_path=snapshot / "before.model_registry",
        smoke=smoke,
    )
    result = CliRunner().invoke(
        main,
        [
            "models",
            "rollback-interactive",
            record["transaction_id"],
            "--smoke-evidence",
            str(evidence),
            "--pipeline",
            str(fixture["pipeline_path"]),
            "--external-registry",
            str(fixture["external_registry_path"]),
            "--model-registry",
            str(fixture["model_registry_path"]),
            "--history",
            str(fixture["history_path"]),
            "--snapshot-root",
            str(fixture["snapshot_root"]),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["promotion_transaction_id"] == record["transaction_id"]
    assert all(fixture[key].read_bytes() == value for key, value in before.items())


def test_cli_promotes_interactive_provider_with_exact_smoke_receipt(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    pipeline = yaml.safe_load(fixture["pipeline_path"].read_text(encoding="utf-8"))
    role = pipeline["provider_roles"]["interactive_segmenter"]
    role["active"] = "sam3_1"
    role["challengers"] = [
        "sam2_1_large",
        *[key for key in role["challengers"] if key not in {"sam3_1", "sam2_1_large"}],
    ]
    role["rollback"] = "sam2_1_large"
    pipeline["stages"]["S07"]["primary_model"] = "sam3_1"
    proposed_pipeline = tmp_path / "proposed_pipeline.yaml"
    proposed_pipeline.write_bytes(
        yaml.safe_dump(pipeline, sort_keys=False, allow_unicode=True).encode("utf-8")
    )
    external = yaml.safe_load(fixture["external_registry_path"].read_text(encoding="utf-8"))
    external["providers"]["sam3_1"]["lifecycle_state"] = "promoted"
    proposed_external = tmp_path / "proposed_external.yaml"
    proposed_external.write_bytes(
        yaml.safe_dump(external, sort_keys=False, allow_unicode=True).encode("utf-8")
    )
    models = json.loads(fixture["model_registry_path"].read_text(encoding="utf-8"))
    next(row for row in models["models"] if row["key"] == "sam2_1_hiera_large")[
        "lifecycle_state"
    ] = "benchmarked"
    proposed_models = tmp_path / "proposed_models.json"
    proposed_models.write_bytes(
        (json.dumps(models, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    smoke = fixture["smoke_runner"](
        proposed_pipeline,
        proposed_external,
        proposed_models,
        "sam3_1",
        "promote",
    )
    evidence = tmp_path / "promotion_smoke.json"
    _write_smoke_evidence(
        evidence,
        pipeline_path=proposed_pipeline,
        external_path=proposed_external,
        model_path=proposed_models,
        smoke=smoke,
    )
    certificate_path = tmp_path / "interactive_certificate.json"
    certificate_path.write_text(json.dumps(fixture["promotion_certificate"]), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "models",
            "promote-interactive",
            "sam3_1",
            "--promotion-certificate",
            str(certificate_path),
            "--matrix-bundle",
            str(fixture["matrix_bundle_root"]),
            "--candidate-checkpoint",
            str(fixture["candidate_checkpoint_path"]),
            "--candidate-runtime-lock",
            str(fixture["candidate_runtime_lock_path"]),
            "--smoke-evidence",
            str(evidence),
            "--pipeline",
            str(fixture["pipeline_path"]),
            "--external-registry",
            str(fixture["external_registry_path"]),
            "--model-registry",
            str(fixture["model_registry_path"]),
            "--history",
            str(fixture["history_path"]),
            "--snapshot-root",
            str(fixture["snapshot_root"]),
            "--project-root",
            str(fixture["project_root"]),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["candidate_key"] == "sam3_1"
