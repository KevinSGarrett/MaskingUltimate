#!/usr/bin/env bash
set -euo pipefail

volume_path="${RUNPOD_VOLUME_PATH:-/runpod-volume}"
workspace_path="${MASKFACTORY_WORKSPACE_PATH:-/workspace}"

if [[ -d "${workspace_path}/maskfactory" ]]; then
  # Some Serverless templates mount the network volume directly at /workspace.
  # Preserve that mount and run against it without creating a compatibility link.
  :
elif [[ -d "${volume_path}" ]]; then
  if [[ -e "${workspace_path}" && ! -L "${workspace_path}" ]]; then
    if [[ -d "${workspace_path}" ]] && rmdir "${workspace_path}" 2>/dev/null; then
      :
    else
      echo "${workspace_path} exists, is not the MaskFactory network volume, and cannot become the Serverless network-volume compatibility link" >&2
      exit 64
    fi
  fi
  ln -sfn "${volume_path}" "${workspace_path}"
else
  echo "MaskFactory network volume is absent at both ${workspace_path} and ${volume_path}" >&2
  exit 66
fi

if [[ "${1:-}" == "--prepare-only" ]]; then
  exit 0
fi

exec python /handler.py
