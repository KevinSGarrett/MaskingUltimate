"""Fail-closed autonomous role, retrieval, tool, critic, and memory controls.

Model text is untrusted input.  This module authorizes only a closed JSON
proposal produced by an exact qualified stack over a hash-bound context.  It
never executes tools and never promotes observations into authority.  Critic
quorum counts independent model families, not endpoints, checkpoints, or
prompt variants.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from maskfactory.validation import canonical_json_bytes

CONTROL_VERSION = "1.0.0"
ROLE_OUTPUT_KEYS = frozenset(
    {
        "schema_version",
        "role",
        "stack_identity_sha256",
        "decision",
        "confidence",
        "citations",
        "tool_call",
        "uncertainty",
    }
)
TOOL_CALL_KEYS = frozenset({"tool_id", "arguments", "idempotency_key"})
ALLOWED_ROLES = frozenset(
    {
        "request_normalizer",
        "planner_diagnostician",
        "router_adviser",
        "repair_proposer",
        "visual_critic",
        "evidence_summarizer",
    }
)
AUTHORITY_RECORD_KINDS = frozenset(
    {"adopted_release", "active_policy", "qualified_route", "runtime_evidence"}
)
NONAUTHORITATIVE_RECORD_KINDS = frozenset({"conversation_cache", "model_output", "free_form_note"})
CRITIC_STATUSES = frozenset({"pass", "fail", "uncertain", "missing", "malformed", "timeout"})
EVENT_KEYS = frozenset(
    {
        "event_version",
        "stream_id",
        "sequence",
        "created_at",
        "event_type",
        "previous_event_sha256",
        "payload",
        "payload_sha256",
        "authority_effect",
        "event_sha256",
    }
)
EVENT_TYPES = frozenset(
    {"context_built", "role_evaluated", "critic_quorum", "tool_authorized", "abstained"}
)


class IntelligenceControlError(ValueError):
    """An intelligence artifact or durable event violated the closed contract."""


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise IntelligenceControlError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise IntelligenceControlError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _require_sha(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise IntelligenceControlError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True)
class RoleStackIdentity:
    stack_id: str
    role: str
    model_family: str
    model_revision: str
    runtime_sha256: str
    prompt_sha256: str
    parser_sha256: str
    tool_policy_sha256: str
    qualification_scope_sha256: str
    qualification_certificate_sha256: str
    qualified_until: str
    lifecycle_state: str = "active"

    def __post_init__(self) -> None:
        if self.role not in ALLOWED_ROLES:
            raise IntelligenceControlError("role stack has unsupported role")
        if any(
            not isinstance(value, str) or not value
            for value in (self.stack_id, self.model_family, self.model_revision)
        ):
            raise IntelligenceControlError("role stack identity fields are incomplete")
        for field in (
            "runtime_sha256",
            "prompt_sha256",
            "parser_sha256",
            "tool_policy_sha256",
            "qualification_scope_sha256",
            "qualification_certificate_sha256",
        ):
            _require_sha(getattr(self, field), field)
        _parse_time(self.qualified_until)

    @property
    def identity_sha256(self) -> str:
        return _sha(
            {
                "stack_id": self.stack_id,
                "role": self.role,
                "model_family": self.model_family,
                "model_revision": self.model_revision,
                "runtime_sha256": self.runtime_sha256,
                "prompt_sha256": self.prompt_sha256,
                "parser_sha256": self.parser_sha256,
                "tool_policy_sha256": self.tool_policy_sha256,
                "qualification_scope_sha256": self.qualification_scope_sha256,
                "qualification_certificate_sha256": self.qualification_certificate_sha256,
                "qualified_until": self.qualified_until,
                "lifecycle_state": self.lifecycle_state,
            }
        )

    def is_qualified_at(self, at_time: str) -> bool:
        return self.lifecycle_state == "active" and _parse_time(at_time) < _parse_time(
            self.qualified_until
        )


@dataclass(frozen=True)
class RegistryRecord:
    record_id: str
    record_kind: str
    payload: Mapping[str, Any]
    payload_sha256: str

    def __post_init__(self) -> None:
        if not self.record_id:
            raise IntelligenceControlError("registry record ID is required")
        if self.record_kind not in AUTHORITY_RECORD_KINDS | NONAUTHORITATIVE_RECORD_KINDS:
            raise IntelligenceControlError("registry record kind is unsupported")
        _require_sha(self.payload_sha256, "payload_sha256")
        if self.payload_sha256 != _sha(self.payload):
            raise IntelligenceControlError("registry record payload hash mismatch")

    @property
    def may_support_authority(self) -> bool:
        return self.record_kind in AUTHORITY_RECORD_KINDS


def make_registry_record(
    record_id: str, record_kind: str, payload: Mapping[str, Any]
) -> RegistryRecord:
    return RegistryRecord(record_id, record_kind, dict(payload), _sha(payload))


@dataclass(frozen=True)
class Citation:
    record_id: str
    payload_sha256: str

    def __post_init__(self) -> None:
        if not self.record_id:
            raise IntelligenceControlError("citation record ID is required")
        _require_sha(self.payload_sha256, "citation payload_sha256")


@dataclass(frozen=True)
class ToolContract:
    tool_id: str
    role: str
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...]
    argument_types: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.tool_id or self.role not in ALLOWED_ROLES:
            raise IntelligenceControlError("tool contract identity is invalid")
        all_arguments = (*self.required_arguments, *self.optional_arguments)
        if len(all_arguments) != len(set(all_arguments)):
            raise IntelligenceControlError("tool contract arguments must be unique")
        if set(self.argument_types) != set(all_arguments):
            raise IntelligenceControlError("tool argument types must cover the exact key set")
        if not set(self.argument_types.values()) <= {
            "string",
            "array",
            "object",
            "number",
            "integer",
            "boolean",
        }:
            raise IntelligenceControlError("tool contract argument type is unsupported")

    def as_document(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "role": self.role,
            "required_arguments": list(self.required_arguments),
            "optional_arguments": list(self.optional_arguments),
            "argument_types": dict(sorted(self.argument_types.items())),
        }

    @property
    def contract_sha256(self) -> str:
        return _sha(self.as_document())


def tool_policy_sha256(contracts: Iterable[ToolContract]) -> str:
    documents = [contract.as_document() for contract in contracts]
    return _sha(sorted(documents, key=lambda row: (row["role"], row["tool_id"])))


def _argument_has_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


@dataclass(frozen=True)
class ContextBundle:
    bundle_id: str
    records: tuple[RegistryRecord, ...]
    required_record_ids: tuple[str, ...]
    retained_record_ids: tuple[str, ...]
    dropped_record_ids: tuple[str, ...]
    compaction_manifest: Mapping[str, Any]
    authority_complete: bool
    blockers: tuple[str, ...]

    @property
    def bundle_sha256(self) -> str:
        return _sha(
            {
                "bundle_id": self.bundle_id,
                "records": [
                    {
                        "record_id": record.record_id,
                        "record_kind": record.record_kind,
                        "payload_sha256": record.payload_sha256,
                    }
                    for record in self.records
                    if record.record_id in self.retained_record_ids
                ],
                "required_record_ids": list(self.required_record_ids),
                "compaction_manifest": self.compaction_manifest,
                "authority_complete": self.authority_complete,
                "blockers": list(self.blockers),
            }
        )

    def record_map(self) -> dict[str, RegistryRecord]:
        return {
            record.record_id: record
            for record in self.records
            if record.record_id in self.retained_record_ids
        }


def build_context_bundle(
    *,
    bundle_id: str,
    records: Sequence[RegistryRecord],
    required_record_ids: Sequence[str],
    retained_record_ids: Sequence[str] | None = None,
) -> ContextBundle:
    if not bundle_id:
        raise IntelligenceControlError("context bundle ID is required")
    if len({record.record_id for record in records}) != len(records):
        raise IntelligenceControlError("context registry record IDs must be unique")
    record_map = {record.record_id: record for record in records}
    required = tuple(sorted(set(required_record_ids)))
    retained = tuple(
        sorted(record_map if retained_record_ids is None else set(retained_record_ids))
    )
    unknown_retained = sorted(set(retained) - set(record_map))
    missing_required = sorted(set(required) - set(record_map))
    dropped = tuple(sorted(set(record_map) - set(retained)))
    dropped_required = sorted(set(required) - set(retained))
    nonauthority_required = sorted(
        record_id
        for record_id in required
        if record_id in record_map and not record_map[record_id].may_support_authority
    )
    blockers = [
        *(f"unknown_retained:{record_id}" for record_id in unknown_retained),
        *(f"missing_required:{record_id}" for record_id in missing_required),
        *(f"dropped_required:{record_id}" for record_id in dropped_required),
        *(f"nonauthority_required:{record_id}" for record_id in nonauthority_required),
    ]
    manifest = {
        "manifest_version": CONTROL_VERSION,
        "retained_record_ids": list(retained),
        "dropped_record_ids": list(dropped),
        "required_record_ids": list(required),
        "retained_record_sha256s": {
            record_id: record_map[record_id].payload_sha256
            for record_id in retained
            if record_id in record_map
        },
        "dropped_required_record_ids": dropped_required,
    }
    manifest["manifest_sha256"] = _sha(manifest)
    return ContextBundle(
        bundle_id,
        tuple(records),
        required,
        retained,
        dropped,
        manifest,
        not blockers,
        tuple(blockers),
    )


@dataclass(frozen=True)
class RoleDecision:
    status: str
    role: str
    confidence: float
    proposal: Mapping[str, Any] | None
    citations: tuple[str, ...]
    uncertainty: tuple[str, ...]
    blockers: tuple[str, ...]
    context_bundle_sha256: str
    stack_identity_sha256: str
    tool_authorized: bool = False
    may_execute_tool: bool = False
    may_promote_authority: bool = False


def evaluate_role_output(
    raw_output: str,
    *,
    stack: RoleStackIdentity,
    context: ContextBundle,
    tool_contracts: Mapping[str, ToolContract],
    at_time: str,
) -> RoleDecision:
    """Parse and authorize one proposal without executing it or granting authority."""
    blockers: list[str] = []
    try:
        document = json.loads(raw_output)
    except (TypeError, json.JSONDecodeError):
        document = {}
        blockers.append("free_form_or_invalid_json")
    if not isinstance(document, dict) or set(document) != ROLE_OUTPUT_KEYS:
        blockers.append("role_output_schema")
        document = document if isinstance(document, dict) else {}
    if document.get("schema_version") != CONTROL_VERSION:
        blockers.append("role_output_version")
    if document.get("role") != stack.role:
        blockers.append("role_mismatch")
    if document.get("stack_identity_sha256") != stack.identity_sha256:
        blockers.append("stack_identity_mismatch")
    if not stack.is_qualified_at(at_time):
        blockers.append("stack_not_currently_qualified")
    applicable_contracts = tuple(
        contract for contract in tool_contracts.values() if contract.role == stack.role
    )
    if stack.tool_policy_sha256 != tool_policy_sha256(applicable_contracts):
        blockers.append("tool_policy_binding_mismatch")
    if not context.authority_complete:
        blockers.extend(context.blockers)
    confidence = document.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        blockers.append("confidence_invalid")
        confidence = 0.0
    decision = document.get("decision")
    if decision not in {"propose", "abstain"}:
        blockers.append("decision_invalid")
    raw_citations = document.get("citations")
    citations: list[Citation] = []
    if not isinstance(raw_citations, list) or not raw_citations:
        blockers.append("citations_invalid")
        raw_citations = []
    for raw_citation in raw_citations:
        if not isinstance(raw_citation, dict) or set(raw_citation) != {
            "record_id",
            "payload_sha256",
        }:
            blockers.append("citation_schema")
            continue
        try:
            citations.append(Citation(**raw_citation))
        except (IntelligenceControlError, TypeError):
            blockers.append("citation_schema")
    if len({citation.record_id for citation in citations}) != len(citations):
        blockers.append("citations_duplicate")
    retained = context.record_map()
    for citation in citations:
        record = retained.get(citation.record_id)
        if record is None:
            blockers.append(f"citation_missing:{citation.record_id}")
        elif record.payload_sha256 != citation.payload_sha256:
            blockers.append(f"citation_hash_mismatch:{citation.record_id}")
        elif not record.may_support_authority:
            blockers.append(f"citation_nonauthoritative:{citation.record_id}")
    uncertainty = document.get("uncertainty")
    if not isinstance(uncertainty, list) or any(not isinstance(item, str) for item in uncertainty):
        blockers.append("uncertainty_invalid")
        uncertainty = []
    tool_call = document.get("tool_call")
    proposal: Mapping[str, Any] | None = None
    if tool_call is not None:
        if not isinstance(tool_call, dict) or set(tool_call) != TOOL_CALL_KEYS:
            blockers.append("tool_call_schema")
        else:
            tool_id = tool_call.get("tool_id")
            arguments = tool_call.get("arguments")
            idempotency_key = tool_call.get("idempotency_key")
            contract = tool_contracts.get(tool_id)
            if contract is None or contract.role != stack.role:
                blockers.append("tool_not_allowlisted_for_role")
            if not isinstance(arguments, dict):
                blockers.append("tool_arguments_invalid")
            elif contract is not None and contract.role == stack.role:
                required = set(contract.required_arguments)
                allowed = required | set(contract.optional_arguments)
                if not required.issubset(arguments) or not set(arguments) <= allowed:
                    blockers.append("tool_arguments_schema")
                elif any(
                    not _argument_has_type(arguments[key], contract.argument_types[key])
                    for key in arguments
                ):
                    blockers.append("tool_argument_type")
            if not isinstance(idempotency_key, str) or not idempotency_key:
                blockers.append("tool_idempotency_missing")
            proposal = dict(tool_call)
    if decision == "propose" and tool_call is None:
        blockers.append("proposal_tool_call_missing")
    if decision == "abstain":
        blockers.append("model_abstained")
    status = "authorized_proposal" if not blockers else "autonomous_abstention"
    tool_authorized = status == "authorized_proposal" and tool_call is not None
    return RoleDecision(
        status=status,
        role=stack.role,
        confidence=float(confidence),
        proposal=proposal if status == "authorized_proposal" else None,
        citations=tuple(item.record_id for item in citations),
        uncertainty=tuple(uncertainty),
        blockers=tuple(sorted(set(blockers))),
        context_bundle_sha256=context.bundle_sha256,
        stack_identity_sha256=stack.identity_sha256,
        tool_authorized=tool_authorized,
        may_execute_tool=False,
        may_promote_authority=False,
    )


@dataclass(frozen=True)
class CriticObservation:
    critic_id: str
    stack: RoleStackIdentity
    status: str
    confidence: float
    citations: tuple[Citation, ...]
    report_sha256: str

    def __post_init__(self) -> None:
        if not self.critic_id:
            raise IntelligenceControlError("critic ID is required")
        if self.stack.role != "visual_critic":
            raise IntelligenceControlError("critic observation requires visual_critic role")
        if self.status not in CRITIC_STATUSES:
            raise IntelligenceControlError("critic status is unsupported")
        if not 0 <= self.confidence <= 1:
            raise IntelligenceControlError("critic confidence must be in 0..1")
        _require_sha(self.report_sha256, "report_sha256")


@dataclass(frozen=True)
class CriticQuorumDecision:
    status: str
    independent_families: tuple[str, ...]
    counted_critic_ids: tuple[str, ...]
    excluded_critic_ids: tuple[str, ...]
    family_verdicts: Mapping[str, str]
    blockers: tuple[str, ...]
    explicit_uncertainty: bool
    critic_evidence_sha256: str
    may_clear_hard_veto: bool = False
    may_issue_certificate: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"pass", "autonomous_abstention"}:
            raise IntelligenceControlError("critic quorum status is invalid")
        if tuple(sorted(set(self.independent_families))) != self.independent_families:
            raise IntelligenceControlError("critic family list must be sorted and unique")
        if set(self.family_verdicts) != set(self.independent_families):
            raise IntelligenceControlError("critic family verdicts differ from family identity")
        if not set(self.family_verdicts.values()) <= {"pass", "fail", "uncertain"}:
            raise IntelligenceControlError("critic family verdict is invalid")
        _require_sha(self.critic_evidence_sha256, "critic_evidence_sha256")


def evaluate_critic_quorum(
    observations: Iterable[CriticObservation],
    *,
    expected_critic_ids: Sequence[str],
    context: ContextBundle,
    at_time: str,
    minimum_independent_families: int = 2,
) -> CriticQuorumDecision:
    observations = tuple(observations)
    if len(set(expected_critic_ids)) != len(expected_critic_ids):
        raise IntelligenceControlError("expected critic IDs must be unique")
    if len({item.critic_id for item in observations}) != len(observations):
        raise IntelligenceControlError("critic IDs must be unique")
    observed = {item.critic_id: item for item in observations}
    blockers: list[str] = []
    missing = sorted(set(expected_critic_ids) - set(observed))
    unexpected = sorted(set(observed) - set(expected_critic_ids))
    blockers.extend(f"critic_missing:{critic_id}" for critic_id in missing)
    blockers.extend(f"critic_unexpected:{critic_id}" for critic_id in unexpected)
    family_rows: dict[str, list[CriticObservation]] = {}
    counted: list[str] = []
    excluded: list[str] = []
    retained = context.record_map()
    for item in observations:
        item_blocked = False
        if item.critic_id in unexpected:
            excluded.append(item.critic_id)
            continue
        if not item.stack.is_qualified_at(at_time):
            blockers.append(f"critic_unqualified:{item.critic_id}")
            item_blocked = True
        if item.status in {"missing", "malformed", "timeout"}:
            blockers.append(f"critic_{item.status}:{item.critic_id}")
            item_blocked = True
        if not item.citations:
            blockers.append(f"critic_citations_missing:{item.critic_id}")
            item_blocked = True
        for citation in item.citations:
            record = retained.get(citation.record_id)
            if (
                record is None
                or record.payload_sha256 != citation.payload_sha256
                or not record.may_support_authority
            ):
                blockers.append(f"critic_citation_invalid:{item.critic_id}:{citation.record_id}")
                item_blocked = True
        if item_blocked:
            excluded.append(item.critic_id)
            continue
        family_rows.setdefault(item.stack.model_family, []).append(item)
        counted.append(item.critic_id)
    family_verdicts: dict[str, str] = {}
    for family, rows in sorted(family_rows.items()):
        statuses = {row.status for row in rows}
        if "fail" in statuses:
            family_verdicts[family] = "fail"
        elif "uncertain" in statuses or len(statuses) != 1:
            family_verdicts[family] = "uncertain"
        else:
            family_verdicts[family] = "pass"
    families = tuple(sorted(family_verdicts))
    if len(families) < minimum_independent_families:
        blockers.append("independent_critic_quorum_missing")
    if any(value == "fail" for value in family_verdicts.values()):
        blockers.append("critic_failure")
    if any(value == "uncertain" for value in family_verdicts.values()):
        blockers.append("critic_uncertainty")
    if len(set(family_verdicts.values())) > 1:
        blockers.append("critic_disagreement")
    if not context.authority_complete:
        blockers.extend(context.blockers)
    status = (
        "pass"
        if not blockers and set(family_verdicts.values()) == {"pass"}
        else ("autonomous_abstention")
    )
    critic_evidence_sha256 = _sha(
        [
            {
                "critic_id": item.critic_id,
                "stack_identity_sha256": item.stack.identity_sha256,
                "model_family": item.stack.model_family,
                "status": item.status,
                "confidence": item.confidence,
                "citations": [
                    {
                        "record_id": citation.record_id,
                        "payload_sha256": citation.payload_sha256,
                    }
                    for citation in item.citations
                ],
                "report_sha256": item.report_sha256,
            }
            for item in sorted(observations, key=lambda row: row.critic_id)
        ]
    )
    return CriticQuorumDecision(
        status,
        families,
        tuple(sorted(counted)),
        tuple(sorted(excluded)),
        family_verdicts,
        tuple(sorted(set(blockers))),
        status != "pass",
        critic_evidence_sha256,
    )


def critic_quorum_document(decision: CriticQuorumDecision) -> dict[str, Any]:
    return {
        "control_version": CONTROL_VERSION,
        "status": decision.status,
        "independent_families": list(decision.independent_families),
        "counted_critic_ids": list(decision.counted_critic_ids),
        "excluded_critic_ids": list(decision.excluded_critic_ids),
        "family_verdicts": dict(sorted(decision.family_verdicts.items())),
        "blockers": list(decision.blockers),
        "explicit_uncertainty": decision.explicit_uncertainty,
        "critic_evidence_sha256": decision.critic_evidence_sha256,
        "may_clear_hard_veto": decision.may_clear_hard_veto,
        "may_issue_certificate": decision.may_issue_certificate,
    }


def critic_quorum_sha256(decision: CriticQuorumDecision) -> str:
    return _sha(critic_quorum_document(decision))


def _event_hash(event: Mapping[str, Any]) -> str:
    return _sha({key: value for key, value in event.items() if key != "event_sha256"})


def load_intelligence_events(path: str | Path) -> tuple[dict[str, Any], ...]:
    event_path = Path(path)
    if not event_path.exists():
        return ()
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    stream_id: str | None = None
    for index, line in enumerate(event_path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IntelligenceControlError("event store contains invalid JSON") from exc
        if not isinstance(event, dict) or set(event) != EVENT_KEYS:
            raise IntelligenceControlError("event store row violates closed schema")
        if event.get("event_version") != CONTROL_VERSION or event.get("sequence") != index:
            raise IntelligenceControlError("event store sequence/version mismatch")
        if event.get("event_type") not in EVENT_TYPES:
            raise IntelligenceControlError("event type is unsupported")
        if not isinstance(event.get("stream_id"), str) or not event["stream_id"]:
            raise IntelligenceControlError("event stream ID is invalid")
        if stream_id is None:
            stream_id = event["stream_id"]
        elif event["stream_id"] != stream_id:
            raise IntelligenceControlError("event stream ID changed within one journal")
        if event.get("previous_event_sha256") != previous:
            raise IntelligenceControlError("event chain is broken")
        if event.get("payload_sha256") != _sha(event.get("payload")):
            raise IntelligenceControlError("event payload hash mismatch")
        if event.get("authority_effect") != "none_observation_only":
            raise IntelligenceControlError("intelligence event cannot promote authority")
        if event.get("event_sha256") != _event_hash(event):
            raise IntelligenceControlError("event hash mismatch")
        _parse_time(event.get("created_at"))
        previous = str(event["event_sha256"])
        events.append(event)
    return tuple(events)


def append_intelligence_event(
    path: str | Path,
    *,
    stream_id: str,
    event_type: str,
    payload: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    if not stream_id or event_type not in EVENT_TYPES:
        raise IntelligenceControlError("event stream/type is invalid")
    _parse_time(created_at)
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    events = load_intelligence_events(event_path)
    if events and events[0]["stream_id"] != stream_id:
        raise IntelligenceControlError("append stream ID differs from existing journal")
    previous = events[-1]["event_sha256"] if events else "0" * 64
    event = {
        "event_version": CONTROL_VERSION,
        "stream_id": stream_id,
        "sequence": len(events) + 1,
        "created_at": created_at,
        "event_type": event_type,
        "previous_event_sha256": previous,
        "payload": dict(payload),
        "payload_sha256": _sha(payload),
        "authority_effect": "none_observation_only",
    }
    event["event_sha256"] = _event_hash(event)
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if load_intelligence_events(event_path)[-1] != event:
        raise IntelligenceControlError("event append verification failed")
    return event


__all__ = [
    "CONTROL_VERSION",
    "Citation",
    "ContextBundle",
    "CriticObservation",
    "CriticQuorumDecision",
    "IntelligenceControlError",
    "RegistryRecord",
    "RoleDecision",
    "RoleStackIdentity",
    "ToolContract",
    "append_intelligence_event",
    "build_context_bundle",
    "critic_quorum_document",
    "critic_quorum_sha256",
    "evaluate_critic_quorum",
    "evaluate_role_output",
    "load_intelligence_events",
    "make_registry_record",
    "tool_policy_sha256",
]
