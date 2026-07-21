"""STATIC inactive-path gates for body_parts_v2.

Strengthens inactive authority identity, migration refusal of production/gold
claims, and CVAT pilot readiness checks that are code/fixture-only. Never grants
production activation and never substitutes Kevin pilot sources.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .ontology_v2 import DEFAULT_ONTOLOGY_V2, build_ontology_v2, load_v2_proposal

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "ontology_v2_inactive_path_static_only_no_production_activation"
ARTIFACT_TYPE = "ontology_v2_inactive_path_gate_report"
SCHEMA_VERSION = "1.0.0"
INACTIVE_STATUS = "approved_design_not_active"
ACTIVE_RUNTIME_ONTOLOGY = "body_parts_v1"
V2_ONTOLOGY = "body_parts_v2"

PILOT_IMAGE_MIN = 20
PILOT_IMAGE_MAX = 30
REQUIRED_PILOT_STATES = (
    "visible",
    "partially_visible",
    "occluded",
    "occluded_by_clothing",
    "cropped_out",
    "not_visible",
    "not_applicable",
    "unreviewed_for_v2",
    "ambiguous_do_not_use",
)
FORBIDDEN_ACTIVATION_TRUE_KEYS = (
    "production_activation_performed",
    "production_activation_granted",
    "production_activation_allowed",
    "production_activation_claimed",
    "v2_champion_claimed",
    "human_anatomy_gold_claimed",
    "pilot_complete",
    "kevin_pilot_sources_authorized",
    "mapping_authority",
)
FORBIDDEN_SOURCE_KINDS_FOR_COMPLETION = frozenset(
    {
        "fixture_matrix_probe",
        "synthetic",
        "synthetic_geometry_exact",
        "fabricated_pilot",
        "unreviewed_warehouse",
    }
)


class OntologyV2InactiveGateError(ValueError):
    """Inactive-path authority, migration, or pilot gate violated."""


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def appended_v2_part_names() -> tuple[str, ...]:
    labels = build_ontology_v2()["labels"]
    return tuple(
        str(label["name"])
        for label in labels
        if isinstance(label, Mapping)
        and label.get("map") == "part"
        and isinstance(label.get("id"), int)
        and 56 <= int(label["id"]) <= 64
    )


def require_inactive_v2_authority(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse any document that claims active/production body_parts_v2 authority."""

    if not isinstance(document, Mapping):
        raise OntologyV2InactiveGateError("inactive authority document missing")
    status = document.get("activation_status") or document.get("status")
    if status != INACTIVE_STATUS:
        raise OntologyV2InactiveGateError(
            "inactive authority requires activation_status=approved_design_not_active"
        )
    ontology = document.get("mask_ontology_version") or document.get("ontology_version")
    if ontology not in {None, V2_ONTOLOGY}:
        raise OntologyV2InactiveGateError(
            f"inactive authority ontology must be {V2_ONTOLOGY} or omitted"
        )
    for key in FORBIDDEN_ACTIVATION_TRUE_KEYS:
        if document.get(key) is True:
            raise OntologyV2InactiveGateError(
                f"inactive authority refuses {key}=true (no production activation)"
            )
    if document.get("active_runtime_ontology") not in {None, ACTIVE_RUNTIME_ONTOLOGY}:
        raise OntologyV2InactiveGateError(
            "inactive authority refuses non-v1 active_runtime_ontology claims"
        )
    return {
        "activation_status": INACTIVE_STATUS,
        "active_runtime_ontology": ACTIVE_RUNTIME_ONTOLOGY,
        "production_activation_performed": False,
        "ontology_version": ontology or V2_ONTOLOGY,
    }


