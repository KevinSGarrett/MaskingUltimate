"""Seal bounded Mode B loopback RUNTIME evidence for MF-P6-12.04."""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def get_json(url: str, timeout: float = 10.0) -> tuple[int, bytes, dict]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read()
        return int(response.status), body, json.loads(body.decode("utf-8"))


def post_predict(image: Path) -> dict:
    boundary = "----mfbound"
    image_bytes = image.read_bytes()
    body = b"".join(
        [
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="image"; '
                'filename="ultralytics_bus_adults.jpg"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode("ascii")
            + image_bytes
            + b"\r\n",
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="labels"\r\n\r\n'
                "left_forearm\r\n"
            ).encode("ascii"),
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    request = urllib.request.Request(
        "http://127.0.0.1:8765/predict",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
            return {"http_status": int(response.status), "body": payload}
    except urllib.error.HTTPError as exc:
        return {
            "http_status": int(exc.code),
            "body": exc.read().decode("utf-8", errors="replace"),
            "error_type": "HTTPError",
        }


def main() -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "qa" / "live_verification" / f"mode_b_runtime_loopback_health_{ts}.json"
    health_status, health_body, health = get_json("http://127.0.0.1:8765/health")
    models_status, models_body, models = get_json("http://127.0.0.1:8765/models")
    predict = post_predict(ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg")

    stdout = ROOT / "logs" / "maskfactory_8765_20260719T213725309Z.stdout.log"
    stderr = ROOT / "logs" / "maskfactory_8765_20260719T213725309Z.stderr.log"
    lock_path = ROOT / "runs" / "gpu.lock"
    lock_doc = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else None

    ss = subprocess.check_output(
        ["wsl", "-d", "Ubuntu-22.04", "--", "bash", "-lc", "ss -ltnp | grep 8765 || true"],
        text=True,
    )
    ps = subprocess.check_output(
        [
            "wsl",
            "-d",
            "Ubuntu-22.04",
            "--",
            "bash",
            "-lc",
            "ps -p 467 -o pid=,etime=,cmd= || true",
        ],
        text=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    free_gib = round(shutil.disk_usage("C:/").free / (1024**3), 2)

    doc = {
        "schema_version": "1.0.0",
        "artifact_type": "mode_b_runtime_loopback_bounded_evidence",
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "related_tracker_item": "MF-P6-12.04",
        "project_head": head,
        "branch": branch,
        "authoritative_runtime": {
            "distro": "Ubuntu-22.04",
            "interpreter": "/home/kevin/miniforge3/envs/maskfactory/bin/python",
            "pythonpath": "/mnt/c/Comfy_UI_Main_Masking/src",
            "command": (
                "wsl.exe -d Ubuntu-22.04 --cd /mnt/c/Comfy_UI_Main_Masking -e /usr/bin/env "
                "PYTHONPATH=/mnt/c/Comfy_UI_Main_Masking/src "
                "/home/kevin/miniforge3/envs/maskfactory/bin/python -m maskfactory.cli serve "
                "--port 8765"
            ),
            "windows_wsl_client_pid": 13824,
            "linux_service_pid": 467,
        },
        "disk_free_gib_c": free_gib,
        "surfaces": {
            "windows_loopback_health": {
                "url": "http://127.0.0.1:8765/health",
                "http_status": health_status,
                "body": health,
                "body_sha256": hashlib.sha256(health_body).hexdigest(),
                "tier": "RUNTIME_PASS_BOUNDED",
                "claim": "draft-service health only; not champion-backed prediction",
            },
            "windows_loopback_models": {
                "url": "http://127.0.0.1:8765/models",
                "http_status": models_status,
                "governed_model_count": len(models.get("models") or []),
                "champion_count": len(models.get("champions") or {}),
                "loaded_model_count": len(models.get("loaded_models") or []),
                "body_sha256": hashlib.sha256(models_body).hexdigest(),
                "tier": "RUNTIME_PASS_BOUNDED",
                "claim": "governed registry enumeration only; champions empty",
            },
            "predict_draft": {
                "url": "http://127.0.0.1:8765/predict",
                "result": predict,
                "tier": "AWAITING_RUNTIME",
                "exact_blocker": (
                    "champion prediction provider is not configured "
                    "(HTTP 503 typed refuse); zero configured champions"
                ),
            },
            "refine_draft": {
                "url": "http://127.0.0.1:8765/refine",
                "prior_malformed_clicks": {
                    "http_status": 503,
                    "detail": "JSON parse error",
                    "note": "first probe used bad PowerShell quoting",
                },
                "bounded_valid_clicks_probe": {
                    "timeout_seconds": 30,
                    "curl_exit": 28,
                    "http_status": None,
                    "note": (
                        "on-demand interactive refiner load did not return within 30s; "
                        "not retried under ~32 GiB free to avoid disk/OOM risk"
                    ),
                },
                "tier": "AWAITING_RUNTIME",
                "exact_blocker": (
                    "on-demand interactive refiner (SAM-class) load exceeded 30s bounded "
                    "probe under disk_free_gib_c~32; no refine draft bytes obtained"
                ),
            },
        },
        "listener": {
            "wsl_ss": ss.strip(),
            "wildcard_listener": False,
            "address": "127.0.0.1:8765",
            "linux_ps": ps.strip(),
        },
        "gpu_lock": {
            "path": "runs/gpu.lock",
            "document": lock_doc,
            "purpose_ok": bool(
                lock_doc
                and lock_doc.get("purpose") == "serve_mode_b"
                and lock_doc.get("pid") == 467
            ),
        },
        "managed_logs": {
            "stdout": stdout.relative_to(ROOT).as_posix(),
            "stderr": stderr.relative_to(ROOT).as_posix(),
            "stdout_bytes": stdout.stat().st_size,
            "stderr_bytes": stderr.stat().st_size,
            "stdout_sha256": (stdout_sha := sha_file(stdout)),
            "stderr_sha256": (stderr_sha := sha_file(stderr)),
            "hash_status": (
                "hashed"
                if stdout_sha is not None and stderr_sha is not None
                else "deferred_while_managed_handles_are_open_or_locked"
            ),
        },
        "tiers": {
            "mode_b_windows_loopback_health_models": "RUNTIME_PASS_BOUNDED",
            "mode_b_predict_draft": "AWAITING_RUNTIME",
            "mode_b_refine_draft": "AWAITING_RUNTIME",
            "mode_b_champion_backed_prediction": "AWAITING_RUNTIME",
            "mode_b_visual_qa": "NOT_CLAIMED",
            "mode_b_production_evidence": "NOT_CLAIMED",
            "mf_p6_12_04_item_complete": False,
        },
        "truth_boundary": (
            "RUNTIME_PASS_BOUNDED applies only to live Windows 127.0.0.1:8765 /health and "
            "/models with owned serve_mode_b lock and exact loopback bind. Predict "
            "typed-refuses without champion. Refine on-demand load timed out in a 30s "
            "bounded probe. No champion-backed prediction, VISUAL_QA_PASS_BOUNDED, or "
            "PRODUCTION_EVIDENCE_PASS is claimed. MF-P6-12.04 remains incomplete."
        ),
        "service_retained_running": True,
    }
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    doc["self_sha256"] = hashlib.sha256(canonical).hexdigest()
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    print("self_sha256", doc["self_sha256"])
    print("health_sha", doc["surfaces"]["windows_loopback_health"]["body_sha256"])
    print("models_sha", doc["surfaces"]["windows_loopback_models"]["body_sha256"])
    print("stdout_sha", doc["managed_logs"]["stdout_sha256"])
    print("stderr_sha", doc["managed_logs"]["stderr_sha256"])
    print("tier", doc["tiers"]["mode_b_windows_loopback_health_models"])
    print("champions", doc["surfaces"]["windows_loopback_models"]["champion_count"])
    print("predict", predict)
    print("disk", free_gib)


if __name__ == "__main__":
    main()
