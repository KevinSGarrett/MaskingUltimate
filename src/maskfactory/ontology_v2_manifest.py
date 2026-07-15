"""Inactive body_parts_v2 manifest schema, migration, and supervision gates."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .ontology_v2 import DEFAULT_PROPOSAL, build_ontology_v2, load_v2_proposal
from .validation import validate_document

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_V1 = ROOT / "src" / "maskfactory" / "schemas" / "manifest.schema.json"
DEFAULT_SCHEMA_V2 = ROOT / "src" / "maskfactory" / "schemas" / "manifest_v2.schema.json"

V2_VISIBLE_STATES = frozenset({"visible", "partially_visible"})
V2_NULL_MASK_STATES = frozenset(
    {
        "occluded_by_clothing",
        "cropped_out",
        "not_visible",
        "not_applicable",
        "unreviewed_for_v2",
    }
)
V2_REVIEW_STATES = frozenset(
    {
        *V2_VISIBLE_STATES,
        "occluded",
        *V2_NULL_MASK_STATES,
        "ambiguous_do_not_use",
    }
)


class OntologyV2ManifestError(ValueError):
    """Raised when v2 migration, review state, or supervision authority is unsafe."""


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OntologyV2ManifestError(f"cannot load {description} {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise OntologyV2ManifestError(f"{description} root must be an object")
    return document


def build_manifest_v2_schema(path: Path | str = DEFAULT_SCHEMA_V1) -> dict[str, Any]:
    schema = deepcopy(_load_json(Path(path), "v1 manifest schema"))
    schema["$id"] = "https://maskfactory.local/schemas/manifest_v2.schema.json"
    schema["title"] = "MaskFactory body_parts_v2 per-instance package manifest"
    schema["description"] = (
        "Inactive v2 manifest authority from doc 18; production remains v1 until activation."
    )
    schema["required"].extend(["reviewed_ontology_version", "ontology_migration"])
    schema["properties"]["schema_version"] = {"const": "2.0.0"}
    schema["properties"]["mask_ontology_version"] = {"const": "body_parts_v2"}
    schema["properties"]["reviewed_ontology_version"] = {"enum": ["body_parts_v1", "body_parts_v2"]}
    schema["properties"]["ontology_migration"] = {"$ref": "#/$defs/ontologyMigration"}

    visibility = schema["$defs"]["visibility"]["enum"]
    for state in ("occluded_by_clothing", "not_applicable", "unreviewed_for_v2"):
        if state not in visibility:
            visibility.append(state)
    statuses = schema["$defs"]["partStatus"]["enum"]
    statuses.append("unreviewed_for_v2")

    schema["$defs"]["reviewAuthority"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviewed", "reviewer", "reviewed_at", "source", "ontology_version"],
        "properties": {
            "reviewed": {"type": "boolean"},
            "reviewer": {"type": ["string", "null"]},
            "reviewed_at": {"oneOf": [{"$ref": "#/$defs/timestamp"}, {"type": "null"}]},
            "source": {
                "enum": [
                    "legacy_v1_human_review",
                    "legacy_v1_unreviewed",
                    "migrated_unreviewed",
                    "human_review",
                    "autonomous_certification",
                    "weighted_pseudo_label",
                    "n/a",
                ]
            },
            "ontology_version": {"enum": ["body_parts_v1", "body_parts_v2"]},
        },
    }
    schema["$defs"]["ontologyMigration"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "migration_id",
            "from_ontology",
            "to_ontology",
            "source_manifest_sha256",
            "delta_sha256",
            "previous_workflow_status",
            "added_labels",
            "status",
        ],
        "properties": {
            "schema_version": {"const": "1.0.0"},
            "migration_id": {"type": "string", "pattern": "^v1v2_[a-f0-9]{16}$"},
            "from_ontology": {"const": "body_parts_v1"},
            "to_ontology": {"const": "body_parts_v2"},
            "source_manifest_sha256": {"$ref": "#/$defs/sha256"},
            "delta_sha256": {"$ref": "#/$defs/sha256"},
            "previous_workflow_status": {"type": ["string", "null"]},
            "added_labels": {
                "type": "array",
                "minItems": 9,
                "maxItems": 9,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/labelName"},
            },
            "status": {"const": "awaiting_v2_human_review"},
        },
    }

    part_entry = schema["$defs"]["partEntry"]
    part_entry["required"].append("review_authority")
    part_entry["properties"]["review_authority"] = {"$ref": "#/$defs/reviewAuthority"}
    part_entry["properties"]["ambiguity_file"] = {
        "oneOf": [{"$ref": "#/$defs/relativePath"}, {"type": "null"}]
    }
    part_entry["properties"]["ambiguity_sha256"] = {
        "oneOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]
    }
    part_entry["allOf"] = [
        {
            "if": {
                "properties": {
                    "mask_type": {"const": "atomic_exclusive"},
                    "visibility": {"enum": sorted(V2_VISIBLE_STATES)},
                },
                "required": ["mask_type", "visibility"],
            },
            "then": {
                "required": ["mask_sha256", "mask_area_px"],
                "properties": {
                    "mask_file": {"$ref": "#/$defs/relativePath"},
                    "mask_sha256": {"$ref": "#/$defs/sha256"},
                    "mask_area_px": {"type": "integer", "minimum": 1},
                },
            },
        },
        {
            "if": {
                "properties": {
                    "mask_type": {"const": "atomic_exclusive"},
                    "visibility": {"enum": sorted(V2_NULL_MASK_STATES)},
                },
                "required": ["mask_type", "visibility"],
            },
            "then": {
                "properties": {
                    "mask_file": {"type": "null"},
                    "mask_sha256": {"type": "null"},
                    "mask_area_px": {"type": ["integer", "null"], "maximum": 0},
                    "mask_bbox": {"type": "null"},
                    "components": {"type": ["integer", "null"], "maximum": 0},
                }
            },
        },
        {
            "if": {
                "properties": {
                    "mask_type": {"const": "atomic_exclusive"},
                    "visibility": {"const": "ambiguous_do_not_use"},
                },
                "required": ["mask_type", "visibility"],
            },
            "then": {
                "required": ["ambiguity_file", "ambiguity_sha256"],
                "properties": {
                    "mask_file": {"type": "null"},
                    "ambiguity_file": {"$ref": "#/$defs/relativePath"},
                    "ambiguity_sha256": {"$ref": "#/$defs/sha256"},
                },
            },
        },
        {
            "if": {
                "properties": {
                    "mask_type": {"const": "atomic_exclusive"},
                    "visibility": {"const": "unreviewed_for_v2"},
                },
                "required": ["mask_type", "visibility"],
            },
            "then": {
                "properties": {
                    "status": {"const": "unreviewed_for_v2"},
                    "review_authority": {
                        "properties": {
                            "reviewed": {"const": False},
                            "source": {"const": "migrated_unreviewed"},
                            "ontology_version": {"const": "body_parts_v2"},
                        }
                    },
                }
            },
        },
        {
            "if": {
                "properties": {
                    "mask_type": {"const": "atomic_exclusive"},
                    "visibility": {"const": "not_applicable"},
                },
                "required": ["mask_type", "visibility"],
            },
            "then": {
                "properties": {
                    "review_authority": {
                        "properties": {
                            "reviewed": {"const": True},
                            "source": {
                                "enum": [
                                    "human_review",
                                    "autonomous_certification",
                                    "weighted_pseudo_label",
                                ]
                            },
                            "ontology_version": {"const": "body_parts_v2"},
                        }
                    }
                }
            },
        },
    ]
    schema.setdefault("allOf", []).append(
        {
            "if": {
                "properties": {"workflow_status": {"enum": ["approved_gold", "exported"]}},
                "required": ["workflow_status"],
            },
            "then": {
                "properties": {
                    "reviewed_ontology_version": {"const": "body_parts_v2"},
                }
            },
        }
    )
    return schema


def render_manifest_v2_schema() -> str:
    return json.dumps(build_manifest_v2_schema(), indent=2, sort_keys=True) + "\n"


def generate_manifest_v2_schema(path: Path | str = DEFAULT_SCHEMA_V2) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_manifest_v2_schema(), encoding="utf-8")
    return output


def manifest_v2_schema_is_current(path: Path | str = DEFAULT_SCHEMA_V2) -> bool:
    output = Path(path)
    return output.is_file() and output.read_text(encoding="utf-8") == render_manifest_v2_schema()


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _delta_sha256() -> str:
    return hashlib.sha256(DEFAULT_PROPOSAL.read_bytes()).hexdigest()


def _part_labels() -> tuple[dict[str, Any], ...]:
    return tuple(label for label in build_ontology_v2()["labels"] if label["map"] == "part")


def migrate_v1_manifest_document(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return an idempotent v2 review manifest without changing any pixel/file authority."""
    if not isinstance(manifest, Mapping):
        raise OntologyV2ManifestError("manifest must be an object")
    if manifest.get("mask_ontology_version") == "body_parts_v2":
        existing = deepcopy(dict(manifest))
        require_valid_v2_manifest(existing)
        return existing
    if manifest.get("mask_ontology_version") != "body_parts_v1":
        raise OntologyV2ManifestError("migration source must be body_parts_v1")
    structural = validate_document(manifest, "manifest")
    if structural:
        raise OntologyV2ManifestError(
            "v1 manifest fails schema: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in structural)
        )
    parts = manifest.get("parts")
    if not isinstance(parts, Mapping):
        raise OntologyV2ManifestError("v1 manifest parts must be an object")
    part_labels = _part_labels()
    v1_labels = part_labels[:56]
    additions = part_labels[56:]
    missing_enabled_v1 = [
        label["name"] for label in v1_labels if label["enabled"] and label["name"] not in parts
    ]
    missing_disabled_v1 = [
        label for label in v1_labels if not label["enabled"] and label["name"] not in parts
    ]
    if missing_enabled_v1:
        raise OntologyV2ManifestError(
            "v1 manifest is missing enabled PART entries: " + ", ".join(missing_enabled_v1)
        )
    collisions = [label["name"] for label in additions if label["name"] in parts]
    if collisions:
        raise OntologyV2ManifestError("v2 append-only label collision: " + ", ".join(collisions))

    source = deepcopy(dict(manifest))
    result = deepcopy(source)
    source_sha = _canonical_sha256(source)
    previous_workflow = source.get("workflow_status")
    review = source.get("review")
    legacy_reviewed = previous_workflow in {"approved_gold", "exported"}
    reviewer = review.get("reviewer") if legacy_reviewed and isinstance(review, Mapping) else None
    reviewed_at = (
        review.get("approved_at") if legacy_reviewed and isinstance(review, Mapping) else None
    )
    for entry in result["parts"].values():
        if not isinstance(entry, dict):
            raise OntologyV2ManifestError("every v1 part entry must be an object")
        entry["review_authority"] = {
            "reviewed": legacy_reviewed,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "source": "legacy_v1_human_review" if legacy_reviewed else "legacy_v1_unreviewed",
            "ontology_version": "body_parts_v1",
        }
    for label in missing_disabled_v1:
        result["parts"][label["name"]] = {
            "mask_type": label["mask_type"],
            "visibility": "n/a",
            "mask_file": None,
            "mask_sha256": None,
            "mask_area_px": 0,
            "mask_bbox": None,
            "components": 0,
            "status": "n/a",
            "review_authority": {
                "reviewed": False,
                "reviewer": None,
                "reviewed_at": None,
                "source": "n/a",
                "ontology_version": "body_parts_v1",
            },
            "notes": "disabled v1 label absent from source package; no review authority inferred",
        }
    for label in additions:
        result["parts"][label["name"]] = {
            "mask_type": "atomic_exclusive",
            "visibility": "unreviewed_for_v2",
            "mask_file": None,
            "mask_sha256": None,
            "mask_area_px": 0,
            "mask_bbox": None,
            "components": 0,
            "status": "unreviewed_for_v2",
            "review_authority": {
                "reviewed": False,
                "reviewer": None,
                "reviewed_at": None,
                "source": "migrated_unreviewed",
                "ontology_version": "body_parts_v2",
            },
            "notes": "migrated append-only label; human v2 review required",
        }
    result["schema_version"] = "2.0.0"
    result["mask_ontology_version"] = "body_parts_v2"
    result["reviewed_ontology_version"] = "body_parts_v1"
    result["workflow_status"] = "in_review"
    result["ontology_migration"] = {
        "schema_version": "1.0.0",
        "migration_id": f"v1v2_{source_sha[:16]}",
        "from_ontology": "body_parts_v1",
        "to_ontology": "body_parts_v2",
        "source_manifest_sha256": source_sha,
        "delta_sha256": _delta_sha256(),
        "previous_workflow_status": previous_workflow,
        "added_labels": [label["name"] for label in additions],
        "status": "awaiting_v2_human_review",
    }
    if result.get("files") != source.get("files"):
        raise OntologyV2ManifestError("migration changed the authoritative files map")
    require_valid_v2_manifest(result)
    return result