def refuse_migration_production_claims(document: Mapping[str, Any]) -> None:
    """Migration may create inactive review manifests only; never activation/gold."""

    if not isinstance(document, Mapping):
        raise OntologyV2InactiveGateError("migration document missing")
    for key in FORBIDDEN_ACTIVATION_TRUE_KEYS:
        if document.get(key) is True:
            raise OntologyV2InactiveGateError(
                f"migration refused: {key}=true is a production/activation claim"
            )
    migration = document.get("ontology_migration")
    if isinstance(migration, Mapping):
        for key in FORBIDDEN_ACTIVATION_TRUE_KEYS:
            if migration.get(key) is True:
                raise OntologyV2InactiveGateError(
                    f"migration refused: ontology_migration.{key}=true"
                )
        status = migration.get("status")
        if status in {
            "activated",
            "production_active",
            "gold_approved",
            "supervision_eligible",
        }:
            raise OntologyV2InactiveGateError(
                f"migration refused: unsafe ontology_migration.status={status!r}"
            )
        if migration.get("to_ontology") not in {None, V2_ONTOLOGY}:
            raise OntologyV2InactiveGateError(
                "migration refused: to_ontology must be body_parts_v2"
            )
    if document.get("mask_ontology_version") == V2_ONTOLOGY:
        if document.get("workflow_status") in {"approved_gold", "exported", "active"}:
            raise OntologyV2InactiveGateError(
                "migration refused: migrated v2 cannot claim gold/exported/active workflow"
            )
        if document.get("truth_tier") in {
            "human_anchor_gold",
            "autonomous_certified_gold",
            "human_approved_gold",
        }:
            raise OntologyV2InactiveGateError(
                "migration refused: migrated v2 cannot claim gold truth tiers"
            )


def refuse_apply_when_activation_requested(
    *,
    dry_run: bool,
    extras: Mapping[str, Any] | None = None,
) -> None:
    """Hard-refuse migration apply when callers request activation side-effects."""

    payload = extras or {}
    if payload.get("activate_v2") is True or payload.get("production_activation") is True:
        raise OntologyV2InactiveGateError(
            "migration refused: activate_v2/production_activation cannot accompany migration"
        )
    if dry_run is False and payload.get("claim_pilot_complete") is True:
        raise OntologyV2InactiveGateError(
            "migration refused: claim_pilot_complete cannot accompany apply"
        )


def build_cvat_v2_pilot_matrix_contract() -> dict[str, Any]:
    """Return the code/fixture pilot matrix contract (Kevin sources still required)."""

    appended = appended_v2_part_names()
    if len(appended) != 9:
        raise OntologyV2InactiveGateError("pilot matrix requires exactly nine appended PART labels")
    proposal = load_v2_proposal()
    aliases = sorted(str(alias) for alias in proposal.get("aliases", {}))
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "ontology_v2_cvat_pilot_matrix_contract",
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "activation_status": INACTIVE_STATUS,
        "ontology_version": V2_ONTOLOGY,
        "active_runtime_ontology": ACTIVE_RUNTIME_ONTOLOGY,
        "production_activation_performed": False,
        "pilot_complete": False,
        "kevin_pilot_sources_required": True,
        "kevin_pilot_sources_authorized": False,
        "image_count_min": PILOT_IMAGE_MIN,
        "image_count_max": PILOT_IMAGE_MAX,
        "required_states": list(REQUIRED_PILOT_STATES),
        "required_appended_classes": list(appended),
        "aliases_help_only": aliases,
        "fixture_probes_may_exercise_gate": True,
        "fixture_probes_cannot_complete_pilot": True,
        "cvat_project_name": "MaskFactory_body_parts_v2_pilot",
        "ontology_source": "configs/ontology_v2.yaml",
        "ontology_path_exists": DEFAULT_ONTOLOGY_V2.is_file(),
    }
    return {**core, "seal_sha256": _canonical_sha256(core)}


