"""Seal the STATIC Docker train-image contract report.

Proves docker/Dockerfile.train + the maskfactory-train compose service are
coherent with env/openmmlab_training_stack.lock.json WITHOUT building the image
or touching the Docker engine. Never claims a build, mmcv._ext sm_120, a green
training-doctor, a champion, or a certified corpus.

Usage:
  python tools/verify_docker_train_contract.py \
      --output qa/live_verification/docker_train_contract_static_<ts>.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from maskfactory.training.docker_contract import (
    DockerTrainContractError,
    run_docker_train_contract_suite,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default = (
        f"qa/live_verification/docker_train_contract_static_"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    parser.add_argument("--output", type=Path, default=Path(default))
    args = parser.parse_args()

    try:
        report = run_docker_train_contract_suite()
    except DockerTrainContractError as exc:
        print(f"docker_train_contract FAILED: {exc}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proof_tier": report["proof_tier"], "report_id": report["report_id"]}))
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
