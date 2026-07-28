from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from maskfactory.bridge.clean_release_packaging import (
    install_clean_release,
    rollback_clean_release,
    validate_clean_release_manifest,
    validate_wheel_runtime_closure,
)
from maskfactory.validation import canonical_document_sha256


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wheel_with_closure(
    tmp_path: Path,
    *,
    requires: tuple[str, ...] = ("click", "pydantic"),
    record_override: str | None = None,
    entrypoints: str = "[console_scripts]\nmaskfactory = maskfactory.cli:main\n",
) -> Path:
    wheel_path = tmp_path / "maskfactory-1.0.0-py3-none-any.whl"
    members = {
        "maskfactory/__init__.py": b"__version__ = '1.0.0'\n",
        "maskfactory/cli.py": b"def main():\n    return None\n",
        "maskfactory-1.0.0.dist-info/METADATA": (
            "Metadata-Version: 2.4\nName: maskfactory\nVersion: 1.0.0\n"
            + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)
        ).encode("utf-8"),
        "maskfactory-1.0.0.dist-info/entry_points.txt": entrypoints.encode("utf-8"),
    }
    record_rows = []
    for name, content in members.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
        )
        record_rows.append(f"{name},sha256={digest},{len(content)}")
    record_rows.append("maskfactory-1.0.0.dist-info/RECORD,,")
    if record_override is not None:
        record_rows[0] = record_override
    members["maskfactory-1.0.0.dist-info/RECORD"] = ("\n".join(record_rows) + "\n").encode("utf-8")
    with zipfile.ZipFile(wheel_path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return wheel_path


def _setup(tmp_path: Path) -> tuple[Path, Path, dict, dict[str, dict[str, object]], Path]:
    release_root = tmp_path / "release"
    runtime_root = tmp_path / "runtime"
    release_root.mkdir()
    runtime_root.mkdir()
    wheel = _wheel_with_closure(release_root)
    release = {
        "release_id": "mfr_20260719_012345abcdef",
        "release_payload_sha256": "a" * 64,
    }
    evidence = {
        "release_binding": release,
        "publication_payload_sha256": "b" * 64,
        "runtime_provenance": {
            "kind": "native_venv",
            "installed_distribution": {
                "relative_path": wheel.name,
                "sha256": _sha(wheel),
                "size_bytes": wheel.stat().st_size,
            },
        },
        "installation": {"argv": ["python", "-m", "pip", "install", wheel.name]},
        "rollback": {"argv": ["python", "rollback_maskfactory_release.py"]},
    }
    manifest = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_clean_release_manifest",
        "release_id": release["release_id"],
        "release_payload_sha256": release["release_payload_sha256"],
        "publication_payload_sha256": evidence["publication_payload_sha256"],
        "install_mode": "wheel",
        "package": {
            "relative_path": wheel.name,
            "sha256": _sha(wheel),
            "size_bytes": wheel.stat().st_size,
        },
        "runtime_closure": {
            "console_entrypoint": "maskfactory.cli:main",
            "requires_dist": ["click", "pydantic"],
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
    manifest_path = release_root / "install-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    catalog = {
        wheel.name: {
            "relative_path": wheel.name,
            "sha256": _sha(wheel),
            "size_bytes": wheel.stat().st_size,
        },
        manifest_path.name: {
            "relative_path": manifest_path.name,
            "sha256": _sha(manifest_path),
            "size_bytes": manifest_path.stat().st_size,
        },
    }
    evidence["installation"]["manifest"] = catalog[manifest_path.name]
    return release_root, runtime_root, evidence, catalog, manifest_path


def test_validate_clean_release_manifest_accepts_closed_manifest(tmp_path: Path) -> None:
    release_root, _, evidence, catalog, _ = _setup(tmp_path)
    assert validate_clean_release_manifest(evidence, catalog, release_root=release_root) == ()


def test_validate_clean_release_manifest_rejects_editable_install(tmp_path: Path) -> None:
    release_root, _, evidence, catalog, _ = _setup(tmp_path)
    evidence["installation"]["argv"] = ["python", "-m", "pip", "install", "-e", "."]
    codes = {
        code
        for _, code, _ in validate_clean_release_manifest(
            evidence, catalog, release_root=release_root
        )
    }
    assert "editable_install_forbidden" in codes


def test_validate_wheel_runtime_closure_accepts_exact_artifact_contract(tmp_path: Path) -> None:
    wheel_path = _wheel_with_closure(tmp_path)

    assert (
        validate_wheel_runtime_closure(
            wheel_path,
            expected_entrypoint="maskfactory.cli:main",
            expected_requires=("click", "pydantic"),
        )
        == ()
    )


def test_validate_wheel_runtime_closure_rejects_tampered_record(tmp_path: Path) -> None:
    wheel_path = _wheel_with_closure(
        tmp_path,
        record_override="maskfactory/__init__.py,sha256=invalid,1",
    )

    codes = {
        code
        for _, code, _ in validate_wheel_runtime_closure(
            wheel_path,
            expected_entrypoint="maskfactory.cli:main",
            expected_requires=("click", "pydantic"),
        )
    }
    assert "record_hash" in codes
    assert "record_size" in codes


def test_validate_wheel_runtime_closure_rejects_competing_console_script(
    tmp_path: Path,
) -> None:
    wheel_path = _wheel_with_closure(
        tmp_path,
        entrypoints=(
            "[console_scripts]\n"
            "maskfactory = maskfactory.cli:main\n"
            "maskfactory = attacker.module:main\n"
        ),
    )

    codes = {
        code
        for _, code, _ in validate_wheel_runtime_closure(
            wheel_path,
            expected_entrypoint="maskfactory.cli:main",
            expected_requires=("click", "pydantic"),
        )
    }
    assert "entrypoint_drift" in codes


def test_install_and_rollback_emit_proof_and_switch_atomically(tmp_path: Path) -> None:
    release_root, runtime_root, _, _, manifest_path = _setup(tmp_path)
    install_proof = install_clean_release(
        manifest_path=manifest_path,
        release_root=release_root,
        runtime_root=runtime_root,
        proof_out=runtime_root / "install-proof.json",
    )
    active = json.loads((runtime_root / "active_release.json").read_text(encoding="utf-8"))
    assert active["release_id"] == "mfr_20260719_012345abcdef"
    assert install_proof["action"] == "install"
    previous_release = runtime_root / "releases" / "mfr_20260718_ffffffffffff"
    previous_release.mkdir(parents=True, exist_ok=True)
    (previous_release / "installed.json").write_text("{}", encoding="utf-8")
    rollback_proof = rollback_clean_release(
        manifest_path=manifest_path,
        runtime_root=runtime_root,
        target_release_id="mfr_20260718_ffffffffffff",
        proof_out=runtime_root / "rollback-proof.json",
    )
    rolled = json.loads((runtime_root / "active_release.json").read_text(encoding="utf-8"))
    assert rolled["release_id"] == "mfr_20260718_ffffffffffff"
    assert rollback_proof["action"] == "rollback"


def test_install_fails_on_stale_runtime_files(tmp_path: Path) -> None:
    release_root, runtime_root, _, _, manifest_path = _setup(tmp_path)
    stale_dir = runtime_root / "releases" / "mfr_20260719_012345abcdef"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "orphan.txt").write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError, match="stale runtime files detected"):
        install_clean_release(
            manifest_path=manifest_path,
            release_root=release_root,
            runtime_root=runtime_root,
        )
