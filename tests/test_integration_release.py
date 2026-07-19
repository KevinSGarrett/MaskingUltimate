"""Focused producer tests for MF-P6-12.01 integration release acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.bridge.clean_release_packaging import install_clean_release
from maskfactory.bridge.integration_release import (
    IntegrationReleaseError,
    build_inventory_from_root,
    compare_inventories,
    install_integration_pack,
    run_integration_release_acceptance,
    scan_installed_root_issues,
    validate_integration_release_evidence,
)
from maskfactory.validation import canonical_document_sha256, schema_validator


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _manifest(release_root: Path, release_id: str, publication_payload: str, wheel: Path) -> Path:
    manifest = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_clean_release_manifest",
        "release_id": release_id,
        "release_payload_sha256": "a" * 64,
        "publication_payload_sha256": publication_payload,
        "install_mode": "wheel",
        "package": {
            "relative_path": wheel.name,
            "sha256": _sha(wheel),
            "size_bytes": wheel.stat().st_size,
        },
        "activation": {
            "strategy": "atomic_pointer_switch",
            "active_pointer_path": "active_release.json",
        },
        "stale_detection": {
            "policy": "fail_on_detected",
            "expected_runtime_files": ["installed.json", "manifest.json", "wheel.whl"],
        },
        "proof_hooks": {
            "recovery_hook_id": "mf-release-recovery-proof-v1",
            "rollback_hook_id": "mf-release-rollback-proof-v1",
        },
        "source_authority": {"repository_clean": True, "allow_dirty_source": False},
        "rollback_target_release_id": "mfr_20260718_ffffffffffff",
        "manifest_sha256": "",
    }
    manifest["manifest_sha256"] = canonical_document_sha256(
        manifest, excluded_top_level_fields=("manifest_sha256",)
    )
    path = release_root / "install-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _source_tree(release_root: Path) -> dict[str, list[dict]]:
    files = {
        "nodes/__init__.py": "node-pack-v1\n",
        "nodes/loader.py": "def load():\n    return 1\n",
        "workflows/mode_a.json": '{"id":"mode_a"}\n',
        "schemas/mask.json": '{"type":"object"}\n',
        "openapi/openapi.json": '{"openapi":"3.1.0","paths":{}}\n',
        "policies/bridge.yaml": "policy_id: test\n",
    }
    for relative, text in files.items():
        _write(release_root / relative, text)
    return {
        "nodes": build_inventory_from_root(
            release_root / "nodes", relative_paths=["__init__.py", "loader.py"]
        ),
        "workflows": build_inventory_from_root(
            release_root / "workflows", relative_paths=["mode_a.json"]
        ),
        "schemas": build_inventory_from_root(
            release_root / "schemas", relative_paths=["mask.json"]
        ),
        "api_openapi": build_inventory_from_root(
            release_root / "openapi", relative_paths=["openapi.json"]
        ),
        "policies": build_inventory_from_root(
            release_root / "policies", relative_paths=["bridge.yaml"]
        ),
    }


def _prefix_inventories(
    inventories: dict[str, list[dict]], prefixes: dict[str, str]
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for name, rows in inventories.items():
        prefix = prefixes[name]
        out[name] = [
            {
                **row,
                "relative_path": f"{prefix}/{row['relative_path']}",
            }
            for row in rows
        ]
    return out


def _fixture(tmp_path: Path, *, dirty: bool = False, editable_argv: bool = False):
    release_root = tmp_path / "release"
    runtime_root = tmp_path / "runtime"
    install_target = tmp_path / "installed_pack"
    release_root.mkdir()
    runtime_root.mkdir()
    wheel = release_root / "maskfactory-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"immutable-wheel-bytes")
    local = _source_tree(release_root)
    inventories = _prefix_inventories(
        local,
        {
            "nodes": "nodes",
            "workflows": "workflows",
            "schemas": "schemas",
            "api_openapi": "openapi",
            "policies": "policies",
        },
    )
    release_id = "mfr_20260719_012345abcdef"
    publication_payload = "b" * 64
    manifest_path = _manifest(release_root, release_id, publication_payload, wheel)
    publication = {
        "decision": "published",
        "publication_payload_sha256": publication_payload,
        "repository_observation": {"clean": not dirty},
        "installation": {
            "argv": (
                ["python", "-m", "pip", "install", "-e", "."]
                if editable_argv
                else ["python", "-m", "pip", "install", wheel.name]
            )
        },
    }
    capability = {
        "status": "qualified",
        "decision_sha256": "c" * 64,
    }
    recovery = {
        "status": "producer_partial",
        "decision_sha256": "d" * 64,
    }
    # Seed a prior release so rollback has a target.
    prior = runtime_root / "releases" / "mfr_20260718_ffffffffffff"
    prior.mkdir(parents=True)
    (prior / "installed.json").write_text("{}\n", encoding="utf-8")
    return {
        "release_root": release_root,
        "runtime_root": runtime_root,
        "install_target": install_target,
        "inventories": inventories,
        "manifest_path": manifest_path,
        "publication": publication,
        "capability": capability,
        "recovery": recovery,
        "release_id": release_id,
    }


def test_schema_registry_loads_integration_release_evidence() -> None:
    assert schema_validator("maskfactory_integration_release_evidence")


def test_accepts_clean_install_with_exact_inventory_parity_and_receipt(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    evidence = run_integration_release_acceptance(
        release_id=fx["release_id"],
        release_root=fx["release_root"],
        runtime_root=fx["runtime_root"],
        install_target=fx["install_target"],
        source_inventories=fx["inventories"],
        manifest_path=fx["manifest_path"],
        publication_evidence=fx["publication"],
        publication_issues=(),
        capability_decision=fx["capability"],
        recovery_evidence=fx["recovery"],
        repository_clean=True,
        git_commit="a" * 40,
        git_tree="b" * 40,
        evidence_id="mfirel_20260719_012345abcdef",
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "accepted"
    assert evidence["inventory_parity"]["exact_match"] is True
    assert evidence["activation"]["receipt_last"] is True
    assert evidence["verification_receipt"]["receipt_sha256"]
    assert validate_integration_release_evidence(evidence) == ()
    active = json.loads((fx["runtime_root"] / "active_release.json").read_text(encoding="utf-8"))
    assert active["release_id"] == fx["release_id"]


def test_rollback_emits_evidence_and_switches_pointer(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    evidence = run_integration_release_acceptance(
        release_id=fx["release_id"],
        release_root=fx["release_root"],
        runtime_root=fx["runtime_root"],
        install_target=fx["install_target"],
        source_inventories=fx["inventories"],
        manifest_path=fx["manifest_path"],
        publication_evidence=fx["publication"],
        publication_issues=(),
        capability_decision=fx["capability"],
        recovery_evidence=fx["recovery"],
        repository_clean=True,
        git_commit="a" * 40,
        git_tree="b" * 40,
        evidence_id="mfirel_20260719_012345abcdef",
        perform_rollback=True,
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "rolled_back"
    assert evidence["rollback"]["performed"] is True
    assert evidence["rollback"]["evidence_present"] is True
    assert evidence["rollback"]["proof_sha256"]
    assert validate_integration_release_evidence(evidence) == ()
    active = json.loads((fx["runtime_root"] / "active_release.json").read_text(encoding="utf-8"))
    assert active["release_id"] == "mfr_20260718_ffffffffffff"


def test_rejects_dirty_source_authority(tmp_path: Path) -> None:
    fx = _fixture(tmp_path, dirty=True)
    evidence = run_integration_release_acceptance(
        release_id=fx["release_id"],
        release_root=fx["release_root"],
        runtime_root=fx["runtime_root"],
        install_target=fx["install_target"],
        source_inventories=fx["inventories"],
        manifest_path=fx["manifest_path"],
        publication_evidence=fx["publication"],
        publication_issues=(),
        capability_decision=fx["capability"],
        recovery_evidence=fx["recovery"],
        repository_clean=False,
        git_commit="a" * 40,
        git_tree="b" * 40,
        evidence_id="mfirel_20260719_012345abcdef",
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "rejected"
    assert "dirty_source_authority" in evidence["rejection_reasons"]


def test_rejects_editable_install_argv(tmp_path: Path) -> None:
    fx = _fixture(tmp_path, editable_argv=True)
    evidence = run_integration_release_acceptance(
        release_id=fx["release_id"],
        release_root=fx["release_root"],
        runtime_root=fx["runtime_root"],
        install_target=fx["install_target"],
        source_inventories=fx["inventories"],
        manifest_path=fx["manifest_path"],
        publication_evidence=fx["publication"],
        publication_issues=(),
        capability_decision=fx["capability"],
        recovery_evidence=fx["recovery"],
        repository_clean=True,
        git_commit="a" * 40,
        git_tree="b" * 40,
        evidence_id="mfirel_20260719_012345abcdef",
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "rejected"
    assert "editable_install_forbidden" in evidence["rejection_reasons"]


def test_rejects_missing_prerequisites(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    evidence = run_integration_release_acceptance(
        release_id=fx["release_id"],
        release_root=fx["release_root"],
        runtime_root=fx["runtime_root"],
        install_target=fx["install_target"],
        source_inventories=fx["inventories"],
        manifest_path=fx["manifest_path"],
        publication_evidence=None,
        publication_issues=None,
        capability_decision=None,
        recovery_evidence=None,
        repository_clean=True,
        git_commit="a" * 40,
        git_tree="b" * 40,
        evidence_id="mfirel_20260719_012345abcdef",
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "rejected"
    assert "prerequisite_missing" in evidence["rejection_reasons"]


def test_stale_node_rejected_on_reinstall(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    # First install succeeds.
    run_integration_release_acceptance(
        release_id=fx["release_id"],
        release_root=fx["release_root"],
        runtime_root=fx["runtime_root"],
        install_target=fx["install_target"],
        source_inventories=fx["inventories"],
        manifest_path=fx["manifest_path"],
        publication_evidence=fx["publication"],
        publication_issues=(),
        capability_decision=fx["capability"],
        recovery_evidence=fx["recovery"],
        repository_clean=True,
        git_commit="a" * 40,
        git_tree="b" * 40,
        evidence_id="mfirel_20260719_012345abcdef",
        decided_at="2026-07-19T12:00:00Z",
    )
    stale = fx["install_target"] / "nodes" / "stale_unpublished_node.py"
    stale.write_text("stale\n", encoding="utf-8")
    # Contained reinstall must wipe stale bytes (not merge-in-place).
    installed = install_integration_pack(
        source_root=fx["release_root"],
        target_root=fx["install_target"],
        inventories=fx["inventories"],
    )
    assert not stale.exists()
    assert compare_inventories(fx["inventories"]["nodes"], installed["nodes"]) == []


def test_openapi_and_schema_drift_rejected(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    drifted = dict(fx["inventories"])
    drifted["api_openapi"] = [
        {
            **fx["inventories"]["api_openapi"][0],
            "sha256": "f" * 64,
        }
    ]
    with pytest.raises(IntegrationReleaseError, match="source hash drift"):
        install_integration_pack(
            source_root=fx["release_root"],
            target_root=fx["install_target"],
            inventories=drifted,
        )
    mismatches = compare_inventories(
        fx["inventories"]["schemas"],
        [
            {
                **fx["inventories"]["schemas"][0],
                "sha256": "e" * 64,
            }
        ],
    )
    assert any(row["code"] == "changed_hash" for row in mismatches)


def test_scan_detects_extra_stale_node(tmp_path: Path) -> None:
    root = tmp_path / "pack"
    _write(root / "nodes" / "ok.py", "ok\n")
    expected = build_inventory_from_root(root, relative_paths=["nodes/ok.py"])
    _write(root / "nodes" / "stale_unpublished_node.py", "bad\n")
    codes = scan_installed_root_issues(root, expected)
    assert "extra_file" in codes
    assert "stale_node_detected" in codes


def test_clean_packaging_stale_runtime_still_rejected(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    stale_dir = fx["runtime_root"] / "releases" / fx["release_id"]
    stale_dir.mkdir(parents=True)
    (stale_dir / "orphan.txt").write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError, match="stale runtime files detected"):
        install_clean_release(
            manifest_path=fx["manifest_path"],
            release_root=fx["release_root"],
            runtime_root=fx["runtime_root"],
        )
