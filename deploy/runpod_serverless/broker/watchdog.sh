#!/usr/bin/env bash
set -euo pipefail

CONTROL_ROOT="${CONTROL_ROOT:-/workspace/.maskfactory/serverless_overflow_control}"
STATE_ROOT="${STATE_ROOT:-/workspace/.maskfactory/serverless_overflow}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-15}"
LOCK_FILE="${STATE_ROOT}/watchdog.lock"
LOG_FILE="${STATE_ROOT}/watchdog.log"

mkdir -p "${STATE_ROOT}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Serverless overflow watchdog is already running" >&2
  exit 0
fi

while true; do
  if ! /root/.runpod/with_runpod_api_key.sh \
    python "${CONTROL_ROOT}/tools/manage_runpod_serverless_overflow.py" \
    --config "${CONTROL_ROOT}/configs/runpod_serverless_overflow.yaml" \
    reconcile-active >>"${LOG_FILE}" 2>&1; then
    printf '%s reconcile-active failed\n' "$(date -u +%FT%TZ)" >>"${LOG_FILE}"
  fi
  sleep "${INTERVAL_SECONDS}"
done
