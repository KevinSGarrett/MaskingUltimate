"""Start the pinned local CVAT stack with Docker 29 compatibility shims."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "cvat" / "docker-compose.yml",
    ROOT / "cvat" / "components" / "serverless" / "docker-compose.serverless.yml",
    ROOT / "configs" / "cvat-compose.maskfactory.yml",
)


def run(*args: str) -> None:
    """Run one required bootstrap command and stop on failure."""
    subprocess.run(args, cwd=ROOT, check=True)  # noqa: S603


def main() -> None:
    """Prepare retired helper alias and start the local-only CVAT stack."""
    run("docker", "pull", "alpine:3.17")
    run("docker", "tag", "alpine:3.17", "gcr.io/iguazio/alpine:3.17")

    env = os.environ.copy()
    env.setdefault("CVAT_HOST", "localhost")
    if os.name == "nt":
        env.setdefault("MASKFACTORY_DATA_PATH", str(ROOT / "data"))
    else:
        env.setdefault("MASKFACTORY_DATA_PATH", "/mnt/c/Comfy_UI_Main_Masking/data")

    command = ["docker", "compose"]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", str(compose_file)))
    command.extend(("up", "-d"))
    subprocess.run(command, cwd=ROOT, env=env, check=True)  # noqa: S603


if __name__ == "__main__":
    main()
