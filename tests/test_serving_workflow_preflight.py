from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.serve import workflow_preflight
from maskfactory.serve.workflow_performance import (
    DEFAULT_POLICY,
    ROLLBACK_ROLES,
    canonical_sha256,
    file_sha256,
    load_policy,
)
from maskfactory.serve.workflow_preflight import (
    AUTHORITY,
    WorkflowPreflightError,
    package_tree_sha256,
    preflight_workflow_execution,
)
from maskfactory.validation import validate_document


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _certificate(path: Path, role: str) -> dict:
    document = {
        "schema_version": "1.0.0",
        "target_role": role,
        "primary_win_or_labor_reduction": True,
        "hard_bucket_results": [{"bucket": "preflight_fixture", "passed": True}],
        "frozen_eval_sha256": "e" * 64,
        "issued_at": "2026-07-15T18:00:00Z",
    }
    document["sha256"] = canonical_sha256(document)
    _write(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path.resolve()
    packages_root = root / "data" / "packages"
    policy = load_policy(DEFAULT_POLICY)
    sources: list[dict] = []
    for scope, source_id, people, color, tier in (
        ("single_person", "single", 1, (210, 20, 30), "human_anchor_gold"),
        ("multi_person", "multi", 3, (20, 30, 210), "autonomous_certified_gold"),
    ):
        image = root / "sources" / f"{source_id}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 24), color).save(image)
        governance = _write(
            root / "governance" / f"{source_id}.json",
            json.dumps(
                {
                    "source_id": source_id,
                    "scope": scope,
                    "people": people,
                    "rights": "owned_fixture",
                    "content_lane": "adult_explicit_governed_fixture",
                },
                sort_keys=True,
            ),
        )
        package_root = packages_root / f"image_{source_id}" / "instances" / "p0"
        manifest = _write(
            package_root / "manifest.json",
            json.dumps({"image_id": f"image_{source_id}", "truth_tier": tier}, sort_keys=True),
        )
        _write(package_root / "masks" / "person.png", b"strict-mask-fixture")
        sources.append(
            {
                "source_id": source_id,
                "scope": scope,
                "image_id": f"image_{source_id}",
                "image_path": str(image),
                "image_sha256": file_sha256(image),
                "governance_decision_path": str(governance),
                "governance_decision_sha256": file_sha256(governance),
                "person_count": people,
                "unseen_before_measurement": True,
                "image_disjoint": True,
                "package_manifest_path": str(manifest),
                "package_manifest_sha256": file_sha256(manifest),
                "package_tree_sha256": package_tree_sha256(package_root),
                "truth_tier": tier,
            }
        )

    models = []
    bindings: list[dict] = []
    provider_catalog = {}
    active_selection = {}
    rollback_selection = {}
    for index, role in enumerate(ROLLBACK_ROLES):
        active_key = f"active_{role}"
        rollback_key = f"rollback_{role}"
        active_checkpoint = _write(
            root / "models" / f"{active_key}.ckpt", f"active:{role}".encode()
        )
        runtime = _write(root / "env" / f"{active_key}.lock.json", f'{{"role":"{role}"}}')
        rollback_checkpoint = _write(
            root / "models" / f"{rollback_key}.ckpt", f"rollback:{role}".encode()
        )
        certificate_path = root / "certificates" / f"{role}.json"
        certificate = _certificate(certificate_path, role)
        active_role = role if role != "interactive_segmenter" else "interactive_incumbent"
        models.extend(
            [
                {
                    "key": active_key,
                    "role": active_role,
                    "lifecycle_state": "promoted",
                    "sha256": file_sha256(active_checkpoint),
                    "artifact_hashes": {"runtime": file_sha256(runtime)},
                    "benchmark_certificate": certificate,
                },
                {
                    "key": rollback_key,
                    "role": f"rollback_fixture_{index}",
                    "lifecycle_state": "benchmarked",
                    "sha256": file_sha256(rollback_checkpoint),
                },
            ]
        )
        if role == "interactive_segmenter":
            provider_catalog[active_key] = {
                "registry": "model_registry",
                "key": active_key,
            }
            provider_catalog[rollback_key] = {
                "registry": "model_registry",
                "key": rollback_key,
            }
            active_selection[role] = active_key
            rollback_selection[role] = rollback_key
        bindings.append(
            {
                "role": role,
                "active_provider": active_key,
                "rollback_provider": rollback_key,
                "active_lifecycle_state": "promoted",
                "rollback_lifecycle_state": "benchmarked",
                "active_checkpoint_path": str(active_checkpoint),
                "active_checkpoint_sha256": file_sha256(active_checkpoint),
                "active_runtime_path": str(runtime),
                "active_runtime_sha256": file_sha256(runtime),
                "benchmark_certificate_path": str(certificate_path),
                "benchmark_certificate_file_sha256": file_sha256(certificate_path),
                "benchmark_certificate_sha256": certificate["sha256"],
                "rollback_checkpoint_path": str(rollback_checkpoint),
                "rollback_checkpoint_sha256": file_sha256(rollback_checkpoint),
                "rollback_command": f"maskfactory models rollback-fixture {index}",
            }
        )

    registry_path = _write(
        root / "control" / "model_registry.json",
        json.dumps({"models": models}, indent=2, sort_keys=True) + "\n",
    )
    pipeline_path = _write(
        root / "control" / "pipeline.yaml",
        yaml.safe_dump({"provider_catalog": provider_catalog}, sort_keys=True),
    )
    external_path = _write(
        root / "control" / "external_sources.yaml",
        yaml.safe_dump({"providers": {}}, sort_keys=True),
    )
    selection = {"active": active_selection, "rollback": rollback_selection}
    monkeypatch.setattr(
        workflow_preflight,
        "validate_provider_selection",
        lambda *_args, **_kwargs: copy.deepcopy(selection),
    )
    document = {
        "schema_version": "1.0.0",
        "policy_id": "serving_workflow_performance_v1",
        "policy_sha256": policy["sha256"],
        "prepared_at": "2026-07-15T18:00:00Z",
        "api_url": "http://127.0.0.1:8765",
        "output_root": str(root / "runs" / "serving_workflow_fixture"),
        "sources": sources,
        "role_bindings": bindings,
        "authority": AUTHORITY,
    }
    document["sha256"] = canonical_sha256(document)
    return {
        "root": root,
        "packages_root": packages_root,
        "registry": registry_path,
        "pipeline": pipeline_path,
        "external": external_path,
        "document": document,
    }


def _run(document: dict, fixture: dict) -> dict:
    return preflight_workflow_execution(
        document,
        artifact_root=fixture["root"],
        registry_path=fixture["registry"],
        pipeline_path=fixture["pipeline"],
        external_registry_path=fixture["external"],
        packages_root=fixture["packages_root"],
        checked_at=datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
    )


def _reseal(document: dict) -> dict:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def test_complete_preflight_binds_files_governance_packages_roles_and_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    document = fixture["document"]
    assert not validate_document(document, "serving_workflow_execution_input")
    report = _run(document, fixture)
    assert report["ready"] is True
    assert report["findings"] == []
    assert not validate_document(report, "serving_workflow_preflight_report")
    assert report["coverage"]["rollback_roles"] == list(ROLLBACK_ROLES)
    assert report["authority"] == AUTHORITY
    assert report["sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "sha256"}
    )


def test_input_schema_seal_and_loopback_boundary_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    malformed = copy.deepcopy(fixture["document"])
    malformed["sources"].pop()
    with pytest.raises(WorkflowPreflightError, match="minItems"):
        _run(_reseal(malformed), fixture)

    tampered = copy.deepcopy(fixture["document"])
    tampered["output_root"] += "_tampered"
    with pytest.raises(WorkflowPreflightError, match="seal mismatch"):
        _run(tampered, fixture)

    remote = copy.deepcopy(fixture["document"])
    remote["api_url"] = "https://example.com/inference?token=secret"
    with pytest.raises(WorkflowPreflightError, match="loopback HTTP"):
        _run(_reseal(remote), fixture)


def test_package_and_active_artifact_drift_are_reported_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    document = fixture["document"]
    first_package = Path(document["sources"][0]["package_manifest_path"]).parent
    _write(first_package / "unexpected.bin", b"post-seal-drift")
    Path(document["role_bindings"][0]["active_runtime_path"]).write_text(
        "runtime drift", encoding="utf-8"
    )
    report = _run(document, fixture)
    assert report["ready"] is False
    assert {row["code"] for row in report["findings"]} >= {
        "package_tree_hash_mismatch",
        "artifact_hash_mismatch",
    }


def test_truth_output_governance_and_provider_identity_guards_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    document = copy.deepcopy(fixture["document"])
    document["output_root"] = str(
        Path(document["sources"][0]["package_manifest_path"]).parent / "workflow_output"
    )
    document["role_bindings"][0]["rollback_provider"] = document["role_bindings"][0][
        "active_provider"
    ]
    governance_path = Path(document["sources"][0]["governance_decision_path"])
    governance = json.loads(governance_path.read_text(encoding="utf-8"))
    governance["people"] = 4
    governance_path.write_text(json.dumps(governance), encoding="utf-8")
    document["sources"][0]["governance_decision_sha256"] = file_sha256(governance_path)
    _reseal(document)
    report = _run(document, fixture)
    codes = {row["code"] for row in report["findings"]}
    assert report["ready"] is False
    assert {
        "output_inside_truth_root",
        "output_inside_package",
        "rollback_provider_not_distinct",
        "governance_source_mismatch",
    } <= codes


def test_wrong_source_and_role_order_return_schema_valid_not_ready_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    document = copy.deepcopy(fixture["document"])
    document["sources"].reverse()
    document["role_bindings"].reverse()
    report = _run(_reseal(document), fixture)
    assert report["ready"] is False
    assert not validate_document(report, "serving_workflow_preflight_report")
    assert {row["code"] for row in report["findings"]} >= {
        "source_scope_order_invalid",
        "role_binding_order_invalid",
    }


def test_unreadable_control_plane_returns_a_sealed_not_ready_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    missing = tmp_path / "missing-registry.json"
    fixture["registry"] = missing
    report = _run(fixture["document"], fixture)
    assert report["ready"] is False
    assert report["control_plane"]["registry_sha256"] is None
    assert {row["code"] for row in report["findings"]} >= {
        "control_plane_unreadable",
        "control_plane_artifact_unreadable",
    }


def test_cli_writes_exclusive_preflight_evidence_and_exits_nonzero_when_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    input_path = _write(
        tmp_path / "execution_input.json",
        json.dumps(fixture["document"], indent=2, sort_keys=True) + "\n",
    )
    output_path = tmp_path / "preflight_report.json"
    args = [
        "preflight-serving-workflows",
        str(input_path),
        "--artifact-root",
        str(fixture["root"]),
        "--registry",
        str(fixture["registry"]),
        "--pipeline",
        str(fixture["pipeline"]),
        "--external-registry",
        str(fixture["external"]),
        "--packages-root",
        str(fixture["packages_root"]),
        "--output",
        str(output_path),
    ]
    runner = CliRunner()
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(output_path.read_text(encoding="utf-8"))["ready"] is True
    assert runner.invoke(main, args).exit_code != 0

    blocked = copy.deepcopy(fixture["document"])
    blocked["role_bindings"][0]["rollback_provider"] = blocked["role_bindings"][0][
        "active_provider"
    ]
    blocked_path = _write(
        tmp_path / "blocked_input.json",
        json.dumps(_reseal(blocked), indent=2, sort_keys=True) + "\n",
    )
    blocked_result = runner.invoke(main, [*args[:1], str(blocked_path), *args[2:-2]])
    assert blocked_result.exit_code == 1
    assert json.loads(blocked_result.output)["ready"] is False
