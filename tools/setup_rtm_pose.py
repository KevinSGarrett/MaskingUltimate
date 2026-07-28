from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe")
DEPS = ROOT / "models" / "runtime_cache" / "rtm_pose_deps"
OUTPUT = ROOT / "qa" / "live_verification" / "rtm_pose_install_20260714.json"
SOURCES = {
    "mmpose": {
        "url": "https://github.com/open-mmlab/mmpose.git",
        "path": ROOT / "models/runtime_cache/mmpose_v1.3.2",
        "commit": "5408bc76f5b848cf925a0d1857899011d8c5b497",
        "tree": "592d7336c9dd65a3f19f96c8bbcf0956bcf97426",
        "license_sha256": "d125421b289cd79bf03e8590858fa81c22dc95e2753b20bf80e6a3cc80a893f9",
    },
    "rtmlib": {
        "url": "https://github.com/Tau-J/rtmlib.git",
        "path": ROOT / "models/runtime_cache/rtmlib_0.0.15",
        "commit": "f1bac7d80c88305534dbcdde12da39f6db4c3953",
        "tree": "aa0ac704492788c82c37bc323ba98fff45edbf26",
        "license_sha256": "fe6aadc681443c2cb0a95f7f2f2dbf6e624dfaeba1932e710b6933340a1e1e7e",
    },
}
CHECKPOINTS = {
    "rtmw_x": {
        "url": "https://download.openmmlab.com/mmpose/v1/projects/rtmw/rtmw-x_simcc-cocktail14_pt-ucoco_270e-384x288-f840f204_20231122.pth",
        "path": ROOT
        / "models/pose/rtm/rtmw-x_simcc-cocktail14_pt-ucoco_270e-384x288-f840f204_20231122.pth",
        "sha256": "f840f2044fe46cb3821b7cea86be83e1f6cba406ccd28f5475ac010412dcda95",
        "bytes": 369720404,
    },
    "rtmo_crowd": {
        "url": "https://download.openmmlab.com/mmpose/v1/projects/rtmo/rtmo-l_16xb16-700e_body7-crowdpose-640x640-5bafdc11_20231219.pth",
        "path": ROOT
        / "models/pose/rtm/rtmo-l_16xb16-700e_body7-crowdpose-640x640-5bafdc11_20231219.pth",
        "sha256": "5bafdc11e43fba1a834e1323013108831b3e1e0761681dbe7a37896a179f2183",
        "bytes": 178452521,
    },
}
DEPENDENCIES = (
    "numpy==1.26.4",
    "mmcv-lite==2.1.0",
    "mmengine==0.10.7",
    "mmdet==3.2.0",
    "xtcocotools==1.14.3",
    "json-tricks==3.17.3",
    "munkres==1.1.4",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def _install_source(spec: dict) -> None:
    path = Path(spec["path"])
    if not (path / ".git").is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--filter=blob:none", spec["url"], str(path)])
    _run(["git", "fetch", "origin", spec["commit"], "--depth", "1"], cwd=path)
    _run(["git", "checkout", "--detach", spec["commit"]], cwd=path)


def _install_checkpoint(spec: dict) -> None:
    path = Path(spec["path"])
    if path.is_file() and _sha256(path) == spec["sha256"]:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    urllib.request.urlretrieve(spec["url"], partial)  # noqa: S310 - fixed HTTPS allowlist
    if _sha256(partial) != spec["sha256"]:
        raise RuntimeError(f"downloaded checkpoint hash mismatch: {path.name}")
    os.replace(partial, path)


def install() -> None:
    if not PYTHON.is_file():
        raise FileNotFoundError(PYTHON)
    for spec in SOURCES.values():
        _install_source(spec)
    for spec in CHECKPOINTS.values():
        _install_checkpoint(spec)
    DEPS.mkdir(parents=True, exist_ok=True)
    _run(
        [
            str(PYTHON),
            "-m",
            "pip",
            "install",
            "--target",
            str(DEPS),
            "--upgrade",
            *DEPENDENCIES,
        ]
    )
    _run(
        [
            str(PYTHON),
            "-m",
            "pip",
            "install",
            "--target",
            str(DEPS),
            "--no-deps",
            "--upgrade",
            str(SOURCES["mmpose"]["path"]),
        ]
    )


def verify() -> dict:
    source_records = {}
    for name, spec in SOURCES.items():
        path = Path(spec["path"])
        commit = _run(["git", "rev-parse", "HEAD"], cwd=path)
        tree = _run(["git", "rev-parse", "HEAD^{tree}"], cwd=path)
        dirty = _run(["git", "status", "--porcelain"], cwd=path)
        license_hash = _sha256(path / "LICENSE")
        if (commit, tree, license_hash, dirty) != (
            spec["commit"],
            spec["tree"],
            spec["license_sha256"],
            "",
        ):
            raise RuntimeError(f"{name} source checkout failed immutable verification")
        source_records[name] = {
            "repository": spec["url"],
            "commit": commit,
            "tree": tree,
            "license_sha256": license_hash,
            "clean": True,
        }
    checkpoint_records = {}
    for name, spec in CHECKPOINTS.items():
        path = Path(spec["path"])
        if not path.is_file() or path.stat().st_size != spec["bytes"]:
            raise RuntimeError(f"{name} checkpoint missing or has wrong size")
        actual_hash = _sha256(path)
        if actual_hash != spec["sha256"]:
            raise RuntimeError(f"{name} checkpoint hash mismatch")
        checkpoint_records[name] = {
            "source_url": spec["url"],
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": actual_hash,
        }
    mim = DEPS / "mmpose" / ".mim" / "model-index.yml"
    if not mim.is_file():
        raise RuntimeError("isolated MMPose package lacks required .mim metadata")
    packages = _run([str(PYTHON), "-m", "pip", "freeze", "--path", str(DEPS)]).splitlines()
    return {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "sources": source_records,
        "checkpoints": checkpoint_records,
        "runtime": {
            "python": str(PYTHON),
            "dependency_layer": DEPS.relative_to(ROOT).as_posix(),
            "packages": sorted(packages),
            "mmpose_mim_metadata_sha256": _sha256(mim),
            "base_environment_unchanged": True,
        },
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "promotion_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.install:
        install()
    document = verify()
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
