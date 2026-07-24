#!/usr/bin/env bash
set -euo pipefail

volume_path="${RUNPOD_VOLUME_PATH:-/runpod-volume}"
workspace_path="${MASKFACTORY_WORKSPACE_PATH:-/workspace}"

test -d "${volume_path}"
if [[ -e "${workspace_path}" && ! -L "${workspace_path}" ]]; then
  if [[ -d "${workspace_path}" ]] && rmdir "${workspace_path}" 2>/dev/null; then
    :
  else
    echo "${workspace_path} exists, is not an empty directory, and cannot become the Serverless network-volume compatibility link" >&2
    exit 64
  fi
fi
ln -sfn "${volume_path}" "${workspace_path}"

if [[ "${1:-}" == "--prepare-only" ]]; then
  exit 0
fi

exec python /handler.py
