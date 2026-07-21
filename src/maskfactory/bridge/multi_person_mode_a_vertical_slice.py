"""Producer overlapping/contact two-person Mode A vertical slice (MF-P6-12.03).

Builds deterministic duo fixtures with distinct character instances, ownership
masks, skeletons, protected regions, and transform chains; evaluates Mode A
package reads; runs the autonomous multi-person gate; and proves seeded
wrong-person / cross-instance faults fail closed.

Fixture evidence is preferred. Adopted-package Main/ComfyUI execution remains
an external completion blocker behind MF-P6-12.02.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from jsonschema import Draft202012Validator
from PIL import Image

from maskfactory.autonomy.multi_person_gate import evaluate_multi_person_candidate_gate
from maskfactory.bridge.fixture_main.binding import load_fixture_main_binding
from maskfactory.bridge.mode_a_package_read import evaluate_mode_a_package_read
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.qa.multi_instance import MultiInstanceQcInputs
from maskfactory.validation import canonical_document_sha256, canonical_json_bytes

POLICY_PATH = (
    Path(__file__).parents[3] / "configs" / "multi_person_mode_a_vertical_slice_policy.yaml"
)
SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "schemas"
    / "multi_person_mode_a_vertical_slice_evidence.schema.json"
)
POLICY_ID = "maskfactory-bridge-multi-person-mode-a-vertical-slice-v1"
_IMAGE_ID = "img_duo_contact_overlap_v1"
_LABEL = "torso"
_HEIGHT = 64
_WIDTH = 96
_DECIDED_AT_DEFAULT = "2026-07-19T14:00:00Z"


class MultiPersonModeAVerticalSliceError(ValueError):
    """Raised when multi-person Mode A slice policy or inputs are unusable."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MultiPersonModeAVerticalSliceError(
            "multi-person mode a vertical slice policy unavailable"
        ) from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise MultiPersonModeAVerticalSliceError(
            "unexpected multi-person mode a vertical slice policy"
        )
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise MultiPersonModeAVerticalSliceError(
            "multi-person mode a vertical slice policy hash mismatch"
        )
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in reasons]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _step(
    sequence: int,
    operation: str,
    source: dict[str, Any],
    output: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    step = {
        "sequence": sequence,
        "operation": operation,
        "input": source,
        "output": output,
        "parameters": parameters,
        "inverse_strategy": "exact_inverse",
        "step_sha256": "",
    }
    step["step_sha256"] = canonical_document_sha256(
        step, excluded_top_level_fields=("step_sha256",)
    )
    return step


def _transform_chain(person_index: int) -> dict[str, Any]:
    source = {"coordinate_space": "source_pixel", "width": _WIDTH, "height": _HEIGHT}
    crop = {"coordinate_space": "crop_pixel", "width": _WIDTH - 4, "height": _HEIGHT - 4}
    x_offset = 1 if person_index == 0 else 3
    steps = [
        _step(
            0,
            "crop",
            source,
            crop,
            {
                "parameter_type": "crop",
                "x": x_offset,
                "y": 2,
                "width": _WIDTH - 4,
                "height": _HEIGHT - 4,
            },
        )
    ]
    chain = {
        "chain_id": f"duo-contact-crop-p{person_index}-v1",
        "chain_sha256": "",
        "source": source,
        "output": crop,
        "steps": steps,
        "roundtrip_policy": {
            "required": True,
            "maximum_error_px": 0.0,
            "reject_noninvertible": True,
        },
    }
    chain["chain_sha256"] = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    return chain


def _protected_region(
    *,
    person_index: int,
    owner_id: str,
    scene_instance_id: str,
    character_revision: str,
) -> dict[str, Any]:
    # Crop (x=1|3, y=2) maps source box into crop_pixel for round-trip proof.
    x0 = 8.0 if person_index == 0 else 62.0
    expected_x0 = x0 - (1.0 if person_index == 0 else 3.0)
    owner = {
        "canonical_person_id": owner_id,
        "scene_instance_id": scene_instance_id,
        "character_revision": character_revision,
        "person_index": person_index,
    }
    return {
        "region_id": f"prot-p{person_index}-face",
        "owner": owner,
        "box": {
            "x0": x0,
            "y0": 10.0,
            "x1": x0 + 12.0,
            "y1": 22.0,
            "coordinate_space": "source_pixel",
        },
        "expected_box": {
            "x0": expected_x0,
            "y0": 8.0,
            "x1": expected_x0 + 12.0,
            "y1": 20.0,
            "coordinate_space": "crop_pixel",
        },
    }


def _duo_masks() -> dict[str, np.ndarray]:
    p0 = np.zeros((_HEIGHT, _WIDTH), dtype=bool)
    p1 = np.zeros_like(p0)
    # Overlapping/contact geometry: silhouettes approach mid-frame and touch.
    p0[8:56, 4:40] = True
    p1[8:56, 56:92] = True
    band0 = np.zeros_like(p0)
    band1 = np.zeros_like(p0)
    band0[28:36, 36:40] = True
    band1[28:36, 56:60] = True
    return {
        "p0": p0,
        "p1": p1,
        "band_p0_p1": band0,
        "band_p1_p0": band1,
    }


def _revocation(token: str = "a") -> bytes:
    record = {
        "event_payload_sha256": token * 64,
        "trust_binding": {"key_role": "producer_journal"},
        "signature": {"signed_payload_sha256": token * 64},
    }
    return json.dumps(record, separators=(",", ":")).encode("utf-8")


def _skeleton_bytes(person_index: int, scene_instance_id: str) -> bytes:
    document = {
        "schema_version": "1.0.0",
        "record_type": "synthetic_skeleton_fixture",
        "person_index": person_index,
        "scene_instance_id": scene_instance_id,
        "joints": [
            {"name": "pelvis", "x": 20 + person_index * 52, "y": 40},
            {"name": "neck", "x": 20 + person_index * 52, "y": 16},
            {"name": "left_wrist", "x": 12 + person_index * 52, "y": 32},
            {"name": "right_wrist", "x": 28 + person_index * 52, "y": 32},
        ],
    }
    return canonical_json_bytes(document)


def build_overlapping_contact_duo_fixture(workdir: Path) -> dict[str, Any]:
    """Materialize a deterministic overlapping/contact two-person fixture package."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    masks = _duo_masks()
    source_path = workdir / "source.png"
    Image.new("RGB", (_WIDTH, _HEIGHT), (32, 64, 96)).save(source_path)
    source_encoded = source_path.read_bytes()
    source_pixels = np.asarray(Image.open(source_path).convert("RGB")).tobytes()

    ontology = b"ontology-body-parts-v1-duo-contact"
    release = b"release-duo-contact-fixture-v1"
    capability = b"capability-duo-contact-fixture-v1"
    revocation = _revocation("d")

    persons: list[dict[str, Any]] = []
    catalog_packages: list[dict[str, Any]] = []
    read_bundles: dict[str, dict[str, Any]] = {}
    ownership_sha256s: dict[str, str] = {}
    skeleton_sha256s: dict[str, str] = {}
    transform_sha256s: dict[str, str] = {}

    character_revisions = ("char-rev-alice-v1", "char-rev-bob-v1")
    for person_index in (0, 1):
        instance_id = f"p{person_index}"
        owner_id = f"person-{person_index}"
        scene_instance_id = f"scene-duo-{instance_id}"
        character_revision = character_revisions[person_index]
        character_instance_id = f"char-inst-{character_revision}"
        package_id = f"pkg-duo-contact-{instance_id}"
        label = _LABEL

        ownership = masks[instance_id]
        ownership_path = write_binary_mask(workdir / f"ownership_{instance_id}.png", ownership)
        mask_encoded = ownership_path.read_bytes()
        mask_pixels = (ownership.astype(np.uint8) * 255).tobytes()
        ownership_sha256s[instance_id] = _sha256_bytes(mask_encoded)

        skeleton_raw = _skeleton_bytes(person_index, scene_instance_id)
        skeleton_path = workdir / f"skeleton_{instance_id}.json"
        skeleton_path.write_bytes(skeleton_raw)
        skeleton_sha256s[instance_id] = _sha256_bytes(skeleton_raw)

        chain = _transform_chain(person_index)
        transform_sha256s[instance_id] = chain["chain_sha256"]
        protected = _protected_region(
            person_index=person_index,
            owner_id=owner_id,
            scene_instance_id=scene_instance_id,
            character_revision=character_revision,
        )

        manifest = json.dumps(
            {
                "image_id": _IMAGE_ID,
                "person_index": person_index,
                "parts": {label: {"status": "human_approved_gold"}},
                "ownership_mask_sha256": ownership_sha256s[instance_id],
                "skeleton_sha256": skeleton_sha256s[instance_id],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        package_material = {
            "source_encoded_sha256": _sha256_bytes(source_encoded),
            "source_decoded_pixel_sha256": _sha256_bytes(source_pixels),
            "mask_encoded_sha256": _sha256_bytes(mask_encoded),
            "mask_decoded_sha256": _sha256_bytes(mask_pixels),
            "manifest_sha256": _sha256_bytes(manifest),
            "ontology_sha256": _sha256_bytes(ontology),
            "image_id": _IMAGE_ID,
            "person_index": person_index,
            "label": label,
        }
        package_sha256 = canonical_document_sha256(package_material)
        entry = {
            "image_id": _IMAGE_ID,
            "person_index": person_index,
            "label": label,
            "package_id": package_id,
            "package_revision": "rev-duo-1",
            "artifact_id": f"artifact-{instance_id}-{label}",
            "owner_id": owner_id,
            "scene_instance_id": scene_instance_id,
            "character_revision": character_revision,
            "character_instance_id": character_instance_id,
            "raw_part_status": "human_approved_gold",
            "ontology_version": "body_parts_v1",
            "ontology_sha256": _sha256_bytes(ontology),
            "source_encoded_sha256": package_material["source_encoded_sha256"],
            "source_decoded_pixel_sha256": package_material["source_decoded_pixel_sha256"],
            "mask_encoded_sha256": package_material["mask_encoded_sha256"],
            "mask_decoded_sha256": package_material["mask_decoded_sha256"],
            "manifest_sha256": package_material["manifest_sha256"],
            "package_sha256": package_sha256,
            "transform_chain_sha256": chain["chain_sha256"],
            "ownership_mask_sha256": ownership_sha256s[instance_id],
            "skeleton_sha256": skeleton_sha256s[instance_id],
            "protected_region_id": protected["region_id"],
        }
        catalog_packages.append(entry)

        request = {
            "image_id": _IMAGE_ID,
            "person_index": person_index,
            "label": label,
            "exact_use_scope": "diagnostic",
            "artifact_kind": "atomic",
            "ontology_version": "body_parts_v1",
            "raw_part_status": "human_approved_gold",
            "subject": {
                "canonical_person_id": owner_id,
                "scene_instance_id": scene_instance_id,
                "character_revision": character_revision,
            },
            "transform_chain": chain,
            "transform_probes": [
                {"x": 20.0 + person_index * 40.0, "y": 30.0, "coordinate_space": "source_pixel"}
            ],
            "protected_regions": [
                {
                    "region_id": protected["region_id"],
                    "owner": protected["owner"],
                    "box": protected["box"],
                }
            ],
            "expected_protected_regions": [
                {
                    "region_id": protected["region_id"],
                    "owner": protected["owner"],
                    "box": protected["expected_box"],
                }
            ],
        }
        evidence = {
            "catalog": {
                "adoption_decision": "adopted",
                "release_status": "adopted",
                "release_payload_sha256": _sha256_bytes(release),
                "capability_snapshot_sha256": _sha256_bytes(capability),
                "packages": [entry],
            },
            "package_root": str(workdir.resolve()),
            "relative_paths": {
                "source": "source.png",
                "mask": f"ownership_{instance_id}.png",
                "manifest": f"manifest_{instance_id}.json",
            },
            "bytes": {
                "source_encoded": source_encoded,
                "source_decoded_pixels": source_pixels,
                "mask_encoded": mask_encoded,
                "mask_decoded_pixels": mask_pixels,
                "manifest": manifest,
                "ontology": ontology,
                "release": release,
                "capability": capability,
                "revocation_identity": revocation,
            },
            "wrapper": None,
        }
        (workdir / f"manifest_{instance_id}.json").write_bytes(manifest)
        read_bundles[instance_id] = {"request": request, "evidence": evidence}
        persons.append(
            {
                "person_index": person_index,
                "instance_id": instance_id,
                "owner_id": owner_id,
                "scene_instance_id": scene_instance_id,
                "character_revision": character_revision,
                "character_instance_id": character_instance_id,
                "label": label,
                "package_id": package_id,
                "ownership_mask_sha256": ownership_sha256s[instance_id],
                "skeleton_sha256": skeleton_sha256s[instance_id],
                "transform_chain_sha256": transform_sha256s[instance_id],
                "protected_region_id": protected["region_id"],
            }
        )

    catalog = {
        "adoption_decision": "adopted",
        "release_status": "adopted",
        "release_payload_sha256": _sha256_bytes(release),
        "capability_snapshot_sha256": _sha256_bytes(capability),
        "packages": catalog_packages,
        "instance_context": "duo",
        "relationship_kind": "contact",
    }
    catalog_sha256 = canonical_document_sha256(catalog)
    revisions = {row["character_revision"] for row in persons}
    instances = {row["character_instance_id"] for row in persons}
    scenes = {row["scene_instance_id"] for row in persons}
    owners = {row["owner_id"] for row in persons}
    distinct = len(revisions) == 2 and len(instances) == 2 and len(scenes) == 2 and len(owners) == 2
    return {
        "image_id": _IMAGE_ID,
        "instance_context": "duo",
        "relationship_kind": "contact",
        "source_encoded_sha256": _sha256_bytes(source_encoded),
        "source_decoded_pixel_sha256": _sha256_bytes(source_pixels),
        "persons": persons,
        "distinct_character_instances": distinct,
        "catalog_sha256": catalog_sha256,
        "catalog": catalog,
        "read_bundles": read_bundles,
        "masks": masks,
        "ownership_mask_sha256s": ownership_sha256s,
        "skeleton_sha256s": skeleton_sha256s,
        "transform_chain_sha256s": transform_sha256s,
        "protected_region_count": 2,
    }


def evaluate_duo_mode_a_reads(fixture: Mapping[str, Any], *, decided_at: str) -> dict[str, Any]:
    """Evaluate Mode A package reads for both distinct person packages."""
    summaries: dict[str, Any] = {}
    for instance_id in ("p0", "p1"):
        bundle = fixture["read_bundles"][instance_id]
        decision = evaluate_mode_a_package_read(
            bundle["request"], bundle["evidence"], decided_at=decided_at
        )
        observed = _mapping(decision.get("observed"))
        handles = _mapping(decision.get("immutable_handles"))
        summaries[instance_id] = {
            "status": decision["status"],
            "person_index": observed.get("person_index"),
            "owner_id": observed.get("owner_id"),
            "scene_instance_id": observed.get("scene_instance_id"),
            "character_revision": observed.get("character_revision"),
            "package_id": handles.get("package_id"),
            "decision_sha256": decision["decision_sha256"],
            "transform_roundtrip_passed": observed.get("transform_roundtrip_passed"),
            "rejection_reasons": list(decision.get("rejection_reasons") or ()),
        }
    package_ids = {summaries["p0"]["package_id"], summaries["p1"]["package_id"]}
    return {
        "p0": {
            key: summaries["p0"][key]
            for key in (
                "status",
                "person_index",
                "owner_id",
                "scene_instance_id",
                "character_revision",
                "package_id",
                "decision_sha256",
                "transform_roundtrip_passed",
            )
        },
        "p1": {
            key: summaries["p1"][key]
            for key in (
                "status",
                "person_index",
                "owner_id",
                "scene_instance_id",
                "character_revision",
                "package_id",
                "decision_sha256",
                "transform_roundtrip_passed",
            )
        },
        "both_accepted": summaries["p0"]["status"] == "accepted"
        and summaries["p1"]["status"] == "accepted",
        "distinct_package_ids": None not in package_ids and len(package_ids) == 2,
        "_raw": summaries,
    }


def evaluate_duo_multi_person_gate(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Run the autonomous multi-person gate on overlapping/contact duo masks."""
    masks = fixture["masks"]
    inputs = MultiInstanceQcInputs(
        silhouettes={"p0": masks["p0"], "p1": masks["p1"]},
        atomic_unions={"p0": masks["p0"], "p1": masks["p1"]},
        contact_bands={
            ("p0", "p1"): masks["band_p0_p1"],
            ("p1", "p0"): masks["band_p1_p0"],
        },
        recorded_relationships={"p0": frozenset({"p1"}), "p1": frozenset({"p0"})},
        expected_promoted_count=2,
    )
    relationships = {("p0", "p1"): "contact", ("p1", "p0"): "contact"}
    result = evaluate_multi_person_candidate_gate(
        inputs,
        instance_context="duo",
        promoted_instances=("p0", "p1"),
        relationships=relationships,
    )
    payload = {
        "instance_context": result.instance_context,
        "promoted_instances": list(result.promoted_instances),
        "passed": result.passed,
        "blockers": list(result.blockers),
        "checks": [
            {"check_id": check.check_id, "passed": check.passed, "message": check.message}
            for check in result.checks
        ],
    }
    payload["gate_sha256"] = canonical_document_sha256(
        payload, excluded_top_level_fields=("gate_sha256",)
    )
    return {
        "instance_context": payload["instance_context"],
        "promoted_instances": payload["promoted_instances"],
        "passed": payload["passed"],
        "blockers": payload["blockers"],
        "gate_sha256": payload["gate_sha256"],
        "_checks": payload["checks"],
    }


def seed_wrong_person_rejection(fixture: Mapping[str, Any], *, decided_at: str) -> dict[str, Any]:
    """Inject a wrong-person subject swap and require Mode A fail-closed rejection."""
    bundle = copy.deepcopy(fixture["read_bundles"]["p0"])
    # Keep catalog owner as person-0; request claims person-1 identity.
    bundle["request"]["subject"]["canonical_person_id"] = "person-1"
    decision = evaluate_mode_a_package_read(
        bundle["request"], bundle["evidence"], decided_at=decided_at
    )
    reasons = list(decision.get("rejection_reasons") or ())
    rejected = decision.get("status") == "rejected" and "wrong_owner" in reasons
    return {
        "injected": True,
        "rejected": rejected,
        "blocking_reason_codes": reasons if reasons else ["wrong_owner"],
        "decision_sha256": decision["decision_sha256"],
    }


def seed_cross_instance_rejection(fixture: Mapping[str, Any], *, decided_at: str) -> dict[str, Any]:
    """Inject a cross-instance scene swap and require Mode A fail-closed rejection."""
    bundle = copy.deepcopy(fixture["read_bundles"]["p0"])
    # Keep owner; bind to the other person's scene instance.
    bundle["request"]["subject"]["scene_instance_id"] = "scene-duo-p1"
    decision = evaluate_mode_a_package_read(
        bundle["request"], bundle["evidence"], decided_at=decided_at
    )
    reasons = list(decision.get("rejection_reasons") or ())
    rejected = decision.get("status") == "rejected" and "instance_mismatch" in reasons
    return {
        "injected": True,
        "rejected": rejected,
        "blocking_reason_codes": reasons if reasons else ["instance_mismatch"],
        "decision_sha256": decision["decision_sha256"],
    }


def assess_zero_ownership_ambiguity(
    fixture: Mapping[str, Any], gate: Mapping[str, Any]
) -> dict[str, Any]:
    """Accepted duo path must show zero ownership ambiguity and reciprocal contact."""
    masks = fixture["masks"]
    overlap = int(np.count_nonzero(masks["p0"] & masks["p1"]))
    bleed_absent = overlap == 0 and "QC-035" not in gate.get("blockers", ())
    reciprocal = gate.get("passed") is True and "AUT-MP-002" not in gate.get("blockers", ())
    protected_ok = int(fixture.get("protected_region_count") or 0) >= 2
    zero_ambiguity = (
        bleed_absent
        and reciprocal
        and protected_ok
        and fixture.get("distinct_character_instances") is True
        and fixture["ownership_mask_sha256s"]["p0"] != fixture["ownership_mask_sha256s"]["p1"]
    )
    verdict = {
        "zero_ownership_ambiguity": zero_ambiguity,
        "cross_instance_bleed_absent": bleed_absent,
        "protected_region_violation_absent": protected_ok,
        "reciprocal_contact_present": reciprocal,
        "overlap_px": overlap,
    }
    verdict["verdict_sha256"] = canonical_document_sha256(
        verdict, excluded_top_level_fields=("verdict_sha256",)
    )
    return {
        "zero_ownership_ambiguity": verdict["zero_ownership_ambiguity"],
        "cross_instance_bleed_absent": verdict["cross_instance_bleed_absent"],
        "protected_region_violation_absent": verdict["protected_region_violation_absent"],
        "reciprocal_contact_present": verdict["reciprocal_contact_present"],
        "verdict_sha256": verdict["verdict_sha256"],
    }


def run_multi_person_mode_a_vertical_slice(
    workdir: Path | str,
    *,
    decided_at: str = _DECIDED_AT_DEFAULT,
    bind_fixture_main: bool | Path | Mapping[str, Any] = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run the producer-side overlapping/contact Mode A duo vertical slice."""
    policy = _policy()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    reasons: set[str] = set()

    fixture_binding: dict[str, Any] | None = None
    if bind_fixture_main is True:
        fixture_binding = load_fixture_main_binding(repo_root, decided_at=decided_at)
    elif isinstance(bind_fixture_main, Path):
        fixture_binding = load_fixture_main_binding(bind_fixture_main, decided_at=decided_at)
    elif isinstance(bind_fixture_main, Mapping):
        fixture_binding = dict(bind_fixture_main)

    fixture = build_overlapping_contact_duo_fixture(workdir / "fixture")
    if not fixture["distinct_character_instances"]:
        reasons.add("distinct_character_instances_missing")

    ownership_bound = (
        len(fixture["ownership_mask_sha256s"]) == 2
        and fixture["ownership_mask_sha256s"]["p0"] != fixture["ownership_mask_sha256s"]["p1"]
    )
    skeleton_bound = (
        len(fixture["skeleton_sha256s"]) == 2
        and fixture["skeleton_sha256s"]["p0"] != fixture["skeleton_sha256s"]["p1"]
    )
    transforms_bound = (
        len(fixture["transform_chain_sha256s"]) == 2
        and fixture["transform_chain_sha256s"]["p0"] != fixture["transform_chain_sha256s"]["p1"]
    )
    protected_bound = int(fixture["protected_region_count"]) >= 2
    if not ownership_bound:
        reasons.add("ownership_catalog_incomplete")
    if not skeleton_bound:
        reasons.add("skeleton_catalog_incomplete")
    if not protected_bound:
        reasons.add("protected_region_evidence_incomplete")
    if not transforms_bound:
        reasons.add("transform_evidence_incomplete")

    person_reads = evaluate_duo_mode_a_reads(fixture, decided_at=decided_at)
    if not person_reads["both_accepted"] or not person_reads["distinct_package_ids"]:
        reasons.add("mode_a_person_reads_incomplete")
    if any(person_reads[key].get("transform_roundtrip_passed") is not True for key in ("p0", "p1")):
        reasons.add("transform_evidence_incomplete")

    gate = evaluate_duo_multi_person_gate(fixture)
    if not gate["passed"]:
        reasons.add("multi_person_gate_failed")

    wrong_person = seed_wrong_person_rejection(fixture, decided_at=decided_at)
    if not wrong_person["rejected"]:
        reasons.add("wrong_person_fault_not_rejected")

    cross_instance = seed_cross_instance_rejection(fixture, decided_at=decided_at)
    if not cross_instance["rejected"]:
        reasons.add("cross_instance_fault_not_rejected")

    ambiguity = assess_zero_ownership_ambiguity(fixture, gate)
    if not ambiguity["zero_ownership_ambiguity"]:
        reasons.add("ownership_ambiguity_present")

    fixture_bound = bool(
        fixture_binding
        and fixture_binding.get("present")
        and fixture_binding.get("valid")
        and int(fixture_binding.get("person_binding_count") or 0) >= 2
        and fixture_binding.get("main_adapter_execution_receipt_present") is True
        and fixture_binding.get("comfyui_result_history_present") is True
    )
    if fixture_binding is not None and fixture_binding.get("present") and not fixture_bound:
        reasons.add("fixture_main_binding_invalid")
    if not fixture_bound:
        # Honest external blockers: no adopted Main/ComfyUI transaction on this path.
        reasons.add("adopted_package_transaction_absent")
        reasons.add("main_adapter_execution_absent")

    external_blockers = {
        "adopted_package_transaction_absent",
        "main_adapter_execution_absent",
    }
    producer_ok = not (reasons - external_blockers)
    if fixture_bound and producer_ok and not reasons:
        status = "accepted"
    elif producer_ok:
        status = "producer_partial"
    else:
        status = "rejected"
    ordered = _ordered(policy, reasons)
    if status == "accepted" and not ordered:
        ordered = ["eligible"]

    evidence = {
        "schema_version": "1.0.0",
        "record_type": "multi_person_mode_a_vertical_slice_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "fixture_truth_tier": "synthetic_contract_fixture",
        "status": status,
        "rejection_reasons": ordered,
        "package_fixture": {
            "image_id": fixture["image_id"],
            "instance_context": fixture["instance_context"],
            "relationship_kind": fixture["relationship_kind"],
            "source_encoded_sha256": fixture["source_encoded_sha256"],
            "source_decoded_pixel_sha256": fixture["source_decoded_pixel_sha256"],
            "persons": fixture["persons"],
            "distinct_character_instances": fixture["distinct_character_instances"],
            "catalog_sha256": fixture["catalog_sha256"],
        },
        "person_reads": {
            "p0": person_reads["p0"],
            "p1": person_reads["p1"],
            "both_accepted": person_reads["both_accepted"],
            "distinct_package_ids": person_reads["distinct_package_ids"],
        },
        "ownership_evidence": {
            "ownership_masks_bound": ownership_bound,
            "skeleton_catalog_bound": skeleton_bound,
            "protected_regions_bound": protected_bound,
            "transform_chains_bound": transforms_bound,
            "ownership_mask_sha256s": fixture["ownership_mask_sha256s"],
            "skeleton_sha256s": fixture["skeleton_sha256s"],
            "protected_region_count": fixture["protected_region_count"],
            "transform_chain_sha256s": fixture["transform_chain_sha256s"],
        },
        "multi_person_gate": {
            "instance_context": gate["instance_context"],
            "promoted_instances": gate["promoted_instances"],
            "passed": gate["passed"],
            "blockers": gate["blockers"],
            "gate_sha256": gate["gate_sha256"],
        },
        "seeded_faults": {
            "wrong_person": {
                "injected": True,
                "rejected": wrong_person["rejected"],
                "blocking_reason_codes": wrong_person["blocking_reason_codes"],
                "decision_sha256": wrong_person["decision_sha256"],
            },
            "cross_instance": {
                "injected": True,
                "rejected": cross_instance["rejected"],
                "blocking_reason_codes": cross_instance["blocking_reason_codes"],
                "decision_sha256": cross_instance["decision_sha256"],
            },
        },
        "ambiguity_verdict": ambiguity,
        "external_probe": {
            "adopted_package_transaction": fixture_bound,
            "main_adapter_execution": fixture_bound,
            "downstream_comfyui_result_history": fixture_bound,
            "authority_kind": "fixture_authority" if fixture_bound else None,
            "detail": (
                "Fixture Main duo adapter/ComfyUI receipts bound under fixture_authority."
                if fixture_bound
                else (
                    "Producer fixture path only. MF-P6-12.02 adopted single-person "
                    "Main/ComfyUI transaction and pinned adapter execution remain open."
                )
            ),
        },
        "claim_boundary": {
            "producer_fixture_slice_complete": producer_ok
            and status in {"producer_partial", "accepted"},
            "mf_p6_12_02_prerequisite_complete": False,
            "main_adapter_execution_complete": False,
            "mf_p6_12_03_complete": False,
            "fixture_main_bound": fixture_bound,
            "independent_real_accuracy_claim": False,
            "notes": (
                "Producer fixture covers overlapping/contact duo Mode A reads, "
                "ownership/skeleton/protected/transform evidence, multi-person gate "
                "pass, seeded wrong-person/cross-instance rejection, and zero "
                "ownership-ambiguity verdict. Fixture Main may bind synthetic duo "
                "adapter/ComfyUI receipts without claiming production adoption or "
                "independent_real_accuracy."
            ),
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_multi_person_mode_a_vertical_slice_evidence(
    evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and producer claim boundaries."""
    issues: list[str] = []
    try:
        policy = _policy()
    except MultiPersonModeAVerticalSliceError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["reason_codes"])
    reasons = evidence.get("rejection_reasons")
    if not isinstance(reasons, list) or not set(reasons).issubset(allowed):
        issues.append("decision_reason_code")
    claim = _mapping(evidence.get("claim_boundary"))
    if claim.get("mf_p6_12_03_complete") is True:
        issues.append("completion_overclaim")
    if claim.get("main_adapter_execution_complete") is True:
        issues.append("main_execution_overclaim")
    if claim.get("independent_real_accuracy_claim") is True:
        issues.append("independent_real_accuracy_overclaim")
    fixture_bound = claim.get("fixture_main_bound") is True
    probe = _mapping(evidence.get("external_probe"))
    if fixture_bound:
        if probe.get("authority_kind") != "fixture_authority":
            issues.append("fixture_main_authority_missing")
        if probe.get("main_adapter_execution") is not True:
            issues.append("fixture_main_adapter_unbound")
    elif probe.get("main_adapter_execution") is True:
        issues.append("main_execution_overclaim")
    faults = _mapping(evidence.get("seeded_faults"))
    for name in ("wrong_person", "cross_instance"):
        fault = _mapping(faults.get(name))
        if fault.get("injected") is not True or fault.get("rejected") is not True:
            issues.append(f"{name}_not_rejected")
    if evidence.get("ambiguity_verdict", {}).get("zero_ownership_ambiguity") is not True:
        if evidence.get("status") == "producer_partial":
            issues.append("ambiguity_incoherent")
    return tuple(sorted(set(issues)))


__all__ = [
    "MultiPersonModeAVerticalSliceError",
    "assess_zero_ownership_ambiguity",
    "build_overlapping_contact_duo_fixture",
    "evaluate_duo_mode_a_reads",
    "evaluate_duo_multi_person_gate",
    "run_multi_person_mode_a_vertical_slice",
    "seed_cross_instance_rejection",
    "seed_wrong_person_rejection",
    "validate_multi_person_mode_a_vertical_slice_evidence",
]
