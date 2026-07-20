"""Seal the gold-volume tournament input path map (read-only wiring).

Live-probes MaskedWarehouse / reference / DAZ roots, verifies compose RO mounts,
and records an honest path map. Does NOT run a tournament, mint gold, or
register champions.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from maskfactory.autonomy.gold_volume_paths import (
    DEFAULT_MAP_PATH,
    load_gold_volume_map,
    probe_gold_volume_paths,
)
from maskfactory.serve.docker_contract import probe_docker_serve_contract
from maskfactory.training.docker_contract import probe_docker_train_contract

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "gold_volume_tournament_path_map_20260720.json"
COMPOSE_GPU = REPO / "docker" / "compose.gpu.yml"
COMPOSE_GOLD = REPO / "docker" / "compose.gold-volumes.yml"


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal(evidence: dict) -> dict:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def main() -> int:
    document = load_gold_volume_map(DEFAULT_MAP_PATH)
    probe = probe_gold_volume_paths(DEFAULT_MAP_PATH)
    compose_gold = yaml.safe_load(COMPOSE_GOLD.read_text(encoding="utf-8"))
    train_contract = probe_docker_train_contract()
    serve_contract = probe_docker_serve_contract()

    expected_mounts = [
        "C:/Comfy_UI_Main/MaskedWarehouse:/gold/maskedwarehouse:ro",
        "F:/Reference_Images:/gold/reference:ro",
        "F:/DAZ:/gold/daz:ro",
    ]
    compose_wiring = {}
    for service_name in ("maskfactory-train", "maskfactory-serve"):
        service = compose_gold["services"][service_name]
        volumes = list(service.get("volumes") or [])
        env = dict(service.get("environment") or {})
        compose_wiring[service_name] = {
            "ro_mounts_present": all(m in volumes for m in expected_mounts),
            "volumes": volumes,
            "gold_env": {
                key: env.get(key)
                for key in (
                    "MASKFACTORY_GOLD_VOLUME_MAP",
                    "MASKFACTORY_GOLD_MASKEDWAREHOUSE",
                    "MASKFACTORY_GOLD_REFERENCE",
                    "MASKFACTORY_GOLD_DAZ",
                )
            },
        }

    evidence = {
        "artifact_type": "gold_volume_tournament_path_map",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "authority": "gold_volume_tournament_input_path_map_read_only",
        "git_head_at_authoring": _git_head(),
        "branch": "codex/maskfactory-runtime-implementation",
        "map_config": {
            "path": "configs/gold_volume_tournament_inputs.yaml",
            "sha256": _sha_file(DEFAULT_MAP_PATH),
            "map_id": document.get("map_id"),
            "access_mode": document.get("access_mode"),
        },
        "paths_found": {
            "maskedwarehouse_host": document["volumes"]["maskedwarehouse"]["host_root"],
            "maskedwarehouse_datasets": document["volumes"]["maskedwarehouse"]["datasets"],
            "reference_host": document["volumes"]["reference"]["host_root"],
            "reference_output_root": document["volumes"]["reference"]["output_root"],
            "reference_database": document["volumes"]["reference"]["database"],
            "daz_host": document["volumes"]["daz"]["host_root"],
            "daz_root_uuid": document["volumes"]["daz"]["root_uuid"],
            "daz_volume_unique_id": document["volumes"]["daz"]["volume_unique_id"],
            "daz_tournament_subroots": document["volumes"]["daz"]["tournament_subroots"],
            "container_roots": {
                "maskedwarehouse": "/gold/maskedwarehouse",
                "reference": "/gold/reference",
                "daz": "/gold/daz",
            },
        },
        "live_probe": probe,
        "compose_wiring": {
            "compose_gpu_ref": "docker/compose.gpu.yml",
            "compose_gpu_sha256": _sha_file(COMPOSE_GPU),
            "compose_gold_overlay_ref": "docker/compose.gold-volumes.yml",
            "compose_gold_overlay_sha256": _sha_file(COMPOSE_GOLD),
            "compose_usage": (
                "docker compose -f docker/compose.gpu.yml "
                "-f docker/compose.gold-volumes.yml run --rm maskfactory-train"
            ),
            "expected_ro_mounts": expected_mounts,
            "services": compose_wiring,
            "all_services_ro_wired": all(
                row["ro_mounts_present"] for row in compose_wiring.values()
            ),
        },
        "docker_contracts": {
            "train_ready": train_contract.ready,
            "train_issues": list(train_contract.issues),
            "serve_ready": serve_contract.ready,
            "serve_issues": list(serve_contract.issues),
            "note": "STATIC contracts evaluate compose.gpu.yml alone; gold mounts live in the overlay.",
        },
        "honesty_boundary": {
            "read_only_inputs_only": True,
            "no_writes_into_gold_volume_roots": True,
            "no_tournament_executed": True,
            "no_machine_verified_candidate_fabricated": True,
            "no_gold_claimed": True,
            "no_champions_force_registered": True,
            "daz_not_real_gold": True,
            "external_labels_not_gold": True,
        },
        "claims_not_established": [
            "autonomous_certified_gold",
            "machine_verified_candidate_sidecars_in_runs",
            "champions>0",
            "doctor_all_green",
            "PRODUCTION_EVIDENCE_PASS",
            "multi_provider_tournament_pass",
        ],
        "next_agent_step": (
            "With Docker-GPU + >=3 independent mask families available, run the "
            "multi-provider tournament using these RO /gold/* mounts (or host roots) "
            "to emit real machine_verified_candidate sidecars under runs/, freeze an "
            "image-disjoint corpus, then build_autonomous_gold_admission --corpus."
        ),
    }
    sealed = _seal(evidence)
    OUT.write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUT)
    print("self_sha256", sealed["self_sha256"])
    print("required_roots_present", sealed["live_probe"]["required_roots_present"])
    print("compose_ro_wired", sealed["compose_wiring"]["all_services_ro_wired"])
    return 0 if sealed["live_probe"]["required_roots_present"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
