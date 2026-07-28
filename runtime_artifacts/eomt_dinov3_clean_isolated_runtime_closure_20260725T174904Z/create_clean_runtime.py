from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/workspace/maskfactory")
OUT = ROOT / "runtime_artifacts/eomt_dinov3_clean_isolated_runtime_closure_20260725T174904Z"
BINDING = OUT / "clean_runtime_binding.json"
RECEIPT = OUT / "CLEAN_ISOLATED_RUNTIME_RECEIPT.json"
ENV = OUT / "venv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(document: dict) -> str:
    unsigned = dict(document)
    unsigned.pop("self_sha256", None)
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {"argv": command, "returncode": completed.returncode, "output": completed.stdout[-30000:]}


def bound_file(relative: str, expected: str) -> Path:
    path = ROOT / relative
    if not path.is_file() or sha256(path) != expected:
        raise RuntimeError(f"bound file drift: {relative}")
    return path


def receipt_wheels(receipt: Path) -> list[dict]:
    document = json.loads(receipt.read_text(encoding="utf-8"))
    return document["wheels"] if "wheels" in document else [document["wheel"]]


def save(document: dict) -> None:
    document["self_sha256"] = canonical(document)
    RECEIPT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    receipt = {
        "artifact_type": "eomt_dinov3_clean_isolated_runtime_closure_receipt.v4",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "status": None,
        "controls": {"network_install": False, "model_load": False, "gpu_execution": False, "provider_promotion": False, "system_site_packages": False},
        "binding": {"path": str(BINDING.relative_to(ROOT)), "sha256": sha256(BINDING)},
    }
    try:
        if ENV.exists() or RECEIPT.exists():
            raise RuntimeError("environment or terminal receipt already exists; refusing duplicate launch")
        binding = json.loads(BINDING.read_text(encoding="utf-8"))
        if binding.get("self_sha256") != canonical(binding):
            raise RuntimeError("binding canonical self hash mismatch")
        if sha256(Path(__file__)) != binding["launcher"]["sha256"]:
            raise RuntimeError("launcher hash drift")
        lock = bound_file(binding["base_contract"]["requirements_lock"], binding["base_contract"]["requirements_lock_sha256"])
        active = [line for line in lock.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
        if len(active) != binding["base_contract"]["requirements_count"]:
            raise RuntimeError("requirements count mismatch")
        locked = {line.split("sha256:", 1)[1] for line in active}
        verified, wheel_roots = [], []
        for candidate in binding["candidates"]:
            candidate_receipt = bound_file(candidate["receipt"], candidate["receipt_sha256"])
            wheel_root = ROOT / candidate["wheel_root"]
            for row in receipt_wheels(candidate_receipt):
                wheel = wheel_root / row["filename"]
                if not wheel.is_file() or wheel.stat().st_size != row["bytes"] or sha256(wheel) != row["sha256"]:
                    raise RuntimeError("candidate wheel drift: " + row["filename"])
                if row["sha256"] not in locked:
                    raise RuntimeError("requirements lock omits candidate wheel: " + row["filename"])
                verified.append(row["filename"])
            wheel_roots.append(wheel_root)
        if len(set(verified)) != binding["base_contract"]["requirements_count"]:
            raise RuntimeError("candidate closure does not cover the complete requirements lock")
        fixture = bound_file(binding["fixture"]["path"], binding["fixture"]["sha256"])
        model = ROOT / binding["model_directory"]
        receipt["base_python"] = run(["/usr/bin/python3", "-c", "import sys; print(sys.version)"])
        if receipt["base_python"]["returncode"] or "3.11" not in receipt["base_python"]["output"]:
            raise RuntimeError("CPython 3.11 is unavailable")
        receipt["create_venv"] = run(["/usr/bin/python3", "-m", "venv", str(ENV)])
        if receipt["create_venv"]["returncode"]:
            raise RuntimeError("clean venv creation failed")
        python = ENV / "bin/python"
        install = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--require-hashes"]
        for wheel_root in wheel_roots:
            install += ["--find-links", str(wheel_root)]
        receipt["install"] = run(install + ["-r", str(lock)])
        if receipt["install"]["returncode"]:
            raise RuntimeError("hash-bound clean closure installation failed")
        receipt["pip_check"] = run([str(python), "-m", "pip", "check"])
        if receipt["pip_check"]["returncode"]:
            raise RuntimeError("clean closure pip check failed")
        smoke = "import json,PIL,torch,torchvision,transformers,scipy; from PIL import Image; from transformers import AutoImageProcessor,EomtDinov3ForUniversalSegmentation; image=Image.open(r'" + str(fixture) + "'); processor=AutoImageProcessor.from_pretrained(r'" + str(model) + "',local_files_only=True); print(json.dumps({'torch':torch.__version__,'torchvision':torchvision.__version__,'transformers':transformers.__version__,'pillow':PIL.__version__,'scipy':scipy.__version__,'fixture_size':list(image.size),'processor':type(processor).__name__,'eomt_class':EomtDinov3ForUniversalSegmentation.__name__},sort_keys=True))"
        receipt["import_smoke"] = run([str(python), "-c", smoke])
        if receipt["import_smoke"]["returncode"]:
            raise RuntimeError("clean closure processor and fixture-decode smoke failed")
        receipt["verified_candidate_wheel_rows"] = len(verified)
        receipt["status"] = "CLEAN_ISOLATED_RUNTIME_CLOSURE_PROCESSOR_AND_FIXTURE_DECODE_PASS"
        receipt["environment"] = {"path": str(ENV.relative_to(ROOT)), "python": str(python.relative_to(ROOT)), "python_sha256": sha256(python)}
        receipt["next_safe_action"] = "Create one new immutable EoMT 66-class random-head GPU shadow binding; no model weight load, CUDA invocation, or provider authority occurred here."
        receipt["ended_at_utc"] = datetime.now(UTC).isoformat()
        save(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        return 0
    except Exception as exc:
        receipt["status"] = "CLEAN_ISOLATED_RUNTIME_CLOSURE_FAIL"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        receipt["environment_preserved"] = str(ENV.relative_to(ROOT)) if ENV.exists() else None
        receipt["ended_at_utc"] = datetime.now(UTC).isoformat()
        save(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
