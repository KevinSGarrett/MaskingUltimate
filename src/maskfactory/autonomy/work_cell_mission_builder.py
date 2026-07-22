"""Build sealed RunPod autonomous work-cell mission artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from .work_cell import STAGES, seal_manifest, validate_mission_manifest
from .work_cell_command_handlers import command_binding_sha256

SCHEMA_ROOT = Path(__file__).parents[1] / "schemas"


class MissionBuilderError(RuntimeError):
    """Mission artifacts are incomplete, drifted, or unsafe to emit."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_bulk_policy() -> dict[str, Any]:
    return {
        "workload_scope": [
            "source_decode",
            "person_ownership",
            "mask_generation",
            "deterministic_hard_qa",
            "strict_visual_review",
            "bounded_repair",
            "mask_correction",
            "package_freeze",
            "certification",
            "milestone_reporting",
        ],
        "reporting_mode": "milestone_only",
        "suppress_per_record_chat": True,
        "require_no_routine_human_review": True,
        "allow_optional_exception_queue": True,
        "self_hosted_llm_bulk_review": True,
        "material_incident_threshold_fraction": 0.1,
        "terminal_outcomes": ["accepted", "abstained", "quarantined", "rejected"],
    }


def normalize_handler_specs(
    handlers: Mapping[str, Mapping[str, Any]], *, base: Path
) -> dict[str, dict[str, Any]]:
    missing = sorted(set(STAGES) - set(handlers))
    extra = sorted(set(handlers) - set(STAGES))
    if missing or extra:
        raise MissionBuilderError(f"handler coverage invalid: missing={missing} extra={extra}")
    normalized: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        spec = dict(handlers[stage])
        kind = spec.get("kind")
        if kind == "python_callable":
            source = Path(str(spec["source_path"]))
            if not source.is_absolute():
                source = base / source
            spec["implementation_sha256"] = file_sha256(source)
        elif kind == "subprocess_json":
            spec.pop("implementation_sha256", None)
            binding_files = []
            for row in spec.get("binding_files") or ():
                binding = dict(row)
                source = Path(str(binding["path"]))
                if not source.is_absolute():
                    source = base / source
                binding["sha256"] = file_sha256(source)
                binding_files.append(binding)
            if binding_files:
                spec["binding_files"] = binding_files
            spec["implementation_sha256"] = command_binding_sha256(spec)
        else:
            raise MissionBuilderError(f"handler kind invalid: {stage}")
        normalized[stage] = spec
    schema = json.loads((SCHEMA_ROOT / "runpod_work_cell_handlers.schema.json").read_text())
    document = {
        "schema_version": "maskfactory.runpod_work_cell_handlers.v1",
        "handlers": normalized,
    }
    problems = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if problems:
        pointer = "/".join(str(part) for part in problems[0].path)
        raise MissionBuilderError(
            f"handler manifest schema invalid at {pointer or '<root>'}: {problems[0].message}"
        )
    return normalized


def build_mission_artifacts(
    *,
    mission_id: str,
    input_manifest_path: Path,
    records: Sequence[Mapping[str, Any]],
    shard_count: int,
    bindings: Mapping[str, Any],
    provider_bindings: Sequence[Mapping[str, Any]],
    role_bindings: Mapping[str, Any],
    handlers: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
    authority_ceiling: str = "machine_verified_candidate",
    allowed_output_prefix: str | None = None,
    repair_policy: Mapping[str, Any] | None = None,
    execution: Mapping[str, Any] | None = None,
    bulk_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not records:
        raise MissionBuilderError("records required")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    handler_document = {
        "schema_version": "maskfactory.runpod_work_cell_handlers.v1",
        "handlers": normalize_handler_specs(handlers, base=output),
    }
    stage_versions = {
        stage: handler_document["handlers"][stage]["implementation_sha256"] for stage in STAGES
    }
    manifest = seal_manifest(
        {
            "schema_version": "maskfactory.runpod_autonomous_mission.v1",
            "mission_id": mission_id,
            "input": {
                "manifest_path": str(input_manifest_path),
                "manifest_sha256": file_sha256(input_manifest_path),
                "record_count": len(records),
                "shard_count": shard_count,
            },
            "bindings": dict(bindings),
            "provider_bindings": [dict(row) for row in provider_bindings],
            "stage_versions": stage_versions,
            "role_bindings": dict(role_bindings),
            "repair_policy": dict(
                repair_policy
                or {
                    "max_attempts": 2,
                    "max_changed_pixel_fraction": 0.2,
                    "max_elapsed_seconds": 300,
                    "allowed_operations": ["box_refine", "point_refine", "mask_prompt_refine"],
                }
            ),
            "bulk_policy": dict(bulk_policy or default_bulk_policy()),
            "execution": dict(
                execution
                or {
                    "lease_seconds": 300,
                    "max_record_attempts": 3,
                    "checkpoint_records": 256,
                    "milestone_records": 1000,
                }
            ),
            "authority_ceiling": authority_ceiling,
            "allowed_output_prefix": allowed_output_prefix or f"missions/{mission_id}",
        }
    )
    validate_mission_manifest(manifest)
    records_document = [dict(record) for record in records]
    written = {
        "mission": output / "mission.json",
        "records": output / "records.json",
        "handlers": output / "handlers.json",
    }
    for path, document in (
        (written["mission"], manifest),
        (written["records"], records_document),
        (written["handlers"], handler_document),
    ):
        if path.exists():
            raise MissionBuilderError(f"artifact already exists: {path}")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    return {
        "mission_path": str(written["mission"]),
        "records_path": str(written["records"]),
        "handlers_path": str(written["handlers"]),
        "mission_sha256": file_sha256(written["mission"]),
        "records_sha256": file_sha256(written["records"]),
        "handlers_sha256": file_sha256(written["handlers"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "record_count": len(records),
        "stage_versions": stage_versions,
    }
