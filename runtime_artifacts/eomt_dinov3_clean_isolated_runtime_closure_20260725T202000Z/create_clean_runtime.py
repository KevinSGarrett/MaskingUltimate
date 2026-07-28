from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/maskfactory")
OUT = ROOT / "runtime_artifacts/eomt_dinov3_clean_isolated_runtime_closure_20260725T202000Z"
BINDING = OUT / "clean_runtime_binding.json"
RECEIPT = OUT / "CLEAN_ISOLATED_RUNTIME_RECEIPT.json"
ENV = OUT / "venv"
SYSTEM_PYTHON = Path("/usr/bin/python3")
LOCK = ROOT / "env/eomt_dinov3_clean_runtime.requirements_v3.lock.txt"
TRANSFORMERS_ROOT = ROOT / "runtime_artifacts/eomt_dinov3_runtime_closure_candidate_20260725T181500Z"
TORCH_ROOT = ROOT / "runtime_artifacts/eomt_dinov3_clean_torch_closure_candidate_20260725T190000Z"
SCIPY_ROOT = ROOT / "runtime_artifacts/eomt_dinov3_scipy_dependency_recovery_20260725T200000Z"


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


def wheel_rows(receipt_path: Path) -> list[dict]:
    payload = json.loads(receipt_path.read_text())
    return payload["wheels"] if "wheels" in payload else [payload["wheel"]]


def main() -> int:
    receipt = {
        "artifact_type": "eomt_dinov3_clean_isolated_runtime_closure_receipt.v2",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": None,
        "controls": {"network_install": False, "model_load": False, "gpu_execution": False, "provider_promotion": False, "system_site_packages": False},
        "binding": {"path": str(BINDING.relative_to(ROOT)), "sha256": sha(BINDING)},
    }
    try:
        if ENV.exists() or RECEIPT.exists():
            raise RuntimeError("environment or receipt already exists; refusing duplicate launch")
        binding = json.loads(BINDING.read_text())
        if binding["self_sha256"] != canonical(binding):
            raise RuntimeError("binding canonical self hash mismatch")
        if sha(LOCK) != binding["base_contract"]["requirements_lock_sha256"]:
            raise RuntimeError("requirements lock hash mismatch")
        active_lines = [line for line in LOCK.read_text().splitlines() if line and not line.startswith("#")]
        if len(active_lines) != binding["base_contract"]["requirements_count"]:
            raise RuntimeError("requirements count mismatch")
        candidates = [
            (TRANSFORMERS_ROOT / "CANDIDATE_CLOSURE_RECEIPT.json", TRANSFORMERS_ROOT / "wheels", binding["base_contract"]["transformers_candidate_receipt_sha256"]),
            (TORCH_ROOT / "CLEAN_TORCH_CLOSURE_STAGE_RECEIPT.json", TORCH_ROOT / "wheels", binding["base_contract"]["torch_candidate_receipt_sha256"]),
            (SCIPY_ROOT / "SCIPY_STAGE_RECEIPT.json", SCIPY_ROOT / "wheels", binding["base_contract"]["scipy_candidate_receipt_sha256"]),
        ]
        locked_hashes = {line.split("sha256:", 1)[1] for line in active_lines}
        verified = []
        for receipt_path, wheel_root, expected_receipt_hash in candidates:
            if sha(receipt_path) != expected_receipt_hash:
                raise RuntimeError("candidate receipt hash mismatch: " + str(receipt_path.relative_to(ROOT)))
            for row in wheel_rows(receipt_path):
                wheel = wheel_root / row["filename"]
                if not wheel.is_file() or wheel.stat().st_size != row["bytes"] or sha(wheel) != row["sha256"]:
                    raise RuntimeError("candidate wheel drift: " + row["filename"])
                if row["sha256"] not in locked_hashes:
                    raise RuntimeError("requirements lock omits candidate wheel: " + row["filename"])
                verified.append(row["filename"])
        if len(set(verified)) < binding["base_contract"]["requirements_count"]:
            raise RuntimeError("candidate closure is incomplete")
        receipt["base_python"] = run([str(SYSTEM_PYTHON), "-c", "import json,sys; print(json.dumps({'version':sys.version,'executable':sys.executable}))"])
        if receipt["base_python"]["returncode"] or "3.11" not in receipt["base_python"]["output"]:
            raise RuntimeError("required CPython 3.11 is unavailable")
        receipt["create_venv"] = run([str(SYSTEM_PYTHON), "-m", "venv", str(ENV)])
        if receipt["create_venv"]["returncode"]:
            raise RuntimeError("clean venv creation failed")
        python = ENV / "bin/python"
        receipt["install"] = run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--require-hashes",
            "--find-links", str(TRANSFORMERS_ROOT / "wheels"), "--find-links", str(TORCH_ROOT / "wheels"), "--find-links", str(SCIPY_ROOT / "wheels"), "-r", str(LOCK),
        ])
        if receipt["install"]["returncode"]:
            raise RuntimeError("hash-bound clean closure installation failed")
        receipt["pip_check"] = run([str(python), "-m", "pip", "check"])
        if receipt["pip_check"]["returncode"]:
            raise RuntimeError("clean closure pip check failed")
        receipt["import_smoke"] = run([
            str(python), "-c",
            "import json,torch,transformers,tokenizers,safetensors,huggingface_hub,scipy; from transformers import EomtDinov3ForUniversalSegmentation; print(json.dumps({'torch':torch.__version__,'transformers':transformers.__version__,'tokenizers':tokenizers.__version__,'safetensors':safetensors.__version__,'huggingface_hub':huggingface_hub.__version__,'scipy':scipy.__version__,'eomt_class_imported':EomtDinov3ForUniversalSegmentation.__name__},sort_keys=True))",
        ])
        if receipt["import_smoke"]["returncode"]:
            raise RuntimeError("clean closure import smoke failed")
        receipt["verified_candidate_wheel_rows"] = len(verified)
        receipt["status"] = "CLEAN_ISOLATED_RUNTIME_CLOSURE_IMPORT_PASS"
        receipt["environment"] = {"path": str(ENV.relative_to(ROOT)), "python": str(python.relative_to(ROOT)), "python_sha256": sha(python)}
        receipt["next_safe_action"] = "Create one new immutable shadow-only EoMT model-load binding. This receipt establishes only hash-bound dependency closure and CPU-side imports."
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        return 0
    except Exception as exc:
        receipt["status"] = "CLEAN_ISOLATED_RUNTIME_CLOSURE_FAIL"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        receipt["environment_preserved"] = str(ENV.relative_to(ROOT)) if ENV.exists() else None
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