def evaluate_cvat_v2_pilot_readiness(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a pilot distinct-image manifest without inventing Kevin sources.

    Fixture/matrix-probe rows may exercise coverage accounting. Only rows with
    ``source_kind=kevin_governed_pilot`` and explicit Kevin authorization can move
    toward completion, and this STATIC gate never sets ``pilot_complete=true``.
    """

    if not isinstance(manifest, Mapping):
        raise OntologyV2InactiveGateError("pilot readiness manifest missing")
    require_inactive_v2_authority(
        {
            "activation_status": manifest.get("activation_status", INACTIVE_STATUS),
            "ontology_version": manifest.get("ontology_version", V2_ONTOLOGY),
            "production_activation_performed": manifest.get(
                "production_activation_performed", False
            ),
            "production_activation_granted": manifest.get("production_activation_granted", False),
            "pilot_complete": manifest.get("pilot_complete", False),
            "kevin_pilot_sources_authorized": manifest.get("kevin_pilot_sources_authorized", False),
            "mapping_authority": manifest.get("mapping_authority", False),
            "active_runtime_ontology": manifest.get(
                "active_runtime_ontology", ACTIVE_RUNTIME_ONTOLOGY
            ),
        }
    )
    if manifest.get("pilot_complete") is True:
        raise OntologyV2InactiveGateError(
            "STATIC pilot gate refuses pilot_complete=true without Kevin live pilot"
        )
    if manifest.get("kevin_pilot_sources_authorized") is True:
        raise OntologyV2InactiveGateError(
            "STATIC pilot gate refuses kevin_pilot_sources_authorized=true "
            "(Kevin must authorize real pilot sources out-of-band)"
        )

    images = manifest.get("images")
    if not isinstance(images, Sequence) or isinstance(images, (str, bytes)):
        raise OntologyV2InactiveGateError("pilot readiness images must be a list")

    contract = build_cvat_v2_pilot_matrix_contract()
    required_states = set(contract["required_states"])
    required_classes = set(contract["required_appended_classes"])
    seen_ids: set[str] = set()
    covered_states: set[str] = set()
    covered_classes: set[str] = set()
    kevin_rows = 0
    fixture_rows = 0

    for row in images:
        if not isinstance(row, Mapping):
            raise OntologyV2InactiveGateError("pilot image row must be an object")
        image_id = row.get("image_id")
        if not isinstance(image_id, str) or not image_id.strip():
            raise OntologyV2InactiveGateError("pilot image_id missing")
        if image_id in seen_ids:
            raise OntologyV2InactiveGateError(f"duplicate pilot image_id: {image_id}")
        seen_ids.add(image_id)
        source_kind = row.get("source_kind")
        if not isinstance(source_kind, str) or not source_kind.strip():
            raise OntologyV2InactiveGateError(f"pilot source_kind missing for {image_id}")
        if source_kind == "kevin_governed_pilot":
            kevin_rows += 1
        elif (
            source_kind in FORBIDDEN_SOURCE_KINDS_FOR_COMPLETION
            or source_kind == "fixture_matrix_probe"
        ):
            fixture_rows += 1
        else:
            raise OntologyV2InactiveGateError(
                f"unknown pilot source_kind for {image_id}: {source_kind!r}"
            )
        states = row.get("states_covered")
        if not isinstance(states, Sequence) or isinstance(states, (str, bytes)) or not states:
            raise OntologyV2InactiveGateError(f"states_covered missing for {image_id}")
        for state in states:
            if state not in required_states:
                raise OntologyV2InactiveGateError(
                    f"non-canonical pilot state for {image_id}: {state!r}"
                )
            covered_states.add(str(state))
        classes = row.get("appended_classes_covered") or ()
        if not isinstance(classes, Sequence) or isinstance(classes, (str, bytes)):
            raise OntologyV2InactiveGateError(f"appended_classes_covered invalid for {image_id}")
        for name in classes:
            if name not in required_classes:
                raise OntologyV2InactiveGateError(
                    f"unknown appended class for {image_id}: {name!r}"
                )
            covered_classes.add(str(name))
        if row.get("alias_exported_as_canonical") is True:
            raise OntologyV2InactiveGateError(
                f"pilot row refuses alias_exported_as_canonical for {image_id}"
            )

    distinct = len(seen_ids)
    missing_states = sorted(required_states - covered_states)
    missing_classes = sorted(required_classes - covered_classes)
    count_in_range = PILOT_IMAGE_MIN <= distinct <= PILOT_IMAGE_MAX
    matrix_structurally_ready = not missing_states and not missing_classes and count_in_range
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "activation_status": INACTIVE_STATUS,
        "ontology_version": V2_ONTOLOGY,
        "active_runtime_ontology": ACTIVE_RUNTIME_ONTOLOGY,
        "production_activation_performed": False,
        "production_activation_claimed": False,
        # STATIC gate never completes the Kevin pilot; structure may still be ready.
        "pilot_complete": False,
        "completion_eligible": False,
        "kevin_pilot_sources_required": True,
        "kevin_pilot_sources_authorized": False,
        "matrix_structurally_ready": matrix_structurally_ready,
        "distinct_image_count": distinct,
        "image_count_in_range": count_in_range,
        "kevin_governed_row_count": kevin_rows,
        "fixture_probe_row_count": fixture_rows,
        "covered_states": sorted(covered_states),
        "missing_states": missing_states,
        "covered_appended_classes": sorted(covered_classes),
        "missing_appended_classes": missing_classes,
        "contract_seal_sha256": contract["seal_sha256"],
        "remaining_blocker": (
            "NEEDS KEVIN: supply/authorize governed pilot sources and human-anchor decisions"
        ),
    }
    return {**core, "seal_sha256": _canonical_sha256(core)}


def build_inactive_path_static_report(
    *,
    pilot_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal a STATIC inactive-path report for tracker/OPS evidence."""

    contract = build_cvat_v2_pilot_matrix_contract()
    pilot = evaluate_cvat_v2_pilot_readiness(pilot_manifest) if pilot_manifest is not None else None
    require_inactive_v2_authority(contract)
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "activation_status": INACTIVE_STATUS,
        "active_runtime_ontology": ACTIVE_RUNTIME_ONTOLOGY,
        "production_activation_performed": False,
        "production_activation_claimed": False,
        "inactive_authority_gate": "pass",
        "migration_refusal_gate": "pass",
        "cvat_pilot_fixture_gate": "pass",
        "pilot_matrix_contract_seal_sha256": contract["seal_sha256"],
        "pilot_readiness": pilot,
        "items": ["MF-P1-12.09", "MF-P1-10.05", "MF-P1-11.04", "MF-P1-11.05", "MF-P1-11.06"],
        "honest_non_claims": [
            "body_parts_v2 production activation",
            "Kevin pilot sources authorized",
            "pilot_complete",
            "doctor-green",
            "human_anchor_gold",
        ],
    }
    return {**core, "seal_sha256": _canonical_sha256(core)}


