"""Seal the STATIC Docker serve-image contract report.

Proves docker/Dockerfile.serve + docker/requirements-serve.txt + the
maskfactory-serve compose service are coherent with env/requirements.lock.txt
WITHOUT building the image or touching the Docker engine. Never claims a build,
torch CUDA inside a container, a green serve /health, a champion, or Mode-B
predict/refine backing.

Usage:
  python tools/verify_docker_serve_contract.py \
      --output qa/live_verification/docker_serve_contract_static_<ts>.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from maskfactory.serve.docker_contract import (
    DockerServeContractError,
    run_docker_serve_contract_suite,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default = (
        f"qa/live_verification/docker_serve_contract_static_"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    parser.add_argument("--output", type=Path, default=Path(default))
    args = parser.parse_args()

    try:
        report = run_docker_serve_contract_suite()
    except DockerServeContractError as exc:
        print(f"docker_serve_contract FAILED: {exc}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proof_tier": report["proof_tier"], "report_id": report["report_id"]}))
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
