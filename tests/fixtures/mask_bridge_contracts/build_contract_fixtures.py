"""Deterministically materialize MaskFactory bridge-v1 conformance fixtures.

Run from the repository root.  Private keys are fixed conformance-only seeds and
must never be used by a runtime release.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.validation import (  # noqa: E402
    ADOPTION_COMPATIBILITY_CHECKS,
    ADOPTION_REVALIDATION_TRIGGERS,
    BRIDGE_SCHEMA_NAMES,
    OPERATIONAL_QA_GATES,
    artifact_identity_sha256,
    canonical_document_sha256,
    canonical_json_bytes,
)

HERE = Path(__file__).resolve().parent
SCHEMAS = ROOT / "src/maskfactory/schemas"
BRIDGE_GOVERNANCE = ROOT / "qa/governance/bridge"
COMPLETION = ROOT / "qa/governance/completion"

RELEASE_ID = "mfr_20260717_012345abcdef"
CAPABILITY_ID = "mfcap_0123456789abcdef01234567"
REQUIREMENTS_ID = "mfreq_0123456789abcdef01234567"
SCOPE = "1" * 64
SOURCE_ENCODED = "2" * 64
SOURCE_DECODED = "3" * 64
TRANSFORM_ID = "fixture-transform-v1"
REVOCATION_INDEX = "4" * 64


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


KEY_SPECS = {
    "producer_release": ("MaskFactory", "mf-release-fixture", bytes([1]) * 32),
    "producer_authority": ("MaskFactory", "mf-authority-fixture", bytes([2]) * 32),
    "producer_receipt": ("MaskFactory", "mf-receipt-fixture", bytes([3]) * 32),
    "producer_journal": ("MaskFactory", "mf-journal-fixture", bytes([4]) * 32),
    "consumer_requirements": ("Comfy_UI_Main", "comfy-main-requirements-fixture", bytes([5]) * 32),
    "consumer_request": ("Comfy_UI_Main", "comfy-main-request-fixture", bytes([6]) * 32),
    "consumer_feedback": ("Comfy_UI_Main", "comfy-main-feedback-fixture", bytes([7]) * 32),
    "consumer_qualification": (
        "Comfy_UI_Main",
        "comfy-main-qualification-fixture",
        bytes([8]) * 32,
    ),
    "consumer_adoption": ("Comfy_UI_Main", "comfy-main-adoption-fixture", bytes([9]) * 32),
    "consumer_journal": ("Comfy_UI_Main", "comfy-main-journal-fixture", bytes([10]) * 32),
}


def private_key(role: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(KEY_SPECS[role][2])


def public_bytes(role: str) -> bytes:
    return (
        private_key(role)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def key_set_fields(role: str) -> dict[str, str]:
    authority = KEY_SPECS[role][0]
    prefix = "mf" if authority == "MaskFactory" else "comfy-main"
    return {
        "key_set_id": f"{prefix}-fixture-trust-set",
        "key_set_version": "1.0.0",
        "key_set_sha256": h(f"{authority}:fixture-trust-set:1.0.0"),
    }


def trust_binding(role: str) -> dict[str, Any]:
    fields = key_set_fields(role)
    return {
        **fields,
        "key_role": role,
        "signing_key_id": KEY_SPECS[role][1],
        "signing_public_key_sha256": hashlib.sha256(public_bytes(role)).hexdigest(),
        "rotation_policy_sha256": h(f"{KEY_SPECS[role][0]}:rotation-policy-v1"),
        "revocation_policy_sha256": h(f"{KEY_SPECS[role][0]}:revocation-policy-v1"),
    }


def trust_record(role: str) -> dict[str, Any]:
    authority, key_id, _ = KEY_SPECS[role]
    return {
        "key_id": key_id,
        "public_key_sha256": hashlib.sha256(public_bytes(role)).hexdigest(),
        "roles": [role],
        "usage_scope": "conformance_only",
        "status": "active",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "authority": authority,
        **key_set_fields(role),
    }


TRUSTED_KEYS = {record["key_id"]: record for record in (trust_record(role) for role in KEY_SPECS)}


def sign(document: dict[str, Any], hash_field: str, role: str, excluded: tuple[str, ...]) -> None:
    document[hash_field] = canonical_document_sha256(document, excluded_top_level_fields=excluded)
    digest = bytes.fromhex(document[hash_field])
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": KEY_SPECS[role][1],
        "public_key_base64": base64.b64encode(public_bytes(role)).decode("ascii"),
        "signed_payload_sha256": document[hash_field],
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": base64.b64encode(private_key(role).sign(digest)).decode("ascii"),
    }


def authentication(role: str, nonce: str, issued: str, expires: str) -> dict[str, Any]:
    return {
        "principal_id": f"fixture:{role}",
        "authority": KEY_SPECS[role][0],
        "role": role,
        "nonce": nonce,
        "issued_at": issued,
        "expires_at": expires,
        "replay_window_seconds": 300,
        "credential_material_included": False,
    }


def media_scope() -> dict[str, Any]:
    return {
        "scope_kind": "still_image",
        "sequence_id": "sequence-fixture",
        "shot_id": "shot-fixture",
        "take_id": "take-fixture",
        "source_video_sha256": None,
        "decoded_frame_sha256": None,
        "frame_index": None,
        "pts": None,
        "timebase_numerator": None,
        "timebase_denominator": None,
        "timestamp_ns": None,
        "frame_span": None,
        "neighbor_frames": [],
    }


def source() -> dict[str, Any]:
    return {
        "artifact_id": "source-fixture",
        "encoded_sha256": SOURCE_ENCODED,
        "decoded_pixel_sha256": SOURCE_DECODED,
        "decoder": {
            "decoder_id": "pillow",
            "version": "11.0.0",
            "binary_sha256": h("pillow-binary"),
        },
        "exif_orientation": 1,
        "orientation_applied": True,
        "width": 512,
        "height": 512,
        "channel_layout": "RGB",
        "alpha_mode": "none",
        "bit_depth": 8,
        "dtype": "uint8",
        "color_space": "sRGB",
        "icc_profile_sha256": None,
        "color_transform": {
            "transform_id": "srgb-canonical-v1",
            "transform_sha256": h("srgb-canonical-v1"),
        },
        "frame_extraction": None,
        "coordinate_space": "source_pixel",
    }


def subject() -> dict[str, Any]:
    return {
        "scene_id": "scene-fixture",
        "shot_id": "shot-fixture",
        "take_id": "take-fixture",
        "character_id": "character-fixture",
        "character_revision": "1.0.0",
        "scene_instance_id": "scene-instance-001",
        "canonical_person_id": "person-canonical-001",
        "person_index": 0,
        "provider_person_index": 1,
        "assignment_evidence": {
            "mapping_id": "assignment-fixture",
            "mapping_sha256": h("assignment-fixture"),
            "status": "unambiguous",
            "bbox_sha256": h("bbox-fixture"),
            "skeleton_sha256": None,
            "silhouette_sha256": None,
            "depth_sha256": None,
        },
    }


def owner_self() -> dict[str, Any]:
    person = subject()
    return {
        "owner_kind": "character_instance",
        "entity_id": person["character_id"],
        "scene_instance_id": person["scene_instance_id"],
        "canonical_person_id": person["canonical_person_id"],
        "person_index": person["person_index"],
    }


def owner_other() -> dict[str, Any]:
    return {
        "owner_kind": "character_instance",
        "entity_id": "character-fixture-002",
        "scene_instance_id": "scene-instance-002",
        "canonical_person_id": "person-canonical-002",
        "person_index": 1,
    }


def transform_chain() -> dict[str, Any]:
    step = {
        "sequence": 0,
        "operation": "project",
        "input": {"coordinate_space": "source_pixel", "width": 512, "height": 512},
        "output": {"coordinate_space": "output_pixel", "width": 512, "height": 512},
        "parameters": {
            "parameter_type": "project",
            "matrix_3x3": [1, 0, 0, 0, 1, 0, 0, 0, 1],
            "clip_policy": "clip",
            "rounding": "half_even",
        },
        "inverse_strategy": "exact_inverse",
        "step_sha256": "0" * 64,
    }
    step["step_sha256"] = canonical_document_sha256(
        step, excluded_top_level_fields=("step_sha256",)
    )
    chain = {
        "chain_id": TRANSFORM_ID,
        "chain_sha256": "0" * 64,
        "source": step["input"],
        "output": step["output"],
        "steps": [step],
        "roundtrip_policy": {
            "required": True,
            "maximum_error_px": 0.01,
            "reject_noninvertible": True,
        },
    }
    chain["chain_sha256"] = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    return chain


def authority_binding(certified: bool) -> dict[str, Any]:
    if certified:
        return {
            "authority_state": "certified",
            "issuer_kind": "maskfactory_autonomous",
            "certificate_kind": "exact_serving_route_output",
            "certificate_id": "mfac_aaaaaaaaaaaaaaaaaaaaaaaa",
            "certificate_sha256": "a" * 64,
            "certificate_status": "active",
            "certificate_scope_sha256": SCOPE,
            "certificate_exact_scope_match": True,
            "revocation_checked_at": "2026-07-17T00:00:05Z",
            "revocation_checkpoint_sha256": REVOCATION_INDEX,
        }
    return {
        "authority_state": "draft",
        "issuer_kind": "consumer_advisory",
        "certificate_kind": "none",
        "certificate_id": None,
        "certificate_sha256": None,
        "certificate_status": "none",
        "certificate_scope_sha256": None,
        "certificate_exact_scope_match": False,
        "revocation_checked_at": None,
        "revocation_checkpoint_sha256": None,
    }


def content_summary(area: int = 100) -> dict[str, Any]:
    return {
        "bounds": {"x": 100, "y": 100, "width": 10, "height": 10} if area else None,
        "area_pixels": area,
        "area_ppm": (area * 1_000_000) // (512 * 512),
        "is_empty": area == 0,
    }


def region(
    *,
    region_id: str,
    artifact_id: str,
    label: str,
    owner: Mapping[str, Any],
    mask_type: str,
    artifact_kind: str,
    certified: bool,
    encoded_seed: str,
    decoded_seed: str,
) -> dict[str, Any]:
    chain = transform_chain()
    record = {
        "region_id": region_id,
        "artifact_id": artifact_id,
        "artifact_identity_sha256": "0" * 64,
        "encoded_sha256": h(encoded_seed),
        "decoded_mask_sha256": h(decoded_seed),
        "format": "PNG",
        "channel_layout": "L",
        "dtype": "uint8",
        "allowed_values": "binary_0_255",
        "mask_type": mask_type,
        "artifact_kind": artifact_kind,
        "visibility": "visible",
        "empty_semantics": "forbidden",
        "content_summary": content_summary(),
        "source_decoded_pixel_sha256": SOURCE_DECODED,
        "owner": dict(owner),
        "label": label,
        "coordinate_space": "output_pixel",
        "width": 512,
        "height": 512,
        "transform_chain_sha256": chain["chain_sha256"],
        "transform_step_sequence": 0,
        "required_minimum_authority_state": "certified" if certified else "draft",
        "authority_binding": authority_binding(certified),
    }
    record["artifact_identity_sha256"] = artifact_identity_sha256(record)
    return record


def wire_rows() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "schema_id": f"https://maskfactory.local/schemas/{name}.schema.json",
            "version": "1.0.0",
            "relative_path": f"src/maskfactory/schemas/{name}.schema.json",
            "sha256": raw_sha(SCHEMAS / f"{name}.schema.json"),
        }
        for name in BRIDGE_SCHEMA_NAMES
    ]


def provider_runtime() -> dict[str, Any]:
    return {
        "runtime_kind": "native_venv",
        "runtime_id": "maskfactory-native-fixture",
        "runtime_version": "1.0.0",
        "environment_lock_sha256": h("environment-lock"),
        "interpreter_build_sha256": h("python-3.11.9-build"),
        "venv_manifest_sha256": h("maskfactory-venv"),
        "container_sha256": None,
    }


def build_capability_snapshot() -> dict[str, Any]:
    route_id = "route-fixture"
    stack = {
        "stack_id": "fixture.stack",
        "stack_sha256": h("fixture.stack"),
        "capability_ids": ["mask.package.read", "mask.live.predict", "mask.live.refine"],
        "roles": ["package_reader", "predictor", "refiner"],
        "labels": ["left_hand", "torso"],
        "access_modes": ["mode_a_package_read", "mode_b_live_predict", "mode_b_live_refine"],
        "media_scopes": ["still_image"],
        "model_artifacts": [{"model_id": "fixture-segmenter", "sha256": h("fixture-segmenter")}],
        "workflow": {"workflow_id": "fixture-mask-workflow", "sha256": h("fixture-mask-workflow")},
        "runtime": provider_runtime(),
        "hardware": {
            "hardware_profile_id": "fixture-gpu",
            "hardware_profile_sha256": h("fixture-gpu"),
            "minimum_vram_mb": 4096,
            "minimum_ram_mb": 8192,
            "accelerators": ["cuda"],
        },
        "route_key": {"route_key_id": route_id, "sha256": h(route_id)},
        "performance_profile": {
            "profile_id": "fixture-performance",
            "sha256": h("fixture-performance"),
            "observed_at": "2026-07-17T00:00:00Z",
        },
        "champion_binding": {
            "champion_id": "fixture-champion",
            "champion_sha256": h("fixture-champion"),
            "status": "current",
        },
        "qualification_scope": {
            "scope_sha256": h("fixture-qualified-scope"),
            "labels": ["left_hand", "torso"],
            "contexts": ["solo", "duo"],
            "artifact_kinds": ["atomic_visible", "protected_qa"],
            "max_person_count": 2,
            "max_width": 2048,
            "max_height": 2048,
            "benchmark_certificate_sha256": h("fixture-benchmark-certificate"),
            "valid_until": "2026-12-31T00:00:00Z",
        },
        "lifecycle": "promoted",
        "certificate_ids": ["fixture-benchmark-certificate"],
    }
    snapshot = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_capability_snapshot",
        "snapshot_id": CAPABILITY_ID,
        "release_id": RELEASE_ID,
        "generated_at": "2026-07-17T00:00:00Z",
        "evidence_context": "conformance_fixture",
        "fixture_only": True,
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["snapshot_sha256"],
        },
        "bridge_contract": "maskfactory-comfyui-bridge/1.0",
        "access_modes": ["mode_a_package_read", "mode_b_live_predict", "mode_b_live_refine"],
        "endpoints": [
            {"operation": "health", "method": "GET", "path": "/health", "enabled": True},
            {"operation": "models", "method": "GET", "path": "/models", "enabled": True},
            {"operation": "predict", "method": "POST", "path": "/predict", "enabled": True},
            {"operation": "refine", "method": "POST", "path": "/refine", "enabled": True},
        ],
        "package_formats": ["maskfactory-package/1.0"],
        "ontologies": [
            {
                "version": "body_parts_v1",
                "sha256": h("body_parts_v1"),
                "left_right_convention": "character_perspective",
            }
        ],
        "labels": ["left_hand", "torso"],
        "artifact_kinds": ["atomic_visible", "protected_qa"],
        "coordinate_spaces": ["source_pixel", "normalized_0_1", "crop_pixel", "output_pixel"],
        "transform_operations": ["crop", "resize", "pad", "horizontal_flip", "inverse_project"],
        "limits": {
            "max_person_count": 2,
            "max_source_width": 2048,
            "max_source_height": 2048,
            "max_request_bytes": 10000000,
            "default_timeout_ms": 10000,
        },
        "authority_policy": {
            "mode_a_truth_tiers": [
                "machine_candidate",
                "qa_passed_machine_candidate",
                "operationally_certified_artifact",
            ],
            "uncertified_output_default_authority_state": "draft",
            "access_mode_determines_authority": False,
            "certified_requires_exact_output_certificate": True,
            "draft_can_override_certified": False,
            "producer_owns_truth_escalation": True,
        },
        "authority_crosswalk": {
            mode: {
                "default_authority_state": "draft",
                "maximum_authority_state": "certified",
                "permitted_issuer_kinds": (
                    ["maskfactory_autonomous", "none"]
                    if mode != "mode_a_package_read"
                    else ["maskfactory_autonomous", "human_anchor_optional", "none"]
                ),
                "certified_certificate_kinds": ["exact_serving_route_output"],
                "promotion_eligibility": "certificate_scope_qa_and_lineage_derived",
            }
            for mode in ("mode_a_package_read", "mode_b_live_predict", "mode_b_live_refine")
        },
        "provider_stacks": [stack],
        "availability": {
            "mode_a": "available",
            "mode_b_predict": "available",
            "mode_b_refine": "available",
            "observed_at": "2026-07-17T00:00:00Z",
            "valid_until": "2026-07-18T00:00:00Z",
            "health_evidence_sha256": h("health-fixture"),
            "mode_eligibility": [
                {
                    "access_mode": mode,
                    "eligible": True,
                    "route_ids": [route_id],
                    "certificate_ids": ["fixture-benchmark-certificate"],
                    "reason_codes": ["promoted_live_route"],
                }
                for mode in ("mode_a_package_read", "mode_b_live_predict", "mode_b_live_refine")
            ],
        },
        "snapshot_sha256": "0" * 64,
    }
    snapshot["snapshot_sha256"] = canonical_document_sha256(
        snapshot, excluded_top_level_fields=("snapshot_sha256",)
    )
    return snapshot


def key_set_for_requirements(authority: str, roles: list[str]) -> dict[str, Any]:
    records = [trust_record(role) for role in roles]
    fields = key_set_fields(roles[0])
    return {
        "authority": authority,
        **fields,
        "trusted_keys": [
            {
                key: record[key]
                for key in (
                    "key_id",
                    "public_key_sha256",
                    "roles",
                    "usage_scope",
                    "status",
                    "valid_from",
                    "valid_until",
                )
            }
            for record in records
        ],
        "rotation_policy_id": f"{authority}-rotation-v1",
        "rotation_policy_sha256": h(f"{authority}:rotation-policy-v1"),
        "revocation_policy_id": f"{authority}-revocation-v1",
        "revocation_policy_sha256": h(f"{authority}:revocation-policy-v1"),
    }


def build_consumer_requirements() -> dict[str, Any]:
    requirements = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_consumer_requirements",
        "requirements_id": REQUIREMENTS_ID,
        "consumer": {
            "project": "Comfy_UI_Main",
            "controller_version": "1.0.0",
            "git_commit": "1" * 40,
        },
        "created_at": "2026-07-17T00:00:00Z",
        "authentication": authentication(
            "consumer_requirements",
            "requirements-fixture-nonce-0001",
            "2026-07-16T23:59:59Z",
            "2026-07-17T00:05:00Z",
        ),
        "trust_binding": trust_binding("consumer_requirements"),
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["requirements_sha256", "signature"],
        },
        "bridge_contract": "maskfactory-comfyui-bridge/1.0",
        "accepted_wire_schemas": wire_rows(),
        "required_semantic_invariant_profile": {
            "profile_id": "maskfactory-comfyui-bridge-semantics",
            "profile_version": "1.0.0",
            "sha256": "0" * 64,
            "require_all_validation_layers": True,
        },
        "trusted_signing_key_sets": [
            key_set_for_requirements(
                "MaskFactory",
                ["producer_release", "producer_authority", "producer_receipt", "producer_journal"],
            ),
            key_set_for_requirements(
                "Comfy_UI_Main",
                [
                    "consumer_requirements",
                    "consumer_request",
                    "consumer_feedback",
                    "consumer_qualification",
                    "consumer_adoption",
                    "consumer_journal",
                ],
            ),
        ],
        "required_access_modes": ["mode_a_package_read", "mode_b_live_predict"],
        "required_capabilities": [
            {
                "capability_id": "mask.package.read",
                "access_mode": "mode_a_package_read",
                "labels": ["left_hand"],
                "artifact_kinds": ["atomic_visible"],
                "minimum_authority_state": "qa_passed_noncertified",
            }
        ],
        "optional_capabilities": [
            {
                "capability_id": "mask.live.predict",
                "access_mode": "mode_b_live_predict",
                "labels": ["left_hand"],
                "artifact_kinds": ["atomic_visible"],
                "minimum_authority_state": "certified",
            }
        ],
        "compatibility": {
            "api_contracts": ["maskfactory-api/1.0"],
            "package_formats": ["maskfactory-package/1.0"],
            "ontology_versions": ["body_parts_v1"],
            "node_pack_versions": ["1.0.0"],
        },
        "required_labels": ["left_hand", "torso"],
        "required_artifact_kinds": ["atomic_visible", "protected_qa"],
        "required_coordinate_spaces": ["source_pixel", "output_pixel"],
        "required_transform_operations": ["inverse_project"],
        "minimum_person_count": 2,
        "accepted_media_scopes": ["still_image"],
        "authority_requirements": {
            "accepted_mode_a_truth_tiers": [
                "machine_candidate",
                "qa_passed_machine_candidate",
                "operationally_certified_artifact",
            ],
            "accepted_certificate_kinds": ["exact_serving_route_output"],
            "accepted_issuer_kinds": ["maskfactory_autonomous"],
            "require_unrevoked_certificate": True,
            "require_exact_scope_match": True,
            "access_mode_determines_authority": False,
            "allow_consumer_truth_escalation": False,
        },
        "runtime_requirements": {
            "request_timeout_ms": 10000,
            "maximum_queue_ms": 1000,
            "maximum_p50_latency_ms": 2000,
            "maximum_p95_latency_ms": 4000,
            "maximum_vram_mb": 8192,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 1000000,
            "minimum_concurrency": 1,
            "maximum_retries": 2,
            "idempotency_required": True,
            "fail_closed_on_mismatch": True,
            "circuit_breaker_required": True,
        },
        "requirements_sha256": "0" * 64,
    }
    return requirements


def build_request(mode: str, *, refine_parent: Mapping[str, Any] | None = None) -> dict[str, Any]:
    is_mode_a = mode == "mode_a_package_read"
    target = region(
        region_id="target-left-hand",
        artifact_id="package-left-hand" if is_mode_a else "control-left-hand",
        label="left_hand",
        owner=owner_self(),
        mask_type="atomic" if is_mode_a else "roi_control",
        artifact_kind="atomic_visible",
        certified=is_mode_a,
        encoded_seed="mode-a-target-encoded" if is_mode_a else "mode-b-control-encoded",
        decoded_seed="mode-a-target-decoded" if is_mode_a else "mode-b-control-decoded",
    )
    protected = region(
        region_id="protected-other-torso",
        artifact_id="protected-other-torso",
        label="torso",
        owner=owner_other(),
        mask_type="atomic",
        artifact_kind="protected_qa",
        certified=True,
        encoded_seed="protected-torso-encoded",
        decoded_seed="protected-torso-decoded",
    )
    access_mode = mode
    request_id = {
        "mode_a_package_read": "mfareq_aaaaaaaaaaaaaaaaaaaaaaaa",
        "mode_b_live_predict": "mfareq_bbbbbbbbbbbbbbbbbbbbbbbb",
        "mode_b_live_refine": "mfareq_cccccccccccccccccccccccc",
    }[mode]
    if mode == "mode_a_package_read":
        payload = {
            "payload_type": mode,
            "package_selector": {
                "package_id": "fixture-package",
                "package_revision": "1.0.0",
                "package_manifest_sha256": h("fixture-package-manifest"),
                "package_certificate_kind": "autonomous_package",
                "package_certificate_id": "fixture-package-certificate",
                "package_certificate_sha256": h("fixture-package-certificate"),
                "package_certificate_status": "active",
                "package_certificate_exact_scope_match": True,
            },
            "artifact_selectors": [
                {
                    "artifact_id": target["artifact_id"],
                    "artifact_identity_sha256": target["artifact_identity_sha256"],
                    "encoded_sha256": target["encoded_sha256"],
                    "decoded_mask_sha256": target["decoded_mask_sha256"],
                    "label": target["label"],
                    "artifact_kind": target["artifact_kind"],
                    "canonical_person_id": target["owner"]["canonical_person_id"],
                    "person_index": target["owner"]["person_index"],
                    "coordinate_space": target["coordinate_space"],
                }
            ],
            "mode_payload_sha256": "0" * 64,
        }
    elif mode == "mode_b_live_predict":
        prompt = "left hand of canonical subject"
        payload = {
            "payload_type": mode,
            "prompt": {
                "text": prompt,
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
            "positive_points": [{"x": 105, "y": 105, "coordinate_space": "output_pixel"}],
            "negative_points": [{"x": 300, "y": 300, "coordinate_space": "output_pixel"}],
            "boxes": [
                {"x0": 95, "y0": 95, "x1": 115, "y1": 115, "coordinate_space": "output_pixel"}
            ],
            "spatial_prior": None,
            "mode_payload_sha256": "0" * 64,
        }
    else:
        if refine_parent is None:
            raise ValueError("refinement requires exact parent artifact")
        parent = {
            "artifact_id": refine_parent["artifact_id"],
            "artifact_identity_sha256": refine_parent["artifact_identity_sha256"],
            "encoded_sha256": refine_parent["encoded_sha256"],
            "decoded_mask_sha256": refine_parent["decoded_mask_sha256"],
            "source_decoded_pixel_sha256": refine_parent["source_decoded_pixel_sha256"],
            "owner": refine_parent["owner"],
            "label": refine_parent["label"],
            "mask_type": refine_parent["mask_type"],
            "coordinate_space": refine_parent["coordinate_space"],
            "width": refine_parent["width"],
            "height": refine_parent["height"],
            "transform_chain_sha256": refine_parent["transform_chain_sha256"],
            "transform_step_sequence": 0,
            "authority_state": "certified",
            "truth_tier": "operationally_certified_artifact",
            "certificate_kind": "exact_serving_route_output",
            "certificate_id": "mfac_0123456789abcdef01234567",
            "certificate_sha256": "f" * 64,
            "certificate_status": "active",
            "certificate_scope_sha256": SCOPE,
            "certificate_exact_scope_match": True,
            "revocation_checked_at": "2026-07-17T00:00:05Z",
            "revocation_checkpoint_sha256": REVOCATION_INDEX,
        }
        prior = copy.deepcopy(target)
        prior.update(
            {
                "artifact_id": parent["artifact_id"],
                "artifact_identity_sha256": parent["artifact_identity_sha256"],
                "encoded_sha256": parent["encoded_sha256"],
                "decoded_mask_sha256": parent["decoded_mask_sha256"],
                "mask_type": parent["mask_type"],
                "authority_binding": {
                    "authority_state": "certified",
                    "issuer_kind": "maskfactory_autonomous",
                    "certificate_kind": "exact_serving_route_output",
                    "certificate_id": parent["certificate_id"],
                    "certificate_sha256": parent["certificate_sha256"],
                    "certificate_status": "active",
                    "certificate_scope_sha256": SCOPE,
                    "certificate_exact_scope_match": True,
                    "revocation_checked_at": "2026-07-17T00:00:05Z",
                    "revocation_checkpoint_sha256": REVOCATION_INDEX,
                },
                "required_minimum_authority_state": "certified",
            }
        )
        payload = {
            "payload_type": mode,
            "parent_artifacts": [parent],
            "prior_mask": prior,
            "refinement_prompt": "repair left-hand boundary",
            "positive_clicks": [{"x": 106, "y": 106, "coordinate_space": "output_pixel"}],
            "negative_clicks": [],
            "boxes": [],
            "mode_payload_sha256": "0" * 64,
        }
    payload["mode_payload_sha256"] = canonical_document_sha256(
        payload, excluded_top_level_fields=("mode_payload_sha256",)
    )
    request = {
        "schema_version": "1.0.0",
        "record_type": "mask_acquisition_request",
        "request_id": request_id,
        "project_id": "comfy-main-fixture",
        "run_id": "run-fixture",
        "correlation_id": "correlation-fixture",
        "job_id": "job-fixture",
        "pass_id": "pass-mask-fixture",
        "attempt_id": "attempt-1" if mode != "mode_b_live_refine" else "attempt-2",
        "attempt_number": 1 if mode != "mode_b_live_refine" else 2,
        "hypothesis": {
            "hypothesis_id": (
                "hypothesis-initial"
                if mode != "mode_b_live_refine"
                else "hypothesis-refine-boundary"
            ),
            "hypothesis_class": "initial" if mode != "mode_b_live_refine" else "boundary",
            "material_change_sha256": (
                None if mode != "mode_b_live_refine" else h("refine-boundary-change")
            ),
            "retry_kind": "initial" if mode != "mode_b_live_refine" else "quality_hypothesis",
        },
        "idempotency_key": f"fixture:{mode}:attempt:{1 if mode != 'mode_b_live_refine' else 2}",
        "created_at": "2026-07-17T00:00:00Z",
        "deadline_at": "2026-07-17T00:01:00Z",
        "authentication": authentication(
            "consumer_request",
            f"request-{mode}-nonce-0001",
            "2026-07-16T23:59:59Z",
            "2026-07-17T00:02:00Z",
        ),
        "trust_binding": trust_binding("consumer_request"),
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["request_payload_sha256", "signature"],
        },
        "access_mode": access_mode,
        "media_scope": media_scope(),
        "source": source(),
        "subject": subject(),
        "mask_intents": [
            {
                "intent_id": "intent-left-hand",
                "label": "left_hand",
                "artifact_kind": "atomic_visible",
                "purpose": "conditioning",
                "target_coordinate_space": "output_pixel",
                "target_region_ids": [target["region_id"]],
                "protected_region_ids": [protected["region_id"]],
            }
        ],
        "target_regions": [target],
        "protected_regions": [protected],
        "protected_owner_roster": [
            {
                "owner": owner_self(),
                "relationship": "self",
                "authorization_policy_id": "owner-policy-v1",
                "authorization_policy_sha256": h("owner-policy-v1"),
            },
            {
                "owner": owner_other(),
                "relationship": "other_character",
                "authorization_policy_id": "owner-policy-v1",
                "authorization_policy_sha256": h("owner-policy-v1"),
            },
        ],
        "transform_chain": transform_chain(),
        "compatibility": {
            "bridge_contract": "maskfactory-comfyui-bridge/1.0",
            "release_id": RELEASE_ID,
            "capability_snapshot_id": CAPABILITY_ID,
            "capability_snapshot_sha256": "0" * 64,
            "api_contract": "maskfactory-api/1.0",
            "package_format": "maskfactory-package/1.0",
            "ontology_version": "body_parts_v1",
            "ontology_sha256": h("body_parts_v1"),
        },
        "minimum_authority_state": "qa_passed_noncertified" if is_mode_a else "certified",
        "accepted_authority": {
            "issuer_kinds": ["maskfactory_autonomous"],
            "certificate_kinds": ["exact_serving_route_output"],
            "required_certificate_scope_sha256": SCOPE,
            "require_active_certificate": True,
            "require_exact_scope_match": True,
        },
        "resource_envelope": {
            "maximum_runtime_ms": 5000,
            "maximum_queue_ms": 1000,
            "maximum_vram_mb": 8192,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 1000000,
            "priority": "normal",
            "allow_cpu_fallback": False,
        },
        "retry_policy": {
            "maximum_attempts": 3,
            "retry_only_typed_transient_errors": True,
            "allow_silent_fallback": False,
        },
        "mode_payload": payload,
        "request_payload_sha256": "0" * 64,
    }
    return request


def receipt_output_from_region(
    record: Mapping[str, Any],
    *,
    artifact_id: str | None = None,
    encoded_seed: str | None = None,
    decoded_seed: str | None = None,
) -> dict[str, Any]:
    output = {
        key: copy.deepcopy(record[key])
        for key in (
            "artifact_id",
            "label",
            "artifact_kind",
            "mask_type",
            "owner",
            "artifact_identity_sha256",
            "encoded_sha256",
            "decoded_mask_sha256",
            "format",
            "channel_layout",
            "dtype",
            "allowed_values",
            "visibility",
            "empty_semantics",
            "content_summary",
            "source_decoded_pixel_sha256",
            "width",
            "height",
            "coordinate_space",
            "transform_chain_sha256",
        )
    }
    if artifact_id is not None:
        output["artifact_id"] = artifact_id
    if encoded_seed is not None:
        output["encoded_sha256"] = h(encoded_seed)
    if decoded_seed is not None:
        output["decoded_mask_sha256"] = h(decoded_seed)
    output.update(
        {
            "intent_id": "intent-left-hand",
            "relative_path": f"outputs/{output['artifact_id']}.png",
            "size_bytes": 1234,
        }
    )
    output["artifact_identity_sha256"] = artifact_identity_sha256(output)
    return output


def input_lineage(region_record: Mapping[str, Any]) -> dict[str, Any]:
    auth = region_record["authority_binding"]
    return {
        "region_id": region_record["region_id"],
        "artifact_identity_sha256": region_record["artifact_identity_sha256"],
        "encoded_sha256": region_record["encoded_sha256"],
        "decoded_mask_sha256": region_record["decoded_mask_sha256"],
        "source_decoded_pixel_sha256": region_record["source_decoded_pixel_sha256"],
        "artifact_type": region_record["mask_type"],
        "owner_identity_sha256": canonical_document_sha256(region_record["owner"]),
        "coordinate_space": region_record["coordinate_space"],
        "width": region_record["width"],
        "height": region_record["height"],
        "transform_chain_sha256": region_record["transform_chain_sha256"],
        "transform_step_sequence": region_record["transform_step_sequence"],
        "required_minimum_authority_state": region_record["required_minimum_authority_state"],
        "authority_state": auth["authority_state"],
        "issuer_kind": auth["issuer_kind"],
        "certificate_kind": auth["certificate_kind"],
        "certificate_id": auth["certificate_id"],
        "certificate_sha256": auth["certificate_sha256"],
        "certificate_scope_sha256": auth["certificate_scope_sha256"],
        "certificate_status": auth["certificate_status"],
        "certificate_exact_scope_match": auth["certificate_exact_scope_match"],
        "revocation_checked_at": auth["revocation_checked_at"],
        "revocation_checkpoint_sha256": auth["revocation_checkpoint_sha256"],
    }


def lineage_parents(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_sha256": row["artifact_identity_sha256"],
            "authority_state": row["authority_state"],
            "truth_tier": row["truth_tier"],
            "certificate_kind": row["certificate_kind"],
            "certificate_id": row["certificate_id"],
            "certificate_sha256": row["certificate_sha256"],
            "certificate_status": row["certificate_status"],
            "certificate_exact_scope_match": row["certificate_exact_scope_match"],
        }
        for row in request["mode_payload"].get("parent_artifacts") or []
    ]


def flattened_source() -> dict[str, Any]:
    src = source()
    return {
        "artifact_id": src["artifact_id"],
        "encoded_sha256": src["encoded_sha256"],
        "decoded_pixel_sha256": src["decoded_pixel_sha256"],
        "decoder_id": src["decoder"]["decoder_id"],
        "decoder_version": src["decoder"]["version"],
        "decoder_binary_sha256": src["decoder"]["binary_sha256"],
        "exif_orientation": src["exif_orientation"],
        "orientation_applied": src["orientation_applied"],
        "width": src["width"],
        "height": src["height"],
        "channel_layout": src["channel_layout"],
        "alpha_mode": src["alpha_mode"],
        "bit_depth": src["bit_depth"],
        "dtype": src["dtype"],
        "color_space": src["color_space"],
        "icc_profile_sha256": src["icc_profile_sha256"],
        "color_transform_sha256": src["color_transform"]["transform_sha256"],
        "frame_extraction_sha256": None,
        "coordinate_space": "source_pixel",
    }


def flattened_subject() -> dict[str, Any]:
    person = subject()
    return {
        field: person[field]
        for field in (
            "scene_id",
            "shot_id",
            "take_id",
            "character_id",
            "character_revision",
            "scene_instance_id",
            "canonical_person_id",
            "person_index",
            "provider_person_index",
        )
    } | {"assignment_evidence_sha256": person["assignment_evidence"]["mapping_sha256"]}


def provider_binding() -> dict[str, Any]:
    return {
        "stack_id": "fixture.stack",
        "stack_sha256": h("fixture.stack"),
        "model_artifacts": [{"model_id": "fixture-segmenter", "sha256": h("fixture-segmenter")}],
        "workflow": {"workflow_id": "fixture-mask-workflow", "sha256": h("fixture-mask-workflow")},
        "runtime": provider_runtime(),
        "execution_fingerprint_sha256": h("fixture-execution-fingerprint"),
    }


def transform_observation() -> dict[str, Any]:
    chain = transform_chain()
    return {
        "transform_chain_id": chain["chain_id"],
        "transform_chain_sha256": chain["chain_sha256"],
        "source_coordinate_space": chain["source"]["coordinate_space"],
        "source_width": chain["source"]["width"],
        "source_height": chain["source"]["height"],
        "output_coordinate_space": chain["output"]["coordinate_space"],
        "output_width": chain["output"]["width"],
        "output_height": chain["output"]["height"],
        "executed_step_sha256s": [step["step_sha256"] for step in chain["steps"]],
        "roundtrip_checked": True,
        "roundtrip_passed": True,
        "maximum_roundtrip_error_px": 0.0,
    }


def build_receipt(
    request: Mapping[str, Any],
    output: Mapping[str, Any],
    release: Mapping[str, Any],
    *,
    certificate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    mode = request["access_mode"]
    certified = certificate is not None
    package = (
        request["mode_payload"].get("package_selector") if mode == "mode_a_package_read" else None
    )
    if isinstance(package, Mapping):
        package_fields = {
            key: package[key]
            for key in (
                "package_id",
                "package_revision",
                "package_manifest_sha256",
                "package_certificate_kind",
                "package_certificate_id",
                "package_certificate_sha256",
                "package_certificate_status",
                "package_certificate_exact_scope_match",
            )
        }
    else:
        package_fields = {
            "package_id": None,
            "package_revision": None,
            "package_manifest_sha256": None,
            "package_certificate_kind": "none",
            "package_certificate_id": None,
            "package_certificate_sha256": None,
            "package_certificate_status": "none",
            "package_certificate_exact_scope_match": False,
        }
    receipt = {
        "schema_version": "1.0.0",
        "record_type": "mask_acquisition_receipt",
        "receipt_id": {
            "mode_a_package_read": "mfarec_aaaaaaaaaaaaaaaaaaaaaaaa",
            "mode_b_live_predict": "mfarec_bbbbbbbbbbbbbbbbbbbbbbbb",
            "mode_b_live_refine": "mfarec_cccccccccccccccccccccccc",
        }[mode],
        "request_id": request["request_id"],
        "request_payload_sha256": request["request_payload_sha256"],
        "project_id": request["project_id"],
        "run_id": request["run_id"],
        "job_id": request["job_id"],
        "pass_id": request["pass_id"],
        "attempt_id": request["attempt_id"],
        "attempt_number": request["attempt_number"],
        "hypothesis_id": request["hypothesis"]["hypothesis_id"],
        "idempotency_key": request["idempotency_key"],
        "completed_at": "2026-07-17T00:00:05Z",
        "authentication": authentication(
            "producer_receipt",
            f"receipt-{mode}-nonce-0001",
            "2026-07-17T00:00:04Z",
            "2026-07-17T00:05:00Z",
        ),
        "trust_binding": trust_binding("producer_receipt"),
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["receipt_payload_sha256", "signature"],
        },
        "result": "succeeded",
        "access_mode": mode,
        "media_scope": copy.deepcopy(request["media_scope"]),
        "release_binding": {
            "release_id": RELEASE_ID,
            "release_payload_sha256": release["release_payload_sha256"],
            "capability_snapshot_id": CAPABILITY_ID,
            "capability_snapshot_sha256": request["compatibility"]["capability_snapshot_sha256"],
            "bridge_contract": "maskfactory-comfyui-bridge/1.0",
            "wire_schema_name": "mask_acquisition_receipt",
            "wire_schema_version": "1.0.0",
            "wire_schema_sha256": raw_sha(SCHEMAS / "mask_acquisition_receipt.schema.json"),
        },
        "execution_observation": {
            "admitted_at": "2026-07-17T00:00:01Z",
            "queued_at": "2026-07-17T00:00:01Z",
            "started_at": "2026-07-17T00:00:02Z",
            "completed_at": "2026-07-17T00:00:05Z",
            "queue_ms": 1000,
            "runtime_ms": 3000,
            "total_ms": 4000,
            "deadline_met": True,
            "outcome_class": "success",
            "worker": {
                "worker_id": "worker-fixture",
                "device_id": "gpu-fixture",
                "device_kind": "cuda",
                "lease_id": "lease-fixture",
                "lease_acquired_at": "2026-07-17T00:00:01Z",
                "lease_expires_at": "2026-07-17T00:10:00Z",
            },
            "resources": {"peak_vram_mb": 4096, "peak_ram_mb": 8192, "output_bytes": 1234},
            "route_selection": {
                "selected_route_id": "route-fixture",
                "selected_route_sha256": h("route-fixture"),
                "eligible_alternatives": [
                    {
                        "route_id": "route-alternative",
                        "route_sha256": h("route-alternative"),
                        "score": 0.7,
                    }
                ],
                "selection_reason": "qualified contextual champion",
                "selection_evidence_sha256": h("route-selection"),
            },
        },
        "source_binding": flattened_source(),
        "subject_binding": flattened_subject(),
        "provider_binding": None if mode == "mode_a_package_read" else provider_binding(),
        "artifacts": [copy.deepcopy(output)],
        "transform_validation": transform_observation(),
        "qa": {
            "status": "pass",
            "report_sha256": h(f"qa:{mode}"),
            "blocking_failures": [],
            "uncertainty": 0.01,
        },
        "authority": {
            "authority_state": "certified" if certified else "qa_passed_noncertified",
            "issuer_kind": "maskfactory_autonomous",
            "decision_basis": "exact_output_certificate" if certified else "qa_only",
            "certificate_kind": "exact_serving_route_output" if certified else "none",
            "certificate_id": certificate["certificate_id"] if certified else None,
            "certificate_sha256": certificate["certificate_payload_sha256"] if certified else None,
            "certificate_status": "active" if certified else "none",
            "certificate_exact_scope_match": certified,
            "revocation_checked_at": "2026-07-17T00:00:05Z" if certified else None,
            "revocation_index_sha256": REVOCATION_INDEX if certified else None,
        },
        "truth_tier": (
            "operationally_certified_artifact" if certified else "qa_passed_machine_candidate"
        ),
        "lineage": {
            "operation_kind": {
                "mode_a_package_read": "package_read",
                "mode_b_live_predict": "original_prediction",
                "mode_b_live_refine": "refinement",
            }[mode],
            **package_fields,
            "parents": lineage_parents(request),
            "input_target_regions": [input_lineage(row) for row in request["target_regions"]],
            "input_protected_regions": [input_lineage(row) for row in request["protected_regions"]],
            "output_artifact_identity_sha256s": [output["artifact_identity_sha256"]],
        },
        "use_eligibility": {
            "policy_id": "production-mask-use-v1" if certified else "diagnostic-mask-use-v1",
            "policy_sha256": h("production-mask-use-v1" if certified else "diagnostic-mask-use-v1"),
            "required_authority_state": "certified" if certified else "qa_passed_noncertified",
            "exact_use_scope": "production_conditioning" if certified else "diagnostic",
            "eligible": True,
            "reasons": (
                ["exact operational certificate active"]
                if certified
                else ["diagnostic-only noncertified output"]
            ),
        },
        "error": None,
        "receipt_payload_sha256": "0" * 64,
    }
    return receipt


def journal_checkpoint() -> dict[str, Any]:
    return {
        "stream_id": "maskfactory-release-journal",
        "genesis_event_id": "mfbevt_000000000000000000000001",
        "genesis_event_sha256": h("journal-genesis"),
        "first_sequence": 1,
        "last_sequence": 3,
        "event_count": 3,
        "head_event_id": "mfbevt_000000000000000000000003",
        "head_event_sha256": h("journal-head"),
        "revocation_state_sha256": REVOCATION_INDEX,
        "active_revocation_count": 0,
        "validator_sha256": raw_sha(ROOT / "src/maskfactory/validation.py"),
        "checkpointed_at": "2026-07-17T00:00:00Z",
        "fresh_until": "2026-07-18T00:00:00Z",
    }


def build_release(
    capability: Mapping[str, Any], semantic_profile: Mapping[str, Any]
) -> dict[str, Any]:
    core = json.loads((COMPLETION / "core_autonomous_runtime_v1.json").read_text(encoding="utf-8"))
    accuracy = json.loads(
        (COMPLETION / "independent_real_accuracy_v1.json").read_text(encoding="utf-8")
    )
    scale = json.loads((COMPLETION / "scale_daz_maturity_v1.json").read_text(encoding="utf-8"))
    release_key = key_set_fields("producer_release")
    release = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_release_snapshot",
        "release_id": RELEASE_ID,
        "release_status": "fixture",
        "published_at": "2026-07-17T00:00:00Z",
        "evidence_context": "conformance_fixture",
        "fixture_only": True,
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["release_payload_sha256", "signature"],
        },
        "producer": {
            "project": "MaskFactory",
            "repository_id": "maskfactory-fixture",
            "git_commit": "2" * 40,
            "git_tree": "3" * 40,
            "dirty": False,
        },
        "signing_trust": {
            **release_key,
            "release_signing_key_id": KEY_SPECS["producer_release"][1],
            "release_signing_public_key_sha256": hashlib.sha256(
                public_bytes("producer_release")
            ).hexdigest(),
            "rotation_policy_id": "MaskFactory-rotation-v1",
            "rotation_policy_sha256": h("MaskFactory:rotation-policy-v1"),
            "revocation_policy_id": "MaskFactory-revocation-v1",
            "revocation_policy_sha256": h("MaskFactory:revocation-policy-v1"),
        },
        "canonicalization_spec": {
            "algorithm": "maskfactory-canonical-json-v1",
            "spec_version": "1.0.0",
            "relative_path": "qa/governance/bridge/maskfactory_canonical_json_v1.json",
            "sha256": raw_sha(BRIDGE_GOVERNANCE / "maskfactory_canonical_json_v1.json"),
            "golden_vectors_relative_path": "qa/governance/bridge/maskfactory_canonical_json_golden_vectors_v1.json",
            "golden_vectors_sha256": raw_sha(
                BRIDGE_GOVERNANCE / "maskfactory_canonical_json_golden_vectors_v1.json"
            ),
            "unicode_normalization": "NFC",
            "encoding": "UTF-8",
            "object_key_order": "unicode_codepoint",
            "duplicate_keys": "reject",
            "number_encoding": "shortest_roundtrip_decimal",
            "negative_zero": "zero",
            "nonfinite_numbers": "reject",
            "timestamp_normalization": "RFC3339_UTC_Z",
        },
        "artifact_security_policy": {
            "policy_id": "release-artifact-security-v1",
            "policy_sha256": h("release-artifact-security-v1"),
            "allowed_root_manifest_relative_path": "release/allowed_root_manifest.json",
            "allowed_root_manifest_sha256": h("release-root-manifest"),
            "reject_absolute_paths": True,
            "reject_parent_traversal": True,
            "reject_drive_or_unc_paths": True,
            "reject_symlink_hardlink_reparse": True,
            "reject_case_collisions": True,
            "reject_unmanifested_files": True,
            "maximum_file_bytes": 2000000000,
            "maximum_archive_files": 10000,
            "maximum_archive_expanded_bytes": 10000000000,
            "maximum_compression_ratio": 200,
        },
        "journal_checkpoint": journal_checkpoint(),
        "compatibility": {
            "bridge_contract": "maskfactory-comfyui-bridge/1.0",
            "api_contract": "maskfactory-api/1.0",
            "package_format": "maskfactory-package/1.0",
            "ontology_version": "body_parts_v1",
            "node_pack_version": "1.0.0",
            "minimum_consumer_contract": "1.0.0",
        },
        "wire_schemas": wire_rows(),
        "semantic_invariant_profile": {
            "record_id": semantic_profile["profile_id"],
            "relative_path": "qa/governance/bridge/mask_bridge_semantic_invariants_v1.json",
            "profile_sha256": semantic_profile["profile_sha256"],
            "document_sha256": raw_sha(
                BRIDGE_GOVERNANCE / "mask_bridge_semantic_invariants_v1.json"
            ),
        },
        "completion_profiles": [
            {
                "profile_id": core["profile_id"],
                "profile_version": core["profile_version"],
                "relative_path": "qa/governance/completion/core_autonomous_runtime_v1.json",
                "policy_sha256": core["policy_sha256"],
                "document_sha256": raw_sha(COMPLETION / "core_autonomous_runtime_v1.json"),
                "required_for_core_runtime": True,
            },
            {
                "profile_id": accuracy["profile_id"],
                "profile_version": accuracy["profile_version"],
                "relative_path": "qa/governance/completion/independent_real_accuracy_v1.json",
                "policy_sha256": accuracy["policy_sha256"],
                "document_sha256": raw_sha(COMPLETION / "independent_real_accuracy_v1.json"),
                "required_for_core_runtime": False,
            },
            {
                "profile_id": scale["profile_id"],
                "profile_version": scale["profile_version"],
                "relative_path": "qa/governance/completion/scale_daz_maturity_v1.json",
                "policy_sha256": scale["policy_sha256"],
                "document_sha256": raw_sha(COMPLETION / "scale_daz_maturity_v1.json"),
                "required_for_core_runtime": False,
            },
        ],
        "artifacts": [
            {
                "kind": "python_wheel",
                "relative_path": "dist/maskfactory_fixture.whl",
                "sha256": h("fixture-wheel"),
                "size_bytes": 1000,
            },
            {
                "kind": "comfyui_node_pack",
                "relative_path": "dist/maskfactory_nodes_fixture.zip",
                "sha256": h("fixture-node-pack"),
                "size_bytes": 1000,
            },
            {
                "kind": "schema_bundle",
                "relative_path": "dist/maskfactory_schemas_fixture.zip",
                "sha256": h("fixture-schema-bundle"),
                "size_bytes": 1000,
            },
            {
                "kind": "openapi_document",
                "relative_path": "dist/openapi.json",
                "sha256": h("fixture-openapi"),
                "size_bytes": 1000,
            },
            {
                "kind": "compatibility_manifest",
                "relative_path": "dist/compatibility_manifest.json",
                "sha256": h("fixture-compatibility-manifest"),
                "size_bytes": 1000,
            },
            {
                "kind": "certificate_index",
                "relative_path": "dist/certificate_index.json",
                "sha256": h("certificate-index"),
                "size_bytes": 1000,
            },
        ],
        "openapi": {
            "version": "3.1.0",
            "relative_path": "dist/openapi.json",
            "sha256": h("fixture-openapi"),
        },
        "capability_snapshot": {
            "record_id": capability["snapshot_id"],
            "relative_path": "dist/capability_snapshot.json",
            "payload_sha256": capability["snapshot_sha256"],
            "document_sha256": hashlib.sha256(
                (json.dumps(capability, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            ).hexdigest(),
        },
        "workflow_inventory": {
            "inventory_id": "workflow-inventory-fixture",
            "relative_path": "dist/workflow_inventory.json",
            "sha256": h("workflow-inventory"),
            "record_count": 1,
        },
        "node_inventory": {
            "inventory_id": "node-inventory-fixture",
            "relative_path": "dist/node_inventory.json",
            "sha256": h("node-inventory"),
            "record_count": 10,
        },
        "certificate_index": {
            "relative_path": "dist/certificate_index.json",
            "sha256": h("certificate-index"),
            "active_certificate_count": 1,
            "revocation_index_sha256": REVOCATION_INDEX,
        },
        "evidence_index": {
            "inventory_id": "evidence-index-fixture",
            "relative_path": "dist/evidence_index.json",
            "sha256": h("evidence-index"),
            "record_count": 10,
        },
        "known_limitations": [
            {
                "limitation_id": "fixture-only",
                "scope": "all",
                "description": "Conformance fixture only",
                "mitigation": "Require runtime evidence for production",
            }
        ],
        "breaking_changes": [],
        "installation": {
            "installer_id": "fixture-installer",
            "installer_sha256": h("fixture-installer"),
            "install_manifest_sha256": h("fixture-install-manifest"),
            "verification_workflow_id": "fixture-install-verify",
            "verification_workflow_sha256": h("fixture-install-verify"),
        },
        "rollback": {
            "rollback_id": "fixture-rollback",
            "rollback_sha256": h("fixture-rollback"),
            "target_release_id": None,
            "verification_evidence_sha256": h("fixture-rollback-evidence"),
        },
        "supersedes_release_id": None,
        "revoked_release_ids": [],
        "release_payload_sha256": "0" * 64,
    }
    release["artifact_security_policy"]["policy_sha256"] = canonical_document_sha256(
        release["artifact_security_policy"], excluded_top_level_fields=("policy_sha256",)
    )
    sign(
        release,
        "release_payload_sha256",
        "producer_release",
        ("release_payload_sha256", "signature"),
    )
    return release


def build_certificate(
    request: Mapping[str, Any], output: Mapping[str, Any], release: Mapping[str, Any]
) -> dict[str, Any]:
    authority_keys = key_set_fields("producer_authority")
    source_binding = flattened_source()
    source_binding.pop("coordinate_space")
    owner = output["owner"]
    bound = {
        key: copy.deepcopy(output[key])
        for key in (
            "artifact_id",
            "intent_id",
            "source_decoded_pixel_sha256",
            "artifact_identity_sha256",
            "encoded_sha256",
            "decoded_mask_sha256",
            "format",
            "channel_layout",
            "dtype",
            "allowed_values",
            "mask_type",
            "label",
            "visibility",
            "empty_semantics",
            "content_summary",
            "artifact_kind",
            "width",
            "height",
            "coordinate_space",
            "transform_chain_sha256",
        )
    }
    bound.update(owner)
    certificate = {
        "schema_version": "1.0.0",
        "record_type": "operational_autonomy_certificate",
        "certificate_kind": "exact_serving_route_output",
        "certificate_id": (
            "mfac_0123456789abcdef01234568"
            if request["access_mode"] == "mode_b_live_refine"
            else "mfac_0123456789abcdef01234567"
        ),
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["certificate_payload_sha256", "signature"],
        },
        "certificate_payload_sha256": "0" * 64,
        "status": "active",
        "issued_at": "2026-07-17T00:00:04Z",
        "expires_at": "2026-07-18T00:00:04Z",
        "evidence_context": "conformance_fixture",
        "fixture_only": True,
        "issuer_kind": "maskfactory_autonomous",
        "authority_profile": "core_autonomous_runtime",
        "authority_state": "certified",
        "truth_tier": "operationally_certified_artifact",
        "access_mode": request["access_mode"],
        "media_scope": copy.deepcopy(request["media_scope"]),
        "release_binding": {
            "release_id": release["release_id"],
            "release_payload_sha256": release["release_payload_sha256"],
            "capability_snapshot_id": CAPABILITY_ID,
            "capability_snapshot_sha256": request["compatibility"]["capability_snapshot_sha256"],
            "bridge_contract": "maskfactory-comfyui-bridge/1.0",
            "certificate_schema_sha256": raw_sha(
                SCHEMAS / "operational_autonomy_certificate.schema.json"
            ),
            "signing_key_set_id": authority_keys["key_set_id"],
            "signing_key_set_version": authority_keys["key_set_version"],
            "signing_key_set_sha256": authority_keys["key_set_sha256"],
            "rotation_policy_sha256": h("MaskFactory:rotation-policy-v1"),
            "revocation_policy_sha256": h("MaskFactory:revocation-policy-v1"),
        },
        "ontology_binding": {
            "ontology_id": "maskfactory_body_parts",
            "version": "body_parts_v1",
            "sha256": h("body_parts_v1"),
            "left_right_convention": "character_perspective",
        },
        "pipeline_policy_binding": {
            "pipeline_id": "mask-pipeline-fixture",
            "pipeline_sha256": h("mask-pipeline-fixture"),
            "policy_id": "mask-policy-fixture",
            "policy_sha256": h("mask-policy-fixture"),
            "prompt_package_id": "prompt-fixture",
            "prompt_package_sha256": h("prompt-fixture"),
            "controller_id": "mask-controller-fixture",
            "controller_version": "1.0.0",
            "controller_sha256": h("mask-controller-fixture"),
            "randomness_mode": "deterministic_seeded",
            "seed": 42,
            "randomness_manifest_sha256": h("randomness-fixture"),
            "sampler_settings_sha256": h("sampler-fixture"),
        },
        "execution_binding": {
            "provider_stack_id": "fixture.stack",
            "provider_stack_sha256": h("fixture.stack"),
            "model_artifacts": [
                {"model_id": "fixture-segmenter", "sha256": h("fixture-segmenter")}
            ],
            "workflow_id": "fixture-mask-workflow",
            "workflow_sha256": h("fixture-mask-workflow"),
            **provider_runtime(),
            "execution_fingerprint_sha256": h("fixture-execution-fingerprint"),
        },
        "subject_binding": flattened_subject(),
        "source_binding": source_binding,
        "coordinate_binding": transform_observation(),
        "qualified_route_scope": {
            "scope_sha256": h("fixture-qualified-scope"),
            "labels": ["left_hand", "torso"],
            "contexts": ["solo", "duo"],
            "risk_buckets": ["standard", "multi_person"],
            "max_person_count": 2,
            "artifact_kinds": ["atomic_visible", "protected_qa"],
        },
        "certified_output_scope": {
            "scope_sha256": SCOPE,
            "labels": ["left_hand"],
            "artifact_identity_sha256s": [output["artifact_identity_sha256"]],
            "artifact_kinds": ["atomic_visible"],
            "owners": [owner["scene_instance_id"]],
            "coordinate_spaces": ["output_pixel"],
            "permitted_uses": [
                "production_conditioning",
                "downstream_promotion_support",
                "repair_seed",
                "qa",
            ],
            "exact_scope_only": True,
        },
        "lineage": {
            "operation_kind": (
                "refinement"
                if request["access_mode"] == "mode_b_live_refine"
                else "original_prediction"
            ),
            "parents": lineage_parents(request),
            "package_id": None,
            "package_revision": None,
            "package_manifest_sha256": None,
            "package_certificate_kind": "none",
            "package_certificate_id": None,
            "package_certificate_sha256": None,
            "package_certificate_status": "none",
            "package_certificate_exact_scope_match": False,
            "input_target_regions": [input_lineage(row) for row in request["target_regions"]],
            "input_protected_regions": [input_lineage(row) for row in request["protected_regions"]],
            "output_artifact_identity_sha256s": [output["artifact_identity_sha256"]],
        },
        "bound_artifacts": [bound],
        "qa_evidence": {
            "status": "pass",
            "qa_policy_id": "operational-mask-qa-v1",
            "qa_policy_sha256": h("operational-mask-qa-v1"),
            "gate_results": [
                {
                    "gate_id": gate,
                    "status": "pass",
                    "evidence_sha256": h(f"gate:{gate}"),
                    "executor_id": (
                        "fixture.critic"
                        if gate in {"critic_quality", "critic_independence"}
                        else f"executor:{gate}"
                    ),
                    "executor_sha256": (
                        h("fixture.critic")
                        if gate in {"critic_quality", "critic_independence"}
                        else h(f"executor:{gate}")
                    ),
                }
                for gate in sorted(OPERATIONAL_QA_GATES)
            ],
            "deterministic_report_sha256": h("deterministic-report"),
            "critic_report_sha256": h("critic-report"),
            "ownership_report_sha256": h("ownership-report"),
            "protected_region_report_sha256": h("protected-region-report"),
            "critic_independent_from_generator": True,
            "all_blocking_gates_passed": True,
            "abstention_available": True,
            "critic_binding": {
                "critic_id": "critic-fixture",
                "critic_role": "independent_quality_critic",
                "critic_stack_id": "fixture.critic",
                "critic_stack_sha256": h("fixture.critic"),
                "model_artifacts": [
                    {"model_id": "fixture-critic-vlm", "sha256": h("fixture-critic-vlm")}
                ],
                "workflow_id": "fixture-critic-workflow",
                "workflow_sha256": h("fixture-critic-workflow"),
                "execution_fingerprint_sha256": h("fixture-critic-execution"),
                "qualification_scope_sha256": h("fixture-critic-scope"),
                "qualification_certificate_sha256": h("fixture-critic-certificate"),
                "qualification_status": "active",
                "qualified_until": "2026-12-31T00:00:00Z",
            },
        },
        "revocation": {
            "checked_at": "2026-07-17T00:00:05Z",
            "revocation_index_sha256": REVOCATION_INDEX,
            "is_revoked": False,
        },
        "external_manual_anchor_required": False,
        "claim_limits": {
            "maximum_claim": "operational_policy_conformance_for_exact_bound_artifacts",
            "independent_real_accuracy_claim": False,
            "holdout_truth_claim": False,
            "training_gold_claim": False,
            "counts_toward_training_or_accuracy_gates": False,
            "promotion_transaction_required_for_training_gold": True,
        },
    }
    sign(
        certificate,
        "certificate_payload_sha256",
        "producer_authority",
        ("certificate_payload_sha256", "signature"),
    )
    return certificate


def adoption_pins(release: Mapping[str, Any]) -> list[dict[str, str]]:
    pins = [
        {"kind": f"wire_schema:{row['name']}", "sha256": row["sha256"]}
        for row in release["wire_schemas"]
    ]
    pins.extend(
        {"kind": f"artifact:{row['kind']}:{row['relative_path']}", "sha256": row["sha256"]}
        for row in release["artifacts"]
    )
    for field in (
        "workflow_inventory",
        "node_inventory",
        "certificate_index",
        "evidence_index",
        "openapi",
    ):
        pins.append({"kind": field, "sha256": release[field]["sha256"]})
    pins.extend(
        [
            {
                "kind": "semantic_invariant_profile_payload",
                "sha256": release["semantic_invariant_profile"]["profile_sha256"],
            },
            {
                "kind": "semantic_invariant_profile_document",
                "sha256": release["semantic_invariant_profile"]["document_sha256"],
            },
            {
                "kind": "capability_snapshot_payload",
                "sha256": release["capability_snapshot"]["payload_sha256"],
            },
            {
                "kind": "capability_snapshot_document",
                "sha256": release["capability_snapshot"]["document_sha256"],
            },
        ]
    )
    pins.extend(
        [
            {"kind": "canonicalization_spec", "sha256": release["canonicalization_spec"]["sha256"]},
            {
                "kind": "canonicalization_golden_vectors",
                "sha256": release["canonicalization_spec"]["golden_vectors_sha256"],
            },
            {
                "kind": "allowed_root_manifest",
                "sha256": release["artifact_security_policy"]["allowed_root_manifest_sha256"],
            },
        ]
    )
    pins.extend(
        {"kind": f"completion_profile:{row['profile_id']}", "sha256": row["document_sha256"]}
        for row in release["completion_profiles"]
    )
    return sorted(pins, key=lambda row: row["kind"])


def build_adoption(
    release: Mapping[str, Any], capability: Mapping[str, Any], requirements: Mapping[str, Any]
) -> dict[str, Any]:
    producer = release["signing_trust"]
    consumer = key_set_fields("consumer_adoption")
    adoption = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_adoption_receipt",
        "adoption_id": "mfadopt_0123456789abcdef01234567",
        "decided_at": "2026-07-17T00:00:01Z",
        "adoption_scope": "conformance_validation",
        "evidence_context": "conformance_fixture",
        "fixture_only": True,
        "production_use_authorized": False,
        "consumer": {
            "project": "Comfy_UI_Main",
            "controller_version": "1.0.0",
            "git_commit": "1" * 40,
        },
        "release_id": release["release_id"],
        "release_payload_sha256": release["release_payload_sha256"],
        "capability_snapshot_id": capability["snapshot_id"],
        "capability_snapshot_sha256": capability["snapshot_sha256"],
        "consumer_requirements_id": requirements["requirements_id"],
        "consumer_requirements_sha256": requirements["requirements_sha256"],
        "qualification_bundle_id": "mfqual_0123456789abcdef01234567",
        "qualification_bundle_sha256": h("qualification-bundle-fixture"),
        "trust_binding": {
            "producer_key_set_id": producer["key_set_id"],
            "producer_key_set_version": producer["key_set_version"],
            "producer_key_set_sha256": producer["key_set_sha256"],
            "producer_release_key_id": producer["release_signing_key_id"],
            "producer_release_public_key_sha256": producer["release_signing_public_key_sha256"],
            "consumer_key_set_id": consumer["key_set_id"],
            "consumer_key_set_version": consumer["key_set_version"],
            "consumer_key_set_sha256": consumer["key_set_sha256"],
            "consumer_adoption_key_id": KEY_SPECS["consumer_adoption"][1],
            "consumer_adoption_public_key_sha256": hashlib.sha256(
                public_bytes("consumer_adoption")
            ).hexdigest(),
            "rotation_policy_sha256": h("joint-rotation-policy"),
            "revocation_policy_sha256": h("joint-revocation-policy"),
        },
        "journal_checkpoint": journal_checkpoint(),
        "decision": "conformance_only",
        "required_capabilities_satisfied": False,
        "compatibility_checks": [
            {"check": check, "result": "pass", "evidence_sha256": h(f"adoption-check:{check}")}
            for check in sorted(ADOPTION_COMPATIBILITY_CHECKS)
        ],
        "capability_decisions": [
            {
                "capability_id": "mask.package.read",
                "requirement_class": "required",
                "decision": "rejected",
                "reason": "conformance fixture cannot establish adoption",
                "evidence_sha256": h("mask.package.read:conformance-only"),
            },
            {
                "capability_id": "mask.live.predict",
                "requirement_class": "optional",
                "decision": "rejected",
                "reason": "conformance fixture cannot establish adoption",
                "evidence_sha256": h("mask.live.predict:conformance-only"),
            },
        ],
        "pinned_artifacts": [],
        "accepted_capabilities": [],
        "rejected_capabilities": ["mask.package.read", "mask.live.predict"],
        "valid_until": "2026-07-18T00:00:01Z",
        "use_time_recheck_required": True,
        "revalidation_triggers": sorted(ADOPTION_REVALIDATION_TRIGGERS),
        "adoption_payload_sha256": "0" * 64,
    }
    sign(
        adoption,
        "adoption_payload_sha256",
        "consumer_adoption",
        ("adoption_payload_sha256", "signature"),
    )
    return adoption


def build_error(request_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_type": "mask_bridge_error",
        "error_id": "mferr_0123456789abcdef01234567",
        "request_id": request_id,
        "observed_at": "2026-07-17T00:00:05Z",
        "code": "SERVICE_UNAVAILABLE",
        "category": "availability",
        "retryable": True,
        "impact_scope": "request_only",
        "affected_scope": {
            "correlation_ids": ["correlation-fixture"],
            "pass_ids": ["pass-mask-fixture"],
            "release_ids": [RELEASE_ID],
            "capability_ids": ["mask.live.predict"],
            "artifact_sha256s": [],
        },
        "remediation": {
            "action": "retry",
            "retry_after_ms": 1000,
            "runbook_id": "service-retry-v1",
            "runbook_sha256": h("service-retry-v1"),
            "replacement_route_required": False,
        },
        "no_silent_fallback": True,
        "message": "Fixture service unavailable",
        "details_sha256": h("fixture-service-unavailable"),
    }


def build_invalidation(certificate: Mapping[str, Any]) -> dict[str, Any]:
    event = {
        "schema_version": "1.0.0",
        "record_type": "mask_authority_invalidation_event",
        "event_id": "mfinv_0123456789abcdef01234567",
        "stream_id": "maskfactory-release-journal",
        "sequence": 4,
        "causation_id": "mfbevt_000000000000000000000003",
        "idempotency_key": "invalidation:fixture:0001",
        "occurred_at": "2026-07-17T00:01:00Z",
        "effective_at": "2026-07-17T00:01:00Z",
        "evidence_context": "conformance_fixture",
        "fixture_only": True,
        "producer": "MaskFactory",
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["event_payload_sha256", "signature"],
        },
        "trust_binding": trust_binding("producer_journal"),
        "reason": "certificate_revoked",
        "severity": "blocking",
        "target_transitions": [
            {
                "transition_id": "transition-certificate-fixture",
                "target_kind": "certificate",
                "target_id": certificate["certificate_id"],
                "target_sha256": certificate["certificate_payload_sha256"],
                "previous_authority_state": "certified",
                "new_authority_state": "draft",
                "previous_certificate_status": "active",
                "new_certificate_status": "revoked",
                "reason_code": "certificate_evidence_regression",
                "scope_sha256": SCOPE,
            }
        ],
        "required_actions": [
            {
                "action_id": "action-block-fixture",
                "transition_ids": ["transition-certificate-fixture"],
                "action": "block_dependent_pass",
                "deadline_at": "2026-07-17T00:02:00Z",
                "verification_evidence_required": True,
                "verification_policy_sha256": h("block-policy-v1"),
            },
            {
                "action_id": "action-readopt-fixture",
                "transition_ids": ["transition-certificate-fixture"],
                "action": "revalidate_adoption",
                "deadline_at": "2026-07-17T00:02:00Z",
                "verification_evidence_required": True,
                "verification_policy_sha256": h("readopt-policy-v1"),
            },
        ],
        "superseding_binding": None,
        "rollback_binding": None,
        "evidence_sha256": h("certificate-regression-evidence"),
        "event_payload_sha256": "0" * 64,
    }
    sign(event, "event_payload_sha256", "producer_journal", ("event_payload_sha256", "signature"))
    return event


def build_bridge_event(release: Mapping[str, Any]) -> dict[str, Any]:
    event = {
        "schema_version": "1.0.0",
        "record_type": "mask_bridge_event",
        "event_id": "mfbevt_0123456789abcdef01234567",
        "sequence": 1,
        "stream_id": "fixture-event-stream",
        "occurred_at": "2026-07-17T00:00:00Z",
        "evidence_context": "conformance_fixture",
        "fixture_only": True,
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["event_payload_sha256", "signature"],
        },
        "trust_binding": trust_binding("producer_journal"),
        "journal_epoch": 1,
        "event_type": "release_published",
        "producer": "MaskFactory",
        "correlation_id": "release-fixture",
        "causation_id": None,
        "subject": {
            "release_id": release["release_id"],
            "adoption_id": None,
            "capability_snapshot_id": None,
            "consumer_requirements_id": None,
            "request_id": None,
            "receipt_id": None,
            "certificate_id": None,
            "artifact_sha256": None,
        },
        "state_transition": {
            "resource_kind": "release",
            "from_state": "none",
            "to_state": "published",
            "submission_identity_sha256": release["release_payload_sha256"],
            "receipt_last_atomic_commit": False,
            "invalidation_event_id": None,
            "invalidation_event_sha256": None,
            "reconciliation": None,
        },
        "payload_schema": {
            "name": "maskfactory_release_snapshot",
            "version": "1.0.0",
            "sha256": raw_sha(SCHEMAS / "maskfactory_release_snapshot.schema.json"),
        },
        "payload_sha256": release["release_payload_sha256"],
        "previous_event_sha256": None,
        "event_payload_sha256": "0" * 64,
    }
    sign(event, "event_payload_sha256", "producer_journal", ("event_payload_sha256", "signature"))
    return event


def repair_artifact_binding(
    artifact: Mapping[str, Any],
    *,
    authority_state: str,
    certificate_sha256: str | None,
    revocation_sha256: str | None,
) -> dict[str, Any]:
    owner = artifact.get("owner") or {
        field: artifact[field]
        for field in (
            "owner_kind",
            "entity_id",
            "scene_instance_id",
            "canonical_person_id",
            "person_index",
        )
    }
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_identity_sha256": artifact["artifact_identity_sha256"],
        "encoded_sha256": artifact["encoded_sha256"],
        "decoded_mask_sha256": artifact["decoded_mask_sha256"],
        "source_decoded_pixel_sha256": artifact["source_decoded_pixel_sha256"],
        "owner_identity_sha256": canonical_document_sha256(owner),
        "coordinate_space": artifact["coordinate_space"],
        "transform_chain_sha256": artifact["transform_chain_sha256"],
        "authority_state": authority_state,
        "certificate_sha256": certificate_sha256,
        "revocation_checkpoint_sha256": revocation_sha256,
    }


def build_repair_feedback(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    certificate: Mapping[str, Any],
    release: Mapping[str, Any],
    semantic_profile: Mapping[str, Any],
) -> dict[str, Any]:
    output = receipt["artifacts"][0]
    protected = request["protected_regions"][0]
    feedback = {
        "schema_version": "1.0.0",
        "record_type": "mask_repair_feedback",
        "feedback_id": "mffb_0123456789abcdef01234567",
        "project_id": receipt["project_id"],
        "run_id": receipt["run_id"],
        "job_id": receipt["job_id"],
        "pass_id": receipt["pass_id"],
        "attempt_id": "attempt-2",
        "created_at": "2026-07-17T00:00:06Z",
        "consumer": "Comfy_UI_Main",
        "authentication": authentication(
            "consumer_feedback",
            "feedback-fixture-nonce-0001",
            "2026-07-17T00:00:05Z",
            "2026-07-17T00:05:00Z",
        ),
        "trust_binding": trust_binding("consumer_feedback"),
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["feedback_payload_sha256", "signature"],
        },
        "parent_receipt_binding": {
            "receipt_id": receipt["receipt_id"],
            "receipt_payload_sha256": receipt["receipt_payload_sha256"],
            "request_id": request["request_id"],
            "request_payload_sha256": request["request_payload_sha256"],
        },
        "release_binding": {
            "release_id": release["release_id"],
            "release_payload_sha256": release["release_payload_sha256"],
            "capability_snapshot_id": CAPABILITY_ID,
            "capability_snapshot_sha256": request["compatibility"]["capability_snapshot_sha256"],
            "semantic_profile_sha256": semantic_profile["profile_sha256"],
        },
        "policy_binding": {
            "policy_id": receipt["use_eligibility"]["policy_id"],
            "policy_sha256": receipt["use_eligibility"]["policy_sha256"],
        },
        "certificate_binding": {
            "certificate_id": certificate["certificate_id"],
            "certificate_sha256": certificate["certificate_payload_sha256"],
            "certificate_scope_sha256": certificate["certified_output_scope"]["scope_sha256"],
            "status": certificate["status"],
            "revocation_checked_at": certificate["revocation"]["checked_at"],
            "revocation_checkpoint_sha256": certificate["revocation"]["revocation_index_sha256"],
        },
        "source_binding": {
            "artifact_id": request["source"]["artifact_id"],
            "encoded_sha256": request["source"]["encoded_sha256"],
            "decoded_pixel_sha256": request["source"]["decoded_pixel_sha256"],
            "decoder_binary_sha256": request["source"]["decoder"]["binary_sha256"],
        },
        "media_scope_sha256": canonical_document_sha256(request["media_scope"]),
        "subject_binding": {
            "scene_instance_id": request["subject"]["scene_instance_id"],
            "canonical_person_id": request["subject"]["canonical_person_id"],
            "person_index": request["subject"]["person_index"],
            "provider_person_index": request["subject"]["provider_person_index"],
            "assignment_evidence_sha256": request["subject"]["assignment_evidence"][
                "mapping_sha256"
            ],
        },
        "provider_binding": {
            "stack_id": receipt["provider_binding"]["stack_id"],
            "stack_sha256": receipt["provider_binding"]["stack_sha256"],
            "execution_fingerprint_sha256": receipt["provider_binding"][
                "execution_fingerprint_sha256"
            ],
        },
        "output_artifact_bindings": [
            repair_artifact_binding(
                output,
                authority_state="certified",
                certificate_sha256=certificate["certificate_payload_sha256"],
                revocation_sha256=REVOCATION_INDEX,
            )
        ],
        "protected_artifact_bindings": [
            repair_artifact_binding(
                protected,
                authority_state="certified",
                certificate_sha256=protected["authority_binding"]["certificate_sha256"],
                revocation_sha256=protected["authority_binding"]["revocation_checkpoint_sha256"],
            )
        ],
        "transform_binding": {
            "transform_chain_id": receipt["transform_validation"]["transform_chain_id"],
            "transform_chain_sha256": receipt["transform_validation"]["transform_chain_sha256"],
            "executed_step_sha256s": receipt["transform_validation"]["executed_step_sha256s"],
            "roundtrip_report_sha256": h("transform-roundtrip-report"),
        },
        "qa_binding": {
            "qa_policy_sha256": certificate["qa_evidence"]["qa_policy_sha256"],
            "qa_report_sha256": receipt["qa"]["report_sha256"],
            "blocking_failure_ids": ["boundary-softness"],
        },
        "authority_binding": {
            "authority_state": "certified",
            "truth_tier": "operationally_certified_artifact",
            "issuer_kind": "maskfactory_autonomous",
        },
        "defects": [
            {
                "defect_id": "defect-boundary-fixture",
                "class": "boundary",
                "labels": ["left_hand"],
                "severity": "medium",
                "observation_sha256": h("boundary-observation"),
                "target_artifact_identity_sha256": output["artifact_identity_sha256"],
            }
        ],
        "hypothesis": {
            "hypothesis_id": "hypothesis-refine-boundary",
            "parent_hypothesis_id": receipt["hypothesis_id"],
            "material_change": "refinement_change",
            "material_change_sha256": h("refinement-change"),
            "description": "Refine boundary while protecting other character",
            "expected_effect": "Reduce boundary defect without ownership bleed",
        },
        "requested_action": "mode_b_live_refine",
        "retry_budget": {
            "attempt": 2,
            "maximum_attempts": 3,
            "remaining_attempts": 1,
            "same_hypothesis_retry_allowed": False,
        },
        "progress_guard": {
            "no_progress_count": 1,
            "maximum_no_progress_count": 2,
            "previous_score_ppm": 900000,
            "current_score_ppm": 900001,
            "minimum_improvement_ppm": 1000,
            "abstain_when_exhausted": True,
        },
        "immutable_accepted_parent": True,
        "advisory_only": True,
        "consumer_may_mutate_gold": False,
        "consumer_may_escalate_authority": False,
        "feedback_payload_sha256": "0" * 64,
    }
    sign(
        feedback,
        "feedback_payload_sha256",
        "consumer_feedback",
        ("feedback_payload_sha256", "signature"),
    )
    return feedback


def reseal_completion_profile() -> None:
    path = COMPLETION / "core_autonomous_runtime_v1.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["policy_sha256"] = canonical_document_sha256(
        profile, excluded_top_level_fields=("policy_sha256",)
    )
    write_json(path, profile)


def preliminary_negative_fixtures() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mutations = [
        {
            "fixture": "bridge_set",
            "schema": "mask_acquisition_request",
            "pointer": "/access_mode",
            "value": "implicit_mode",
        },
        {
            "fixture": "bridge_set",
            "schema": "mask_acquisition_receipt",
            "pointer": "/truth_tier",
            "value": "autonomous_certified_gold",
        },
        {
            "fixture": "certificate",
            "schema": "operational_autonomy_certificate",
            "pointer": "/claim_limits/training_gold_claim",
            "value": True,
        },
        {
            "fixture": "core_profile",
            "schema": "completion_profile",
            "pointer": "/profile_id",
            "value": "completion_core_autonomous_runtime_v1",
        },
    ]
    raw_promotion = {
        "schema": "mask_acquisition_receipt",
        "mutations": [
            {"pointer": "/authority/authority_state", "value": "draft"},
            {"pointer": "/truth_tier", "value": "machine_candidate"},
            {"pointer": "/use_eligibility/required_authority_state", "value": "certified"},
            {"pointer": "/use_eligibility/exact_use_scope", "value": "production_conditioning"},
            {"pointer": "/use_eligibility/eligible", "value": True},
        ],
    }
    return mutations, raw_promotion


def reseal_semantic_profile(indexed_files: list[tuple[str, str]]) -> dict[str, Any]:
    path = BRIDGE_GOVERNANCE / "mask_bridge_semantic_invariants_v1.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    verifier_sha = raw_sha(ROOT / "src/maskfactory/validation.py")
    for invariant in profile["invariants"]:
        invariant["verifier_sha256"] = verifier_sha
    profile["canonicalization_spec_sha256"] = raw_sha(
        BRIDGE_GOVERNANCE / "maskfactory_canonical_json_v1.json"
    )
    rows = [
        {"relative_path": name, "role": role, "sha256": raw_sha(HERE / name)}
        for name, role in indexed_files
    ]
    profile["conformance_fixture_index"] = {
        "fixture_set_id": "maskfactory-bridge-conformance",
        "fixture_set_version": "1.0.0",
        "relative_path": "tests/fixtures/mask_bridge_contracts",
        "included_fixtures": rows,
        "sha256": hashlib.sha256(canonical_json_bytes(rows)).hexdigest(),
        "positive_count": sum(role == "positive" for _, role in indexed_files),
        "negative_count": sum(role == "negative" for _, role in indexed_files),
    }
    profile["profile_sha256"] = canonical_document_sha256(
        profile, excluded_top_level_fields=("profile_sha256",)
    )
    write_json(path, profile)
    return profile


def finalize_request(request: dict[str, Any], capability: Mapping[str, Any]) -> None:
    request["compatibility"]["capability_snapshot_sha256"] = capability["snapshot_sha256"]
    sign(
        request,
        "request_payload_sha256",
        "consumer_request",
        ("request_payload_sha256", "signature"),
    )


def finalize_receipt(receipt: dict[str, Any]) -> None:
    sign(
        receipt,
        "receipt_payload_sha256",
        "producer_receipt",
        ("receipt_payload_sha256", "signature"),
    )


def main() -> None:
    reseal_completion_profile()
    capability = build_capability_snapshot()
    mutations, raw_promotion = preliminary_negative_fixtures()
    write_json(HERE / "negative_contract_mutations_v1.json", mutations)
    write_json(HERE / "negative_raw_mode_b_self_promotion_v1.json", raw_promotion)

    predict_request = build_request("mode_b_live_predict")
    finalize_request(predict_request, capability)
    write_json(HERE / "positive_mode_b_predict_request_v1.json", predict_request)

    semantic_profile = reseal_semantic_profile(
        [
            ("negative_contract_mutations_v1.json", "negative"),
            ("negative_raw_mode_b_self_promotion_v1.json", "negative"),
            ("positive_mode_b_predict_request_v1.json", "positive"),
        ]
    )
    requirements = build_consumer_requirements()
    requirements["required_semantic_invariant_profile"]["sha256"] = semantic_profile[
        "profile_sha256"
    ]
    sign(
        requirements,
        "requirements_sha256",
        "consumer_requirements",
        ("requirements_sha256", "signature"),
    )
    release = build_release(capability, semantic_profile)

    predict_output = receipt_output_from_region(
        predict_request["target_regions"][0],
        artifact_id="output-left-hand-predict",
        encoded_seed="predict-output-encoded",
        decoded_seed="predict-output-decoded",
    )
    predict_output["mask_type"] = "atomic"
    predict_output["artifact_identity_sha256"] = artifact_identity_sha256(predict_output)
    predict_certificate = build_certificate(predict_request, predict_output, release)
    predict_receipt = build_receipt(
        predict_request, predict_output, release, certificate=predict_certificate
    )
    finalize_receipt(predict_receipt)

    mode_a_request = build_request("mode_a_package_read")
    finalize_request(mode_a_request, capability)
    mode_a_output = receipt_output_from_region(mode_a_request["target_regions"][0])
    mode_a_receipt = build_receipt(mode_a_request, mode_a_output, release, certificate=None)
    finalize_receipt(mode_a_receipt)

    refine_request = build_request("mode_b_live_refine", refine_parent=predict_output)
    refine_parent = refine_request["mode_payload"]["parent_artifacts"][0]
    refine_parent["certificate_id"] = predict_certificate["certificate_id"]
    refine_parent["certificate_sha256"] = predict_certificate["certificate_payload_sha256"]
    prior_authority = refine_request["mode_payload"]["prior_mask"]["authority_binding"]
    prior_authority["certificate_id"] = predict_certificate["certificate_id"]
    prior_authority["certificate_sha256"] = predict_certificate["certificate_payload_sha256"]
    refine_request["mode_payload"]["mode_payload_sha256"] = canonical_document_sha256(
        refine_request["mode_payload"], excluded_top_level_fields=("mode_payload_sha256",)
    )
    finalize_request(refine_request, capability)
    refine_output = receipt_output_from_region(
        predict_output,
        artifact_id="output-left-hand-refine",
        encoded_seed="refine-output-encoded",
        decoded_seed="refine-output-decoded",
    )
    refine_output["artifact_identity_sha256"] = artifact_identity_sha256(refine_output)
    refine_certificate = build_certificate(refine_request, refine_output, release)
    refine_receipt = build_receipt(
        refine_request, refine_output, release, certificate=refine_certificate
    )
    finalize_receipt(refine_receipt)

    adoption = build_adoption(release, capability, requirements)
    error = build_error(predict_request["request_id"])
    invalidation = build_invalidation(predict_certificate)
    feedback = build_repair_feedback(
        predict_request, predict_receipt, predict_certificate, release, semantic_profile
    )
    bridge_event = build_bridge_event(release)

    contract_set = {
        "maskfactory_release_snapshot": release,
        "maskfactory_capability_snapshot": capability,
        "maskfactory_consumer_requirements": requirements,
        "mask_acquisition_request": mode_a_request,
        "mask_acquisition_receipt": mode_a_receipt,
        "mask_bridge_error": error,
        "maskfactory_adoption_receipt": adoption,
        "mask_authority_invalidation_event": invalidation,
        "mask_repair_feedback": feedback,
        "mask_bridge_event": bridge_event,
    }
    write_json(HERE / "positive_contract_set_v1.json", contract_set)
    write_json(HERE / "positive_certified_mode_b_receipt_v1.json", predict_receipt)
    write_json(HERE / "positive_operational_autonomy_certificate_v1.json", predict_certificate)
    write_json(HERE / "positive_certified_mode_b_refine_request_v1.json", refine_request)
    write_json(HERE / "positive_certified_mode_b_refine_receipt_v1.json", refine_receipt)

    print(f"wrote {len(contract_set)} contract documents and 5 standalone fixtures")


if __name__ == "__main__":
    main()
