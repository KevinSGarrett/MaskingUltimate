#!/usr/bin/env bash
set -euo pipefail

RUNPOD_API_KEY="$(
  python -c 'import tomllib; print(tomllib.load(open("/root/.runpod/config.toml", "rb"))["apikey"])'
)"
export RUNPOD_API_KEY
exec "$@"
