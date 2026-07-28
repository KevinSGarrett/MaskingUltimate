from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "models" / "bv"
REPORT = ROOT / "qa" / "live_verification" / "birefnet_variant_install_20260714.json"
ALLOW_PATTERNS = (
    "BiRefNet_config.py",
    "README.md",
    "birefnet.py",
    "config.json",
    "handler.py",
    "model.safetensors",
    "requirements.txt",
)
VARIANTS = {
    "birefnet_dynamic": {
        "directory": "dyn",
        "repo": "ZhengPeng7/BiRefNet_dynamic",
        "revision": "280306042f57b7a33854319da62fd86aaa89ec4c",
        "checkpoint_sha256": "e3d2e4884e51ff30f0cd630edc6b1e41b06b7f23a0a2a5169f7b7cb33a711c2d",
        "checkpoint_bytes": 444473596,
    },
    "birefnet_hr": {
        "directory": "hr",
        "repo": "ZhengPeng7/BiRefNet_HR",
        "revision": "a7a562f6fd16021180f2f4348f4de003a2d3d1e1",
        "checkpoint_sha256": "9d678bafec0b0019fbb073b7fd02f05ede25dc4b15254f23b2fb0be333200c0d",
        "checkpoint_bytes": 444473596,
    },
    "birefnet_hr_matting": {
        "directory": "hrm",
        "repo": "ZhengPeng7/BiRefNet_HR-matting",
        "revision": "5d6b6f8adcb5b417c871b1d84ceaae9871355b7f",
        "checkpoint_sha256": "a5a4de698739ea5e0e8bbab28e1b293dde95092b87a442d566cbc585c53cef55",
        "checkpoint_bytes": 444473596,
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    records = {}
    for key, expected in VARIANTS.items():
        destination = TARGET / str(expected["directory"])
        snapshot_download(
            repo_id=str(expected["repo"]),
            revision=str(expected["revision"]),
            local_dir=destination,
            allow_patterns=list(ALLOW_PATTERNS),
        )
        checkpoint = destination / "model.safetensors"
        checkpoint_sha256 = _sha256(checkpoint)
        if checkpoint.stat().st_size != expected["checkpoint_bytes"]:
            raise RuntimeError(f"{key} checkpoint size mismatch")
        if checkpoint_sha256 != expected["checkpoint_sha256"]:
            raise RuntimeError(f"{key} checkpoint SHA-256 mismatch")
        files = {
            path.relative_to(destination).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(destination.iterdir())
            if path.is_file() and path.name != ".gitattributes"
        }
        if set(ALLOW_PATTERNS) - set(files):
            raise RuntimeError(f"{key} snapshot is missing required source files")
        records[key] = {
            **expected,
            "local_path": destination.relative_to(ROOT).as_posix(),
            "files": files,
        }
    document = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "source": "official Hugging Face repositories at immutable revisions",
        "variants": records,
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