def fixture_pilot_probe_manifest() -> dict[str, Any]:
    """Deterministic fixture-only probe covering the state/class matrix structure."""

    appended = list(appended_v2_part_names())
    images: list[dict[str, Any]] = []
    # 24 distinct fixture probes: cycle states and appended classes.
    for index in range(24):
        state = REQUIRED_PILOT_STATES[index % len(REQUIRED_PILOT_STATES)]
        cls = appended[index % len(appended)]
        images.append(
            {
                "image_id": f"fixture_pilot_probe_{index:02d}",
                "source_kind": "fixture_matrix_probe",
                "states_covered": [state],
                "appended_classes_covered": [cls],
                "alias_exported_as_canonical": False,
            }
        )
    return {
        "activation_status": INACTIVE_STATUS,
        "ontology_version": V2_ONTOLOGY,
        "active_runtime_ontology": ACTIVE_RUNTIME_ONTOLOGY,
        "production_activation_performed": False,
        "pilot_complete": False,
        "kevin_pilot_sources_authorized": False,
        "mapping_authority": False,
        "images": images,
    }


__all__ = [
    "ACTIVE_RUNTIME_ONTOLOGY",
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "FORBIDDEN_ACTIVATION_TRUE_KEYS",
    "INACTIVE_STATUS",
    "OntologyV2InactiveGateError",
    "PILOT_IMAGE_MAX",
    "PILOT_IMAGE_MIN",
    "PROOF_TIER",
    "REQUIRED_PILOT_STATES",
    "SCHEMA_VERSION",
    "V2_ONTOLOGY",
    "appended_v2_part_names",
    "build_cvat_v2_pilot_matrix_contract",
    "build_inactive_path_static_report",
    "evaluate_cvat_v2_pilot_readiness",
    "fixture_pilot_probe_manifest",
    "refuse_apply_when_activation_requested",
    "refuse_migration_production_claims",
    "require_inactive_v2_authority",
]
