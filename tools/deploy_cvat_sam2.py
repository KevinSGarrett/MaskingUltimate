"""Sync and deploy MaskFactory's SAM2 adapter into pinned CVAT v2.24.0."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "integrations"
    / "cvat"
    / "serverless"
    / "pytorch"
    / "facebookresearch"
    / "sam2"
    / "nuclio"
)
DESTINATION = ROOT / "cvat" / "serverless" / "pytorch" / "facebookresearch" / "sam2" / "nuclio"
WSL_COMMAND = (
    "set -euo pipefail; "
    "export DOCKER_CONFIG=/tmp/maskfactory-docker-config; "
    "mkdir -p /tmp/maskfactory-docker-config; "
    "printf '{}\\n' > /tmp/maskfactory-docker-config/config.json; "
    "chmod +x /mnt/c/Comfy_UI_Main_Masking/tools/docker-localonly-bin/docker; "
    "export PATH=/mnt/c/Comfy_UI_Main_Masking/tools/docker-localonly-bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
    "cd /mnt/c/Comfy_UI_Main_Masking/cvat; "
    "(nuctl create project cvat --platform local || "
    "nuctl get projects --platform local | grep -q cvat); "
    "nuctl deploy --project-name cvat "
    "--path serverless/pytorch/facebookresearch/sam2/nuclio "
    "--file serverless/pytorch/facebookresearch/sam2/nuclio/function.yaml "
    "--platform local "
    "--env CVAT_FUNCTIONS_REDIS_HOST=cvat_redis_ondisk "
    "--env CVAT_FUNCTIONS_REDIS_PORT=6666 "
    '--platform-config \'{"attributes": {"network": "cvat_cvat"}}\'; '
    "nuctl get function --platform local"
)


def main() -> None:
    """Copy the tracked adapter and invoke CVAT's pinned CPU deploy script."""
    if not (ROOT / "cvat" / ".git").exists():
        raise RuntimeError("Pinned CVAT checkout is missing; run bootstrap_cvat.py first")
    shutil.copytree(SOURCE, DESTINATION, dirs_exist_ok=True)

    if os.name == "nt":
        command = ["wsl", "-d", "Ubuntu-22.04", "--", "bash", "-lc", WSL_COMMAND]
    else:
        command = ["bash", "-lc", WSL_COMMAND]
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603


if __name__ == "__main__":
    main()