def v2_manifest_issues(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []
    structural = validate_document(manifest, "manifest_v2")
    issues.extend(
        f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in structural
    )
    if manifest.get("mask_ontology_version") != "body_parts_v2":
        return tuple(sorted(set(issues)))
    parts = manifest.get("parts")
    if not isinstance(parts, Mapping):
        return tuple(sorted(set(issues)))
    proposal = load_v2_proposal()
    aliases = set(proposal["aliases"])
    for alias in sorted(aliases & set(parts)):
        issues.append(f"/parts/{alias} alias names cannot persist in v2 manifests")
    for label in proposal["labels"]:
        name = label["name"]
        entry = parts.get(name)
        if not isinstance(entry, Mapping):
            issues.append(f"/parts/{name} missing appended v2 label")
            continue
        state = entry.get("visibility")
        if state not in V2_REVIEW_STATES:
            issues.append(f"/parts/{name}/visibility unknown v2 review state")
            continue
        mask_file = entry.get("mask_file")
        mask_sha = entry.get("mask_sha256")
        area = entry.get("mask_area_px")
        if state in V2_VISIBLE_STATES and (
            not isinstance(mask_file, str)
            or not isinstance(mask_sha, str)
            or not isinstance(area, int)
            or area < 1
        ):
            issues.append(f"/parts/{name} visible state requires nonempty mask authority")
        if state in V2_NULL_MASK_STATES and (
            mask_file is not None or mask_sha is not None or area not in {None, 0}
        ):
            issues.append(f"/parts/{name} null-mask state contains mask authority")
        if state == "ambiguous_do_not_use" and (
            mask_file is not None
            or not isinstance(entry.get("ambiguity_file"), str)
            or not isinstance(entry.get("ambiguity_sha256"), str)
        ):
            issues.append(f"/parts/{name} ambiguity state lacks separate ignore authority")
        ambiguity_file = entry.get("ambiguity_file")
        ambiguity_sha = entry.get("ambiguity_sha256")
        authority = entry.get("review_authority")
        if not isinstance(authority, Mapping) or type(authority.get("reviewed")) is not bool:
            issues.append(f"/parts/{name}/review_authority invalid review authority")
        elif state == "unreviewed_for_v2" and (
            authority.get("reviewed") is not False
            or authority.get("source") != "migrated_unreviewed"
        ):
            issues.append(f"/parts/{name}/review_authority unreviewed state was promoted")
        elif state == "not_applicable" and (
            authority.get("reviewed") is not True
            or authority.get("source") != "human_review"
            or authority.get("ontology_version") != "body_parts_v2"
        ):
            issues.append(f"/parts/{name}/review_authority not_applicable lacks human evidence")
        files = manifest.get("files")
        if isinstance(mask_file, str) and (
            not isinstance(files, Mapping) or files.get(mask_file) != mask_sha
        ):
            issues.append(f"/parts/{name}/mask_file mask is absent from files hash authority")
        if isinstance(ambiguity_file, str) and (
            not isinstance(files, Mapping) or files.get(ambiguity_file) != ambiguity_sha
        ):
            issues.append(
                f"/parts/{name}/ambiguity_file ignore mask is absent from files hash authority"
            )
    return tuple(sorted(set(issues)))


def require_valid_v2_manifest(manifest: Mapping[str, Any]) -> None:
    issues = v2_manifest_issues(manifest)
    if issues:
        raise OntologyV2ManifestError("; ".join(issues))


def v2_supervision_ineligibility(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    reasons = list(v2_manifest_issues(manifest))
    tier = manifest.get("truth_tier", "human_anchor_gold")
    if tier not in {
        "human_anchor_gold",
        "autonomous_certified_gold",
        "weighted_pseudo_label",
    }:
        reasons.append("truth tier is not supervision eligible")
    if manifest.get("reviewed_ontology_version") != "body_parts_v2":
        reasons.append("reviewed_ontology_version is not body_parts_v2")
    allowed_workflows = {
        "human_anchor_gold": {"approved_gold", "exported"},
        "autonomous_certified_gold": {"autonomous_certified", "exported"},
        "weighted_pseudo_label": {"weighted_pseudo", "exported"},
    }.get(str(tier), set())
    if manifest.get("workflow_status") not in allowed_workflows:
        reasons.append("workflow does not match the explicit truth tier")
    qa = manifest.get("qa")
    if not isinstance(qa, Mapping) or qa.get("qa_overall") != "pass":
        reasons.append("QA is not pass")
    if tier == "human_anchor_gold":
        review = manifest.get("review")
        if not isinstance(review, Mapping) or any(
            review.get(field) is None for field in ("reviewer", "approved_at", "review_time_sec")
        ):
            reasons.append("human review block is incomplete")
    parts = manifest.get("parts")
    expected_parts = {label["name"] for label in _part_labels()}
    if not isinstance(parts, Mapping):
        reasons.append("parts authority is missing")
        return tuple(sorted(set(reasons)))
    missing = sorted(expected_parts - set(parts))
    if missing:
        reasons.append("missing v2 PART entries: " + ", ".join(missing))
    for name in sorted(expected_parts & set(parts)):
        entry = parts[name]
        if not isinstance(entry, Mapping):
            reasons.append(f"{name} entry is invalid")
            continue
        authority = entry.get("review_authority")
        expected_source = {
            "human_anchor_gold": "human_review",
            "autonomous_certified_gold": "autonomous_certification",
            "weighted_pseudo_label": "weighted_pseudo_label",
        }.get(str(tier))
        if not isinstance(authority, Mapping) or (
            authority.get("reviewed") is not True
            or authority.get("source") != expected_source
            or authority.get("ontology_version") != "body_parts_v2"
            or tier == "human_anchor_gold"
            and (not authority.get("reviewer") or not authority.get("reviewed_at"))
        ):
            reasons.append(f"{name} lacks body_parts_v2 {tier} authority")
        if entry.get("visibility") == "unreviewed_for_v2":
            reasons.append(f"{name} remains unreviewed_for_v2")
        if entry.get("visibility") in V2_VISIBLE_STATES and entry.get("status") not in {
            "human_anchor_gold" if tier == "human_anchor_gold" else str(tier),
            "human_approved_gold" if tier == "human_anchor_gold" else str(tier),
        }:
            reasons.append(f"{name} visible pixels do not match truth tier {tier}")
    return tuple(sorted(set(reasons)))


def require_v2_supervision_eligible(manifest: Mapping[str, Any]) -> None:
    reasons = v2_supervision_ineligibility(manifest)
    if reasons:
        raise OntologyV2ManifestError("v2 supervision refused: " + "; ".join(reasons))


def _serialize(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.v2-migration-tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def plan_v1_to_v2_manifest_migration(manifest_path: Path | str) -> tuple[dict[str, Any], bytes]:
    path = Path(manifest_path).resolve()
    source_bytes = path.read_bytes()
    source = json.loads(source_bytes)
    target = migrate_v1_manifest_document(source)
    target_bytes = _serialize(target)
    report = {
        "schema_version": "1.0.0",
        "operation": "body_parts_v1_to_v2_manifest",
        "manifest": path.name,
        "source_bytes_sha256": _sha256_bytes(source_bytes),
        "target_bytes_sha256": _sha256_bytes(target_bytes),
        "source_canonical_sha256": _canonical_sha256(source),
        "target_canonical_sha256": _canonical_sha256(target),
        "files_map_before_sha256": _canonical_sha256(source.get("files", {})),
        "files_map_after_sha256": _canonical_sha256(target.get("files", {})),
        "added_labels": target["ontology_migration"]["added_labels"],
        "pixel_files_changed": False,
        "collision_check": "pass",
    }
    if report["files_map_before_sha256"] != report["files_map_after_sha256"]:
        raise OntologyV2ManifestError("migration plan changed the files map")
    return report, target_bytes


def migrate_v1_manifest_file(
    manifest_path: Path | str,
    *,
    report_path: Path | str,
    dry_run: bool = True,
) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    report, target_bytes = plan_v1_to_v2_manifest_migration(path)
    source_bytes = path.read_bytes()
    report["mode"] = "dry_run" if dry_run else "apply"
    report["applied"] = False
    report["backup"] = None
    if not dry_run:
        backup = path.with_name(f".{path.name}.body_parts_v1.backup")
        if backup.exists():
            raise OntologyV2ManifestError(f"migration backup already exists: {backup}")
        with backup.open("xb") as handle:
            handle.write(source_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            _atomic_write(path, target_bytes)
            if _sha256_bytes(path.read_bytes()) != report["target_bytes_sha256"]:
                raise OntologyV2ManifestError("applied v2 manifest hash mismatch")
            report["applied"] = True
            report["backup"] = backup.name
            report["backup_sha256"] = _sha256_bytes(source_bytes)
        except BaseException:
            _atomic_write(path, source_bytes)
            backup.unlink(missing_ok=True)
            raise
    report_output = Path(report_path)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(report_output, _serialize(report))
    return report


def rollback_v2_manifest_file(
    manifest_path: Path | str,
    *,
    report_path: Path | str,
) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    report_file = Path(report_path).resolve()
    report = _load_json(report_file, "v2 migration report")
    if report.get("applied") is not True or not isinstance(report.get("backup"), str):
        raise OntologyV2ManifestError("migration report has no applied rollback authority")
    if _sha256_bytes(path.read_bytes()) != report.get("target_bytes_sha256"):
        raise OntologyV2ManifestError(
            "current v2 manifest changed after migration; rollback refused"
        )
    backup = path.with_name(report["backup"])
    backup_bytes = backup.read_bytes()
    if _sha256_bytes(backup_bytes) != report.get("backup_sha256"):
        raise OntologyV2ManifestError("v1 rollback backup hash mismatch")
    _atomic_write(path, backup_bytes)
    if _sha256_bytes(path.read_bytes()) != report.get("source_bytes_sha256"):
        raise OntologyV2ManifestError("v1 rollback restoration hash mismatch")
    report["rolled_back"] = True
    report["rollback_result"] = "exact_source_bytes_restored"
    _atomic_write(report_file, _serialize(report))
    return report
