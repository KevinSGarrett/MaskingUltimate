from __future__ import annotations

import hashlib
import json
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/maskfactory")
OUT = ROOT / "runtime_artifacts/eomt_dinov3_scipy_dependency_recovery_20260725T200000Z"
HELPER = ROOT / ".train_cu128_ada/bin/python"
BINDING = OUT / "scipy_stage_binding.json"
RECEIPT = OUT / "SCIPY_STAGE_RECEIPT.json"
WHEELS = OUT / "wheels"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps({key: value for key, value in payload.items() if key != "self_sha256"}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_receipt(payload: dict) -> None:
    payload["self_sha256"] = canonical(payload)
    RECEIPT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run(argv: list[str]) -> dict:
    completed = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {"argv": argv, "returncode": completed.returncode, "output": completed.stdout[-20000:]}


def main() -> int:
    receipt = {
        "artifact_type": "eomt_dinov3_scipy_dependency_recovery_receipt.v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": None,
        "controls": {"network_download": True, "package_install": False, "model_load": False, "gpu_execution": False, "provider_promotion": False},
        "binding": {"path": str(BINDING.relative_to(ROOT)), "sha256": sha(BINDING)},
    }
    try:
        if RECEIPT.exists() or WHEELS.exists():
            raise RuntimeError("receipt or wheel directory already exists; refusing duplicate launch")
        binding = json.loads(BINDING.read_text())
        if binding["self_sha256"] != canonical(binding):
            raise RuntimeError("binding canonical self hash mismatch")
        WHEELS.mkdir(parents=True, exist_ok=False)
        receipt["download"] = run([str(HELPER), "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:", "--no-deps", "--dest", str(WHEELS), "scipy==1.17.1"])
        if receipt["download"]["returncode"]:
            raise RuntimeError("wheel-only SciPy staging failed")
        files = sorted(path for path in WHEELS.iterdir() if path.is_file())
        if len(files) != 1 or not files[0].name.startswith("scipy-1.17.1") or files[0].suffix != ".whl":
            raise RuntimeError("expected exactly one scipy 1.17.1 wheel")
        wheel = files[0]
        receipt["wheel"] = {"filename": wheel.name, "bytes": wheel.stat().st_size, "sha256": sha(wheel)}
        receipt["status"] = "SCIPY_ARTIFACT_STAGE_PASS"
        receipt["next_safe_action"] = "Create a new 54-package requirements lock and a new clean isolated runtime closure; this stage does not install SciPy or load EoMT."
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        return 0
    except Exception as exc:
        receipt["status"] = "SCIPY_ARTIFACT_STAGE_FAIL"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
