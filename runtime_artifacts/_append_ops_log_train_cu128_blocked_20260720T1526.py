"""Append-only OPS_LOG for train:cu128 RUNTIME_BLOCKED seal."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "Plan" / "OPS_LOG.md"
MARKER = "## 2026-07-20 15:26 UTC - train:cu128 build BLOCKED (Docker DOWN + C: critical)"

ENTRY = """
## 2026-07-20 15:26 UTC - train:cu128 build BLOCKED (Docker DOWN + C: critical)
**Item:** docker_gpu_train_build_and_training_doctor
**Command:** live docker/pipe/C:/image-inspect probe; hard Desktop restart+wait earlier this wave; python runtime_artifacts/_seal_train_cu128_blocked_20260720T1526.py
**Result:** RUNTIME_BLOCKED (honest). Gate `serve:cu128 exists OR BuildKit free` fails closed: serve image absent; named pipe `dockerDesktopLinuxEngine` absent (BuildKit unavailable). C: free ~15–36 GiB during wave (CRITICAL, << 75 GiB floor / heavy CUDA-devel build gate). `docker_data.vhdx` still 68.11 GiB on C:. Did **not** start `docker compose -f docker/compose.gpu.yml build maskfactory-train`; did **not** run `tools/smoke_docker_gpu_train.py`. Further Docker wake thrash aborted (protect engine + disk). Ollama host 0.32.1 UP; CVAT about unreachable while engine DOWN. No prune/wipe; no USB vhdx migrate. champions=0; no training-doctor green claim.

Evidence: qa/live_verification/train_cu128_blocked_20260720T1526.json. Next: ephemeral reclaim to >=75 GiB C: free -> single stable Docker wake -> sole-build train:cu128 (or serve first) -> training-doctor smoke.
"""


def main() -> None:
    text = OPS.read_text(encoding="utf-8")
    if MARKER in text:
        print("OPS_LOG already has this entry; skip")
        return
    with OPS.open("a", encoding="utf-8", newline="\n") as f:
        f.write(ENTRY if ENTRY.startswith("\n") else "\n" + ENTRY)
    print("APPENDED", MARKER)


if __name__ == "__main__":
    main()
