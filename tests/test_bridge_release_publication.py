from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.crosswalk import load_crosswalk_definition
from maskfactory.bridge.release_publication import validate_release_publication
from maskfactory.validation import canonical_document_sha256


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _binding(root: Path, name: str) -> dict[str, object]:
    path = root / name
    return {"relative_path": name, "sha256": _sha(path), "size_bytes": path.stat().st_size}


def _publication(tmp_path: Path) -> tuple[dict, Path, Path, dict]:
    repository = tmp_path / "repository"
    release_root = tmp_path / "release"
    repository.mkdir()
    release_root.mkdir()
    _run(repository, "init")
    _run(repository, "config", "user.email", "test@example.invalid")
    _run(repository, "config", "user.name", "MaskFactory test")
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _run(repository, "add", "tracked.txt")
    _run(repository, "commit", "-m", "test")
    _run(repository, "remote", "add", "origin", "https://example.invalid/maskfactory.git")
    commit = _run(repository, "rev-parse", "HEAD")
    tree = _run(repository, "rev-parse", "HEAD^{tree}")

    names = (
        "crosswalk.json",
        "environment.lock",
        "maskfactory-1.0.0-py3-none-any.whl",
        "installer.py",
        "verify.py",
        "rollback.py",
        "rollback-evidence.json",
        "keys.json",
        "rotation.json",
        "revocations.json",
        "journal.json",
    )
    adopted_crosswalk = load_crosswalk_definition()
    for name in names:
        if name == "crosswalk.json":
            governance = Path("qa/governance/bridge/maskfactory_main_crosswalk_v1.json")
            (release_root / name).write_bytes(governance.read_bytes())
        else:
            (release_root / name).write_text(f"{name}\n", encoding="utf-8")
    snapshot = {
        "release_id": "mfr_20260719_012345abcdef",
        "release_payload_sha256": "a" * 64,
        "producer": {
            "repository_id": "https://example.invalid/maskfactory.git",
            "git_commit": commit,
            "git_tree": tree,
            "dirty": False,
        },
    }
    (release_root / "release.json").write_text(json.dumps(snapshot), encoding="utf-8")
    rows = [_binding(release_root, name) for name in (*names, "release.json")]
    bindings = {row["relative_path"]: row for row in rows}
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_release_publication_evidence",
        "publication_id": "mfrpub_20260719_012345abcdef",
        "decision": "published",
        "published_at": "2026-07-19T12:00:00Z",
        "release_binding": {
            "release_id": snapshot["release_id"],
            "release_payload_sha256": snapshot["release_payload_sha256"],
            "relative_path": "release.json",
            "document_sha256": _sha(release_root / "release.json"),
        },
        "crosswalk_binding": {
            "crosswalk_id": adopted_crosswalk["crosswalk_id"],
            "relative_path": "crosswalk.json",
            "sha256": bindings["crosswalk.json"]["sha256"],
        },
        "repository_observation": {
            "repository_id": "https://example.invalid/maskfactory.git",
            "git_commit": commit,
            "git_tree": tree,
            "clean": True,
        },
        "runtime_provenance": {
            "kind": "native_venv",
            "python_executable_sha256": "b" * 64,
            "python_version": "3.11.0",
            "platform": "test",
            "environment_lock": bindings["environment.lock"],
            "installed_distribution": bindings["maskfactory-1.0.0-py3-none-any.whl"],
            "cuda": "none",
            "driver": "none",
            "gpu": "none",
        },
        "catalog": rows,
        "installation": {
            "installer": bindings["installer.py"],
            "manifest": {"relative_path": "install-manifest.json", "sha256": "", "size_bytes": 0},
            "verification_workflow": bindings["verify.py"],
            "argv": [
                "python",
                "-m",
                "pip",
                "install",
                "maskfactory-1.0.0-py3-none-any.whl",
            ],
        },
        "rollback": {
            "target_release_id": None,
            "command": bindings["rollback.py"],
            "verification_evidence": bindings["rollback-evidence.json"],
            "argv": ["python", "rollback.py", "--target", "mfr_20260718_ffffffffffff"],
        },
        "trust_checkpoint": {
            "key_registry": bindings["keys.json"],
            "rotation_policy": bindings["rotation.json"],
            "revocation_state": bindings["revocations.json"],
            "journal_checkpoint": bindings["journal.json"],
        },
    }
    evidence["publication_payload_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("publication_payload_sha256", "signature")
    )
    install_manifest = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_clean_release_manifest",
        "release_id": snapshot["release_id"],
        "release_payload_sha256": snapshot["release_payload_sha256"],
        "publication_payload_sha256": evidence["publication_payload_sha256"],
        "install_mode": "wheel",
        "package": {
            "relative_path": "maskfactory-1.0.0-py3-none-any.whl",
            "sha256": bindings["maskfactory-1.0.0-py3-none-any.whl"]["sha256"],
            "size_bytes": bindings["maskfactory-1.0.0-py3-none-any.whl"]["size_bytes"],
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
        "rollback_target_release_id": None,
        "manifest_sha256": "",
    }
    install_manifest["manifest_sha256"] = canonical_document_sha256(
        install_manifest, excluded_top_level_fields=("manifest_sha256",)
    )
    manifest_path = release_root / "install-manifest.json"
    manifest_path.write_text(json.dumps(install_manifest), encoding="utf-8")
    manifest_binding = _binding(release_root, "install-manifest.json")
    evidence["installation"]["manifest"] = manifest_binding
    evidence["catalog"].append(manifest_binding)

    evidence["publication_payload_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("publication_payload_sha256", "signature")
    )
    evidence["signature"] = {
        "algorithm": "ed25519",
        "key_id": "mf-release-test",
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
        "signed_payload_sha256": evidence["publication_payload_sha256"],
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": base64.b64encode(
            private_key.sign(bytes.fromhex(evidence["publication_payload_sha256"]))
        ).decode("ascii"),
    }
    trusted = {
        "mf-release-test": {
            "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
            "roles": ["producer_release"],
            "status": "active",
            "usage_scope": "production",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    }
    return evidence, release_root, repository, trusted


def test_observed_publication_is_byte_closed_and_valid(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    assert not validate_release_publication(
        evidence,
        release_root=release_root,
        repository_root=repository,
        trusted_signing_keys=trusted,
    )


def test_dirty_git_denies_even_when_claimed_clean(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    (repository / "untracked.txt").write_text("not clean\n", encoding="utf-8")
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert "git_drift" in codes


def test_substituted_git_identity_and_unmanifested_file_deny(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    evidence["repository_observation"]["git_commit"] = "f" * 40
    (release_root / "unexpected.txt").write_text("not cataloged\n", encoding="utf-8")
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert {"git_drift", "catalog_closure"} <= codes


def test_missing_cataloged_bytes_or_revoked_key_denies(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    (release_root / "keys.json").write_text("substituted\n", encoding="utf-8")
    trusted["mf-release-test"]["status"] = "revoked"
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert {"catalog_bytes", "signer_authority"} <= codes


def test_both_runtime_branches_are_schema_rejected(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    evidence["runtime_provenance"]["image_digest"] = "sha256:" + "c" * 64
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert "schema" in codes


def test_editable_install_and_dirty_source_authority_are_rejected(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    evidence["installation"]["argv"] = ["python", "-m", "pip", "install", "-e", "."]
    snapshot = json.loads((release_root / evidence["release_binding"]["relative_path"]).read_text())
    snapshot["producer"]["dirty"] = True
    (release_root / evidence["release_binding"]["relative_path"]).write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert {"editable_install_forbidden", "dirty_source_publication_authority"} <= codes


def test_substituted_key_duplicate_catalog_and_canonical_hash_deny(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    evidence["signature"]["public_key_base64"] = base64.b64encode(b"\x01" * 32).decode("ascii")
    # Keep object inequality so schema uniqueItems does not short-circuit before path checks.
    duplicate = dict(evidence["catalog"][0])
    duplicate["size_bytes"] = int(duplicate["size_bytes"]) + 1
    evidence["catalog"].append(duplicate)
    evidence["publication_payload_sha256"] = "0" * 64
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert {"key_substitution", "duplicate_catalog_path", "canonical_hash"} <= codes


def test_substituted_crosswalk_identity_denies_publication(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    evidence["crosswalk_binding"]["crosswalk_id"] = "not-the-adopted-crosswalk"
    (release_root / "crosswalk.json").write_text('{"crosswalk_id":"forged"}\n', encoding="utf-8")
    for row in evidence["catalog"]:
        if row["relative_path"] == "crosswalk.json":
            row["sha256"] = _sha(release_root / "crosswalk.json")
            row["size_bytes"] = (release_root / "crosswalk.json").stat().st_size
    evidence["crosswalk_binding"]["sha256"] = _sha(release_root / "crosswalk.json")
    evidence["publication_payload_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("publication_payload_sha256", "signature")
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    evidence["signature"] = {
        "algorithm": "ed25519",
        "key_id": "mf-release-test",
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
        "signed_payload_sha256": evidence["publication_payload_sha256"],
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": base64.b64encode(
            private_key.sign(bytes.fromhex(evidence["publication_payload_sha256"]))
        ).decode("ascii"),
    }
    trusted["mf-release-test"] = {
        "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
        "roles": ["producer_release"],
        "status": "active",
        "usage_scope": "production",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert "crosswalk_adoption" in codes


def test_fixture_authority_and_incompatible_schema_version_deny(tmp_path: Path) -> None:
    evidence, release_root, repository, trusted = _publication(tmp_path)
    snapshot = json.loads((release_root / evidence["release_binding"]["relative_path"]).read_text())
    snapshot["fixture_only"] = True
    snapshot["release_status"] = "fixture"
    snapshot["schema_version"] = "2.0.0"
    (release_root / evidence["release_binding"]["relative_path"]).write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    # Catalog bytes change with the rewritten release document.
    release_binding = evidence["release_binding"]
    release_path = release_root / release_binding["relative_path"]
    release_binding["document_sha256"] = _sha(release_path)
    for row in evidence["catalog"]:
        if row["relative_path"] == release_binding["relative_path"]:
            row["sha256"] = release_binding["document_sha256"]
            row["size_bytes"] = release_path.stat().st_size
    evidence["publication_payload_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("publication_payload_sha256", "signature")
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    evidence["signature"] = {
        "algorithm": "ed25519",
        "key_id": "mf-release-test",
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
        "signed_payload_sha256": evidence["publication_payload_sha256"],
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": base64.b64encode(
            private_key.sign(bytes.fromhex(evidence["publication_payload_sha256"]))
        ).decode("ascii"),
    }
    trusted["mf-release-test"] = {
        "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
        "roles": ["producer_release"],
        "status": "active",
        "usage_scope": "production",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    codes = {
        issue.code
        for issue in validate_release_publication(
            evidence,
            release_root=release_root,
            repository_root=repository,
            trusted_signing_keys=trusted,
        )
    }
    assert {"fixture_authority", "incompatible_release_schema_version"} <= codes
