"""Additive canonical identity decisions for bridge record sets."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from maskfactory.validation import ValidationIssue, canonical_document_sha256, validate_document

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_identity_policy.yaml"
POLICY_ID = "maskfactory-bridge-canonical-identity-v1"
COLLISION_CODES = (
    "assignment_evidence_drift",
    "character_revision_collision",
    "duplicate_intent_collision",
    "provider_person_index_collision",
    "artifact_identity_collision",
    "idempotency_replay_collision",
)


def _issue(pointer: str, validator: str, message: str) -> ValidationIssue:
    return ValidationIssue(pointer=pointer, validator=validator, message=message)


def _policy_sha256() -> str:
    return hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def _subset(document: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: document.get(field) for field in fields}


def _owner_identity(owner: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        owner.get("owner_kind"),
        owner.get("entity_id"),
        owner.get("scene_instance_id"),
        owner.get("canonical_person_id"),
        owner.get("person_index"),
    )


def _validate_decoder(decoder: object, issues: list[ValidationIssue]) -> Mapping[str, Any]:
    if not isinstance(decoder, Mapping):
        issues.append(
            _issue(
                "/source/decoder", "identity_decoder_drift", "source decoder identity is required"
            )
        )
        return {}
    decoder_id = decoder.get("decoder_id")
    version = decoder.get("version")
    binary = decoder.get("binary_sha256")
    if (
        not isinstance(decoder_id, str)
        or not decoder_id
        or not isinstance(version, str)
        or not version
        or not isinstance(binary, str)
        or len(binary) != 64
    ):
        issues.append(
            _issue(
                "/source/decoder",
                "identity_decoder_drift",
                "decoder id, version, and binary hash must be fully bound",
            )
        )
    return decoder


def _validate_time_identity(
    source: Mapping[str, Any], media_scope: object, issues: list[ValidationIssue]
) -> None:
    if not isinstance(media_scope, Mapping):
        issues.append(
            _issue("/media_scope", "identity_time_drift", "media scope time identity is required")
        )
        return
    scope_kind = media_scope.get("scope_kind")
    extraction = source.get("frame_extraction")
    if scope_kind == "still_image":
        if extraction is not None:
            issues.append(
                _issue(
                    "/source/frame_extraction",
                    "identity_time_drift",
                    "still_image identity cannot carry frame extraction facts",
                )
            )
        return
    if scope_kind not in {"video_frame", "video_span"}:
        issues.append(
            _issue("/media_scope/scope_kind", "identity_time_drift", "unsupported media scope kind")
        )
        return
    if not isinstance(extraction, Mapping):
        issues.append(
            _issue(
                "/source/frame_extraction",
                "identity_time_drift",
                "video media scope requires frame extraction time identity",
            )
        )
        return
    time_fields = (
        "source_video_sha256",
        "frame_index",
        "pts",
        "timebase_numerator",
        "timebase_denominator",
    )
    if any(media_scope.get(field) != extraction.get(field) for field in time_fields):
        issues.append(
            _issue(
                "/media_scope",
                "identity_time_drift",
                "media scope time identity drifted from frame extraction identity",
            )
        )
    if media_scope.get("decoded_frame_sha256") != source.get("decoded_pixel_sha256"):
        issues.append(
            _issue(
                "/media_scope/decoded_frame_sha256",
                "identity_time_drift",
                "decoded frame identity drifted from canonical decoded source pixels",
            )
        )


def _validate_owners(
    request: Mapping[str, Any],
    request_subject: Mapping[str, Any],
    artifacts: Iterable[Mapping[str, Any]],
    issues: list[ValidationIssue],
) -> list[Mapping[str, Any]]:
    roster = request.get("protected_owner_roster")
    if not isinstance(roster, list) or not roster:
        issues.append(
            _issue(
                "/protected_owner_roster",
                "identity_owner_omitted",
                "declared owner roster is required and cannot be empty",
            )
        )
        roster = []
    owners: list[Mapping[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    person_indexes: set[Any] = set()
    scene_instances: set[Any] = set()
    canonical_people: set[Any] = set()
    for index, row in enumerate(roster):
        if not isinstance(row, Mapping):
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}",
                    "identity_owner_ambiguous",
                    "owner roster entries must be objects",
                )
            )
            continue
        owner = row.get("owner")
        if not isinstance(owner, Mapping):
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}/owner",
                    "identity_owner_omitted",
                    "owner roster entry is missing an owner binding",
                )
            )
            continue
        key = _owner_identity(owner)
        if None in key or "" in key:
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}/owner",
                    "identity_owner_omitted",
                    "owner roster entry omits required identity fields",
                )
            )
        if key in seen_keys or owner.get("person_index") in person_indexes:
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}/owner",
                    "identity_owner_ambiguous",
                    "owner roster reuses person index or owner identity",
                )
            )
        if owner.get("scene_instance_id") in scene_instances:
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}/owner",
                    "identity_owner_ambiguous",
                    "owner roster reuses scene_instance_id",
                )
            )
        if owner.get("canonical_person_id") in canonical_people:
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}/owner",
                    "identity_owner_ambiguous",
                    "owner roster reuses canonical_person_id",
                )
            )
        seen_keys.add(key)
        person_indexes.add(owner.get("person_index"))
        scene_instances.add(owner.get("scene_instance_id"))
        canonical_people.add(owner.get("canonical_person_id"))
        owners.append(owner)
    # Subject must appear in the roster under matching scene/person indexes.
    if not any(
        owner.get("scene_instance_id") == request_subject.get("scene_instance_id")
        and owner.get("canonical_person_id") == request_subject.get("canonical_person_id")
        and owner.get("person_index") == request_subject.get("person_index")
        for owner in owners
    ):
        issues.append(
            _issue(
                "/subject",
                "identity_owner_omitted",
                "request subject is omitted from the declared owner roster",
            )
        )
    for artifact_index, artifact in enumerate(artifacts):
        owner = artifact.get("owner")
        if not isinstance(owner, Mapping):
            issues.append(
                _issue(
                    f"/artifacts/{artifact_index}/owner",
                    "identity_owner_omitted",
                    "mask artifact owner is omitted",
                )
            )
            continue
        if not any(
            owner.get("scene_instance_id") == roster_owner.get("scene_instance_id")
            and owner.get("canonical_person_id") == roster_owner.get("canonical_person_id")
            and owner.get("person_index") == roster_owner.get("person_index")
            for roster_owner in owners
        ):
            issues.append(
                _issue(
                    f"/artifacts/{artifact_index}/owner",
                    "identity_owner_ambiguous",
                    "mask artifact owner is not uniquely bound in the declared roster",
                )
            )
    return owners


def assignment_evidence_sha256(subject: Mapping[str, Any]) -> str:
    """Recompute the assignment proof from identity and normalized observations."""
    evidence = subject.get("assignment_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("subject.assignment_evidence is required")
    return canonical_document_sha256(
        {
            "mapping_id": evidence.get("mapping_id"),
            "status": evidence.get("status"),
            "bbox_sha256": evidence.get("bbox_sha256"),
            "skeleton_sha256": evidence.get("skeleton_sha256"),
            "silhouette_sha256": evidence.get("silhouette_sha256"),
            "depth_sha256": evidence.get("depth_sha256"),
            "scene_instance_id": subject.get("scene_instance_id"),
            "canonical_person_id": subject.get("canonical_person_id"),
            "provider_person_index": subject.get("provider_person_index"),
        }
    )


def canonical_identity_record(
    request: Mapping[str, Any], receipt: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    """Normalize one exchange and prove its derived assignment evidence."""
    request_subject = request.get("subject")
    receipt_subject = receipt.get("subject_binding")
    source = request.get("source")
    receipt_source = receipt.get("source_binding")
    if not all(
        isinstance(value, Mapping)
        for value in (request_subject, receipt_subject, source, receipt_source)
    ):
        return {}, (
            _issue(
                "/", "identity_exchange_shape", "request and receipt identity bindings are required"
            ),
        )

    issues: list[ValidationIssue] = []
    try:
        recomputed_assignment = assignment_evidence_sha256(request_subject)
    except ValueError:
        recomputed_assignment = ""
        issues.append(
            _issue(
                "/subject/assignment_evidence",
                "assignment_evidence_shape",
                "assignment evidence must contain a normalized mapping",
            )
        )
    declared_assignment = request_subject.get("assignment_evidence", {}).get("mapping_sha256")
    if declared_assignment != recomputed_assignment:
        issues.append(
            _issue(
                "/subject/assignment_evidence/mapping_sha256",
                "assignment_evidence_recomputed",
                "declared assignment evidence hash does not match normalized assignment evidence",
            )
        )
    if receipt_subject.get("assignment_evidence_sha256") != recomputed_assignment:
        issues.append(
            _issue(
                "/subject_binding/assignment_evidence_sha256",
                "assignment_evidence_receipt_binding",
                "receipt assignment evidence hash does not match the recomputed request evidence",
            )
        )

    fields = (
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
    if _subset(request_subject, fields) != _subset(receipt_subject, fields):
        issues.append(
            _issue(
                "/subject_binding",
                "identity_subject_binding",
                "receipt subject does not exactly preserve the request subject identity",
            )
        )
    source_fields = ("encoded_sha256", "decoded_pixel_sha256")
    if _subset(source, source_fields) != _subset(receipt_source, source_fields):
        issues.append(
            _issue(
                "/source_binding",
                "identity_pixel_drift",
                "receipt source does not exactly preserve encoded and decoded source identities",
            )
        )
    encoded = source.get("encoded_sha256")
    decoded = source.get("decoded_pixel_sha256")
    if (
        not isinstance(encoded, str)
        or len(encoded) != 64
        or not isinstance(decoded, str)
        or len(decoded) != 64
    ):
        issues.append(
            _issue(
                "/source",
                "identity_pixel_drift",
                "encoded and decoded source pixel identities must be fully bound",
            )
        )

    decoder = _validate_decoder(source.get("decoder"), issues)
    receipt_decoder = {
        "decoder_id": receipt_source.get("decoder_id"),
        "version": receipt_source.get("decoder_version"),
        "binary_sha256": receipt_source.get("decoder_binary_sha256"),
    }
    if decoder and any(
        decoder.get(field) != receipt_decoder.get(field)
        for field in ("decoder_id", "version", "binary_sha256")
    ):
        issues.append(
            _issue(
                "/source_binding",
                "identity_decoder_drift",
                "receipt decoder identity drifted from the request source decoder",
            )
        )
    _validate_time_identity(source, request.get("media_scope"), issues)
    receipt_artifacts = [
        artifact for artifact in receipt.get("artifacts") or () if isinstance(artifact, Mapping)
    ]
    _validate_owners(request, request_subject, receipt_artifacts, issues)
    execution = _subset(
        request,
        ("project_id", "run_id", "job_id", "pass_id", "attempt_id", "attempt_number"),
    )
    execution["hypothesis_id"] = (request.get("hypothesis") or {}).get("hypothesis_id")
    lineage = receipt.get("lineage") if isinstance(receipt.get("lineage"), Mapping) else {}
    record = {
        "request_payload_sha256": request.get("request_payload_sha256"),
        "receipt_payload_sha256": receipt.get("receipt_payload_sha256"),
        "idempotency_key": request.get("idempotency_key"),
        "execution": execution,
        "source": {
            "encoded_sha256": source.get("encoded_sha256"),
            "decoded_pixel_sha256": source.get("decoded_pixel_sha256"),
            "decoder_id": decoder.get("decoder_id"),
            "decoder_version": decoder.get("version"),
            "decoder_binary_sha256": decoder.get("binary_sha256"),
        },
        "media_scope": request.get("media_scope"),
        "subject": _subset(request_subject, fields),
        "assignment_evidence_sha256": recomputed_assignment,
        "package": _subset(lineage, ("package_id", "package_revision", "package_manifest_sha256")),
        "owner_roster": sorted(
            (request.get("protected_owner_roster") or ()),
            key=lambda item: canonical_document_sha256(item) if isinstance(item, Mapping) else "",
        ),
        "intents": sorted(
            (
                _subset(
                    intent,
                    ("intent_id", "label", "artifact_kind", "purpose", "target_coordinate_space"),
                )
                for intent in request.get("mask_intents") or ()
                if isinstance(intent, Mapping)
            ),
            key=lambda item: item.get("intent_id") or "",
        ),
        "artifacts": sorted(
            (
                {
                    **_subset(
                        artifact,
                        (
                            "artifact_id",
                            "intent_id",
                            "artifact_identity_sha256",
                            "encoded_sha256",
                            "decoded_mask_sha256",
                        ),
                    ),
                    "owner": artifact.get("owner"),
                }
                for artifact in receipt_artifacts
            ),
            key=lambda item: item.get("artifact_identity_sha256") or "",
        ),
    }
    record["record_sha256"] = canonical_document_sha256(record)
    return record, tuple(sorted(set(issues)))


def _key_sha256(value: object) -> str:
    return canonical_document_sha256({"key": value})


def _collision(code: str, key: object, records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "code": code,
        "key_sha256": _key_sha256(key),
        "record_sha256s": sorted({record["record_sha256"] for record in records}),
    }


def _collisions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[tuple[Any, ...], list[dict[str, Any]]]] = {
        code: defaultdict(list) for code in COLLISION_CODES
    }
    for record in records:
        execution = record["execution"]
        source = record["source"]
        subject = record["subject"]
        scope = (
            execution["project_id"],
            execution["run_id"],
            execution["job_id"],
            execution["pass_id"],
            source["decoded_pixel_sha256"],
            subject["scene_id"],
            subject["shot_id"],
            subject["take_id"],
        )
        groups["assignment_evidence_drift"][
            scope + (subject["scene_instance_id"], subject["canonical_person_id"])
        ].append(record)
        groups["character_revision_collision"][scope + (subject["scene_instance_id"],)].append(
            record
        )
        groups["provider_person_index_collision"][
            scope + (subject["provider_person_index"],)
        ].append(record)
        groups["idempotency_replay_collision"][(record["idempotency_key"],)].append(record)
        for intent in record["intents"]:
            groups["duplicate_intent_collision"][
                scope
                + (
                    subject["scene_instance_id"],
                    subject["canonical_person_id"],
                    intent["intent_id"],
                )
            ].append(record)
        for artifact in record["artifacts"]:
            groups["artifact_identity_collision"][(artifact["artifact_identity_sha256"],)].append(
                record
            )

    collisions: list[dict[str, Any]] = []
    for code, grouped in groups.items():
        for key, members in grouped.items():
            unique = {member["record_sha256"]: member for member in members}
            if len(unique) < 2:
                continue
            if code == "assignment_evidence_drift":
                values = {member["assignment_evidence_sha256"] for member in unique.values()}
            elif code == "character_revision_collision":
                values = {member["subject"]["character_revision"] for member in unique.values()}
            elif code == "provider_person_index_collision":
                values = {member["subject"]["canonical_person_id"] for member in unique.values()}
            elif code == "artifact_identity_collision":
                values = {
                    canonical_document_sha256(
                        next(
                            artifact
                            for artifact in member["artifacts"]
                            if artifact["artifact_identity_sha256"] == key[0]
                        )
                    )
                    for member in unique.values()
                }
            else:
                values = {member["record_sha256"] for member in unique.values()}
            if len(values) > 1:
                collisions.append(_collision(code, key, unique.values()))
    return sorted(collisions, key=lambda item: (item["code"], item["key_sha256"]))


def build_bridge_identity_decision(
    exchanges: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    """Build an order-invariant, fail-closed decision for exchange history."""
    records: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    for index, (request, receipt) in enumerate(exchanges):
        record, record_issues = canonical_identity_record(request, receipt)
        records.append(record)
        issues.extend(
            ValidationIssue(
                pointer=f"/{index}{issue.pointer}",
                validator=issue.validator,
                message=issue.message,
            )
            for issue in record_issues
        )
    unique_records = {record["record_sha256"]: record for record in records if record}
    normalized_records = [unique_records[key] for key in sorted(unique_records)]
    collisions = _collisions(normalized_records)
    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_identity_decision",
        "policy_id": POLICY_ID,
        "policy_sha256": _policy_sha256(),
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["decision_sha256"],
        },
        "decision_scope_sha256": canonical_document_sha256(
            {"record_sha256s": sorted(unique_records)}
        ),
        "records": normalized_records,
        "replay_count": len(records) - len(normalized_records),
        "status": "rejected" if issues or collisions else "accepted",
        "collisions": collisions,
        "rejection_reasons": sorted({issue.validator for issue in issues}),
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision, tuple(sorted(set(issues)))


def validate_bridge_identity_set(
    exchanges: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> tuple[ValidationIssue, ...]:
    """Reject invalid assignment bindings and all cross-record identity collisions."""
    decision, issues = build_bridge_identity_decision(exchanges)
    findings = list(issues)
    if decision["status"] == "rejected":
        findings.extend(
            _issue(
                "/collisions",
                collision["code"],
                "canonical identity record set contains a prohibited collision",
            )
            for collision in decision["collisions"]
        )
    return tuple(sorted(set(findings)))


def validate_bridge_identity_decision(
    decision: Mapping[str, Any],
) -> tuple[ValidationIssue, ...]:
    """Validate a materialized decision, including policy and self-hash bindings."""
    issues = list(validate_document(decision, "bridge_identity_decision"))
    if decision.get("policy_sha256") != _policy_sha256():
        issues.append(_issue("/policy_sha256", "identity_policy_hash", "policy bytes drifted"))
    expected_hash = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    if decision.get("decision_sha256") != expected_hash:
        issues.append(
            _issue("/decision_sha256", "identity_decision_hash", "decision hash mismatch")
        )
    if decision.get("status") == "accepted" and (
        decision.get("collisions") or decision.get("rejection_reasons")
    ):
        issues.append(
            _issue(
                "/status",
                "identity_status_collision",
                "accepted decisions cannot contain collisions or rejection reasons",
            )
        )
    if decision.get("status") == "rejected" and not (
        decision.get("collisions") or decision.get("rejection_reasons")
    ):
        issues.append(
            _issue("/status", "identity_status_rejection", "rejected decisions require a collision")
        )
    return tuple(sorted(set(issues)))
