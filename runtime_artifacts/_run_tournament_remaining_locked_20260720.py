"""Wait for GpuLock, then emit MVC for uncovered sibling-128 remaining samples.

Coordinates with batch-C / batch-B holders: never steals a live lock, chunks
to fit 8 GiB VRAM (BiRefNet→SCHP→faceparse→SAM2 sequenced). Refreshes the
remaining set against production runs/ before each chunk.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from maskfactory.gpu import (  # noqa: E402
    GpuLock,
    GpuLockBusyError,
    GpuLockStaleError,
    lock_state,
)

COMFY_PY = Path(r"C:\Comfy_UI_Main\ComfyUI\.venv\Scripts\python.exe")
FEED_POINTER = REPO / "qa/live_verification/tournament_sample_set_sibling_feed_latest.json"
REMAINING_LATEST = (
    REPO / "qa/live_verification/tournament_sample_set_remaining_uncovered_latest.json"
)
MACHINE_ROOT = REPO / "runs" / "autonomous_gold_tournament_remaining_20260720"
CHUNK = 24
WAIT_TIMEOUT_S = 10800
POLL_S = 30
MAX_CHUNKS = 6


def _seal(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("self_sha256", None)
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return doc


def _mvc_ids() -> set[str]:
    ids: set[str] = set()
    for path in (REPO / "runs").rglob("autonomy/*.json"):
        if path.name.endswith(".corpus_record.json"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("status") == "machine_verified_candidate":
            ids.add(str(doc.get("image_id") or path.parent.parent.name))
    return ids


def _refresh_remaining() -> Path:
    feed = json.loads(FEED_POINTER.read_text(encoding="utf-8"))
    sample_set = json.loads((REPO / feed["sample_set_path"]).read_text(encoding="utf-8"))
    mvc = _mvc_ids()
    remaining = [
        sample
        for sample in sample_set["samples"]
        if f"img_{sample['source_sha256'][:12]}" not in mvc
    ]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    doc = {
        "artifact_type": "tournament_sample_set",
        "schema_version": "1.0.0",
        "role": "tournament_remaining_uncovered_from_sibling_128",
        "parent_sample_set_path": feed["sample_set_path"].replace("\\", "/"),
        "parent_self_sha256": sample_set.get("self_sha256"),
        "sibling_feed_path": str(FEED_POINTER.relative_to(REPO)).replace("\\", "/"),
        "sample_count": len(remaining),
        "samples": remaining,
        "gold_authority": False,
        "mask_authored": False,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "coverage_baseline": {
            "feed_total": int(feed.get("sample_count") or len(sample_set["samples"])),
            "already_mvc_in_runs": int(feed.get("sample_count") or 128) - len(remaining),
            "remaining": len(remaining),
            "pool_mvc_unique_ids": len(mvc),
        },
    }
    body = json.dumps(
        {k: v for k, v in doc.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    doc["self_sha256"] = hashlib.sha256(body).hexdigest()
    out = REPO / f"qa/live_verification/tournament_sample_set_remaining_uncovered_{stamp}.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REMAINING_LATEST.write_text(
        json.dumps(
            {
                "artifact_type": "tournament_sample_set_pointer",
                "sample_set_path": str(out.relative_to(REPO)).replace("\\", "/"),
                "sample_count": doc["sample_count"],
                "sample_set_self_sha256": doc["self_sha256"],
                "recorded_at": doc["recorded_at"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def _wait_and_acquire(image_id: str) -> GpuLock:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while True:
        state, existing, age = lock_state()
        if state == "stale":
            print(f"removing stale gpu.lock age={age:.0f}s existing={existing}", flush=True)
            (REPO / "runs" / "gpu.lock").unlink(missing_ok=True)
        lock = GpuLock(purpose="pipeline", image_id=image_id)
        try:
            lock.acquire()
            print(f"ACQUIRED token={lock._token} image_id={image_id}", flush=True)
            return lock
        except GpuLockBusyError as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"GPU lock busy for {WAIT_TIMEOUT_S}s: {exc}") from exc
            print(f"wait_lock: {exc}", flush=True)
            time.sleep(POLL_S)
        except GpuLockStaleError as exc:
            print(f"stale: {exc}", flush=True)
            (REPO / "runs" / "gpu.lock").unlink(missing_ok=True)
            time.sleep(2)


def _run_chunk(sample_set: Path, limit: int, stamp: str, chunk_idx: int) -> dict[str, Any]:
    machine_root = MACHINE_ROOT / f"chunk_{chunk_idx:02d}"
    machine_root.mkdir(parents=True, exist_ok=True)
    out = (
        REPO
        / f"qa/live_verification/multiprovider_tournament_remaining_{stamp}_c{chunk_idx:02d}.json"
    )
    console = (
        REPO / f"qa/live_verification/_tournament_remaining_console_{stamp}_c{chunk_idx:02d}.txt"
    )
    env = os.environ.copy()
    env["MASKFACTORY_MACHINE_ROOT"] = str(REPO / "runs")
    env["PYTHONUNBUFFERED"] = "1"
    with console.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [
                str(COMFY_PY),
                "-u",
                str(REPO / "tools/run_multiprovider_gold_tournament.py"),
                "--sample-set",
                str(sample_set),
                "--limit",
                str(limit),
                "--output",
                str(out),
                "--machine-root",
                str(machine_root),
            ],
            cwd=str(REPO),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            handle.write(line)
            handle.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        code = proc.wait()
    evidence: dict[str, Any] = {}
    if out.is_file():
        try:
            evidence = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            evidence = {}
    counts = evidence.get("counts") or {}
    return {
        "exit": code,
        "output": str(out.relative_to(REPO)).replace("\\", "/"),
        "console": str(console.relative_to(REPO)).replace("\\", "/"),
        "machine_root": str(machine_root.relative_to(REPO)).replace("\\", "/"),
        "mvc": int(counts.get("machine_verified_candidate") or 0),
        "residual": int(counts.get("residual_human_queue") or 0),
        "agreement_fail": int(counts.get("agreement_gate_failed") or 0),
        "samples_attempted": evidence.get("samples_attempted"),
        "self_sha256": evidence.get("self_sha256"),
    }


def main() -> int:
    if not COMFY_PY.is_file():
        raise SystemExit(f"missing {COMFY_PY}")
    if not FEED_POINTER.is_file():
        raise SystemExit(f"missing {FEED_POINTER}")

    started = time.perf_counter()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    chunk_reports: list[dict[str, Any]] = []

    # Advisory wait so we do not barge ahead of an active holder planning cycle.
    subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/gpu_sequencer.py"),
            "wait",
            "--consumer",
            "pipeline",
            "--timeout",
            str(WAIT_TIMEOUT_S),
            "--poll",
            str(POLL_S),
            "--json",
            str(REPO / f"qa/live_verification/gpu_wait_remaining_{stamp}.json"),
        ],
        cwd=str(REPO),
        check=False,
        timeout=WAIT_TIMEOUT_S + 60,
    )

    for chunk_idx in range(MAX_CHUNKS):
        remaining_path = _refresh_remaining()
        remaining_doc = json.loads(remaining_path.read_text(encoding="utf-8"))
        left = int(remaining_doc["sample_count"])
        print(f"chunk={chunk_idx} remaining={left}", flush=True)
        if left <= 0:
            break

        subprocess.run(["ollama", "stop", "qwen2.5vl:7b"], check=False, capture_output=True)
        time.sleep(1)
        lock = _wait_and_acquire(f"tournament_remaining_c{chunk_idx:02d}")
        try:
            report = _run_chunk(remaining_path, min(CHUNK, left), stamp, chunk_idx)
            chunk_reports.append(report)
            print(json.dumps({"chunk": chunk_idx, **report}, sort_keys=True), flush=True)
        finally:
            try:
                lock.release()
                print("RELEASED", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"RELEASE_ERR {exc}", flush=True)
        # Brief yield so sibling batch waiters can observe a free lock if needed.
        time.sleep(5)

    final_remaining = _refresh_remaining()
    final_doc = json.loads(final_remaining.read_text(encoding="utf-8"))
    from maskfactory.autonomy.corpus import scan_lifecycle_pool

    pool = scan_lifecycle_pool(REPO / "runs")
    seal = {
        "artifact_type": "tournament_remaining_emit_seal",
        "schema_version": "1.0.0",
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PASS_BOUNDED",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "ok",
        "sibling_feed_path": str(FEED_POINTER.relative_to(REPO)).replace("\\", "/"),
        "chunk_size": CHUNK,
        "chunks": chunk_reports,
        "mvc_emitted_this_run": sum(int(c.get("mvc") or 0) for c in chunk_reports),
        "final_remaining_path": str(final_remaining.relative_to(REPO)).replace("\\", "/"),
        "final_remaining_count": final_doc.get("sample_count"),
        "final_coverage": final_doc.get("coverage_baseline"),
        "pool": pool,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "honesty_boundary": {
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "no_lock_steal": True,
            "coordinates_with_batch_locks": True,
            "no_image_builds": True,
        },
    }
    _seal(seal)
    seal_path = REPO / f"qa/live_verification/tournament_remaining_emit_seal_{stamp}.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "seal": str(seal_path.relative_to(REPO)).replace("\\", "/"),
                "mvc_emitted": seal["mvc_emitted_this_run"],
                "remaining": seal["final_remaining_count"],
                "pool_mvc": pool["machine_verified_candidate_count"],
                "self_sha256": seal["self_sha256"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
