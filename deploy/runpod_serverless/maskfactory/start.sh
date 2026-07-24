#!/usr/bin/env bash
set -euo pipefail

test -d /runpod-volume
if [[ -e /workspace && ! -L /workspace ]]; then
  echo "/workspace exists but is not the Serverless network-volume compatibility link" >&2
  exit 64
fi
ln -sfn /runpod-volume /workspace
exec python /handler.py
