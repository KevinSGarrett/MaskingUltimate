from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
entry = """
### Correction — serve image build crashed the daemon; Docker/CVAT restored
- The `maskfactory/serve:cu128` build reached the torch cu128 install (~7 GiB of torch+CUDA wheels) and
  the Docker Desktop daemon/buildkit disconnected (`failed to receive status: rpc error: code =
  Unavailable desc = ... EOF`) — the constrained WSL2 backend was exhausted and the engine went down.
- **Restored services** (per the do-not-leave-services-down rule): restarted Docker Desktop; waited for
  the daemon; verified production **CVAT 2.24.0** at `http://localhost:8080/api/server/about`,
  **nuclio-nuclio-pth-sam2** healthy, and **Ollama 0.32.1** all back up (containers auto-restarted).
- **Honest status:** containerized serve smoke NOT claimed. GPU-container CUDA access (RTX 5060 cap
  12,0) stands. Retry the build with raised WSL2 memory/disk headroom, then run
  `tools/smoke_docker_gpu_serve.py`. Re-sealed evidence self_sha256 ea1a2c75…
"""
path = REPO / "Plan" / "OPS_LOG.md"
with path.open("a", encoding="utf-8") as handle:
    handle.write(entry)
print("appended OPS_LOG correction", len(entry), "chars")
