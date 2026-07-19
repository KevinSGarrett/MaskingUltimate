"""Build additive clean-release install manifest from publication evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from maskfactory.validation import canonical_document_sha256, load_canonical_json


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-evidence", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--wheel-relative-path", required=True)
    parser.add_argument("--rollback-target-release-id", required=False)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = load_canonical_json(args.publication_evidence.read_bytes())
    if not isinstance(evidence, dict):
        raise ValueError("publication evidence must be a JSON object")
    release = evidence["release_binding"]
    wheel_path = (args.release_root / args.wheel_relative_path).resolve(strict=True)
    package = {
        "relative_path": args.wheel_relative_path.replace("\\", "/"),
        "sha256": _sha(wheel_path),
        "size_bytes": wheel_path.stat().st_size,
    }
    manifest = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_clean_release_manifest",
        "release_id": release["release_id"],
        "release_payload_sha256": release["release_payload_sha256"],
        "publication_payload_sha256": evidence["publication_payload_sha256"],
        "install_mode": "wheel",
        "package": package,
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
        "rollback_target_release_id": args.rollback_target_release_id,
        "manifest_sha256": "",
    }
    manifest["manifest_sha256"] = canonical_document_sha256(
        manifest, excluded_top_level_fields=("manifest_sha256",)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
