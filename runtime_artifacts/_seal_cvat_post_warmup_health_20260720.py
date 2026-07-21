"""Seal the 2026-07-20 post-warmup CVAT 2.24 + traefik healthy-state snapshot.

Live-probed (not reconstructed): docker ps sample, /api/server/about JSON,
and the boot-warmup 502 pattern read directly from the traefik access-log
JSON lines for this boot cycle (container StartedAt ~08:05:0x -> first
sustained 200 at StartLocal 08:08:38Z / logged 08:08:49Z).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "cvat_post_warmup_health_20260720T0815.json"

evidence = {
    "artifact_type": "cvat_post_warmup_health",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head": "184313d107d60f6a1fce9935658130cfeb2e09d0",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "autonomous_cvat_post_warmup_health_seal",
    "boot_cycle": {
        "container_started_at_utc": {
            "cvat_server": "2026-07-20T08:05:05.992389312Z",
            "cvat_ui": "2026-07-20T08:05:03.719460362Z",
            "cvat_db": "2026-07-20T08:05:07.740328966Z",
            "cvat_redis_inmem": "2026-07-20T08:05:07.507601219Z",
            "cvat_worker_annotation": "2026-07-20T08:05:07.244715731Z",
            "traefik": "2026-07-20T08:05:07.901237284Z",
        },
        "traefik_access_log_source": "docker logs traefik (JSON access-log lines, RouterName=cvat@docker)",
    },
    "boot_warmup_502_pattern": {
        "description": (
            "After container start, traefik proxies to the cvat_server upstream before its "
            "gunicorn/uvicorn workers finish booting + migrations, so every request "
            "(/api/server/about, /api/lambda/functions) receives a genuine upstream 502 "
            "Bad Gateway (OriginStatus=502, not a traefik-side error) for roughly 60-90s. "
            "Once workers are listening, status flips cleanly to 200 and stays sustained; "
            "no partial/flaky state observed after the flip."
        ),
        "observed_502_window": {
            "first_502_seen": {
                "request_count": 24,
                "start_local": "2026-07-20T08:07:26.200676471Z",
                "path": "/api/server/about",
            },
            "last_502_seen": {
                "request_count": 52,
                "start_local": "2026-07-20T08:08:35.095218905Z",
                "path": "/api/server/about",
            },
            "consecutive_502_responses_observed": 24,
            "approx_502_duration_s": 69,
        },
        "first_sustained_200": {
            "request_count": 53,
            "start_local": "2026-07-20T08:08:38.878683434Z",
            "logged_at_utc": "2026-07-20T08:08:49Z",
            "path": "/api/server/about",
            "duration_ns": 10418932689,
            "note": "OriginDuration ~10.4s on this first successful hit (backend still settling), then sub-second on subsequent hits.",
        },
        "related_but_distinct_pattern_nuclio_sam2_cold_start": {
            "description": (
                "POST /api/lambda/functions/pth-sam2 through traefik returned 504 Gateway "
                "Timeout (traefik-side, after 60s) on the first invocation(s) after the "
                "nuclio-nuclio-pth-sam2 function was cold; NOT the same as the CVAT-backend "
                "502 boot-warmup above. Warm re-invocations returned 200 in single-digit "
                "seconds once the function processor was up."
            ),
            "example_504_request_counts": [66, 73, 77, 100],
        },
        "auth_gated_endpoints_note": (
            "/api/lambda/functions unauthenticated probe returns 401 once the backend is up "
            "(Authentication credentials were not provided) - this is expected auth behavior, "
            "not a health failure."
        ),
    },
    "current_probe_post_warmup": {
        "about": {
            "endpoint": "http://localhost:8080/api/server/about",
            "http": 200,
            "latency_s": 0.387359,
            "body": {
                "name": "Computer Vision Annotation Tool",
                "version": "2.24.0",
            },
        },
        "lambda_functions_unauth": {
            "endpoint": "http://localhost:8080/api/lambda/functions",
            "http": 401,
            "detail": "Authentication credentials were not provided.",
            "latency_s": 0.383547,
        },
        "ollama_context_check": {
            "endpoint": "http://127.0.0.1:11434/api/version",
            "http": 200,
            "version": "0.32.1",
        },
    },
    "docker_ps_sample": {
        "captured_via": "docker ps --format / docker inspect -f {{.Config.Image}}",
        "uptime_at_capture": "Up ~9 minutes (production CVAT + traefik + nuclio stack)",
        "production_cvat_traefik_nuclio": [
            {"name": "cvat_server", "image": "cvat/server:v2.24.0", "status": "Up 9 minutes"},
            {"name": "cvat_ui", "image": "cvat/ui:v2.24.0", "status": "Up 9 minutes"},
            {"name": "cvat_utils", "image": "cvat/server:v2.24.0", "status": "Up 9 minutes"},
            {
                "name": "cvat_worker_annotation",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_worker_import",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_worker_export",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_worker_chunks",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_worker_webhooks",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_worker_quality_reports",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_worker_analytics_reports",
                "image": "cvat/server:v2.24.0",
                "status": "Up 9 minutes",
            },
            {"name": "cvat_db", "image": "postgres:15-alpine", "status": "Up 9 minutes"},
            {"name": "cvat_redis_inmem", "image": "redis:7.2.3-alpine", "status": "Up 9 minutes"},
            {
                "name": "cvat_redis_ondisk",
                "image": "apache/kvrocks:2.7.0",
                "status": "Up 9 minutes (healthy)",
            },
            {
                "name": "cvat_clickhouse",
                "image": "clickhouse/clickhouse-server:23.11-alpine",
                "status": "Up 9 minutes",
            },
            {"name": "cvat_opa", "image": "openpolicyagent/opa:0.63.0", "status": "Up 9 minutes"},
            {
                "name": "cvat_grafana",
                "image": "grafana/grafana-oss:10.1.2",
                "status": "Up 9 minutes",
            },
            {
                "name": "cvat_vector",
                "image": "timberio/vector:0.26.0-alpine",
                "status": "Up 9 minutes",
            },
            {"name": "traefik", "image": "traefik:v3.6.1", "status": "Up 9 minutes"},
            {
                "name": "nuclio",
                "image": "quay.io/nuclio/dashboard:1.13.0-amd64",
                "status": "Up 9 minutes (healthy)",
            },
            {
                "name": "nuclio-nuclio-pth-sam2",
                "image": "cvat.pth.sam2:latest",
                "status": "Up 9 minutes (healthy)",
            },
            {
                "name": "nuclio-local-storage-reader",
                "image": "gcr.io/iguazio/alpine:3.17",
                "status": "Up 9 minutes",
            },
        ],
        "cvat269_rehearsal_stack_present": "cvat269_* containers Up (isolated migration rehearsal on 127.0.0.1:18080/18090; not production; untouched)",
    },
    "honesty": [
        "This wave reads/probes only; no docker compose up/down/restart, no volume ops, no config edits.",
        "Boot-warmup 502 window and Nuclio cold-start 504 window are two distinct, correctly-attributed failure modes (upstream-not-ready vs gateway-timeout-on-cold-function), not conflated.",
        "cvat269_* rehearsal stack observed running alongside production; left untouched.",
    ],
    "claims_established_this_wave": [
        "cvat_2_24_traefik_healthy_post_warmup (about=2.24.0, http=200, sub-400ms)",
        "boot_warmup_502_pattern_documented_with_raw_traefik_log_evidence",
    ],
    "claims_not_established": [
        "doctor_all_green",
        "autonomous_certified_gold",
        "champions>0",
    ],
    "no_open_human_stop_states": True,
    "no_volume_wipe": True,
    "destructive_ops": "none",
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
