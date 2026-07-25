from __future__ import annotations

import hashlib
import json
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/maskfactory")
OUT = ROOT / "runtime_artifacts/eomt_dinov3_clean_torch_closure_candidate_20260725T190000Z"
HELPER = ROOT / ".train_cu128_ada/bin/python"
BINDING = OUT / "clean_torch_stage_binding.json"
RECEIPT = OUT / "CLEAN_TORCH_CLOSURE_STAGE_RECEIPT.json"
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
    return {"argv": argv, "returncode": completed.returncode, "output": completed.stdout[-30000:]}


def main() -> int:
    receipt = {
        "artifact_type": "eomt_dinov3_clean_torch_closure_stage_receipt.v1",
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
        receipt["download"] = run([
            str(HELPER), "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
            "--index-url", "https://download.pytorch.org/whl/cu128", "--extra-index-url", "https://pypi.org/simple",
            "--dest", str(WHEELS), "torch==2.11.0+cu128",
        ])
        if receipt["download"]["returncode"]:
            raise RuntimeError("clean CUDA torch closure staging failed")
        files = sorted(path for path in WHEELS.iterdir() if path.is_file())
        if not files or not any(path.name.startswith("torch-2.11.0+cu128") and path.suffix == ".whl" for path in files):
            raise RuntimeError("exact CUDA torch wheel is absent from staged closure")
        receipt["wheels"] = [{"filename": path.name, "bytes": path.stat().st_size, "sha256": sha(path)} for path in files]
        receipt["status"] = "CLEAN_TORCH_CLOSURE_STAGE_PASS"
        receipt["next_safe_action"] = "Resolve and hash-bind this staged CUDA core with the prior 27-wheel Transformers candidate in a clean venv; no model operation is authorized by this stage."
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"], "wheel_count": len(files)}, sort_keys=True))
        return 0
    except Exception as exc:
        receipt["status"] = "CLEAN_TORCH_CLOSURE_STAGE_FAIL"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
