from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.intelligence import (
    Citation,
    CriticObservation,
    IntelligenceControlError,
    RoleStackIdentity,
    ToolContract,
    append_intelligence_event,
    build_context_bundle,
    evaluate_critic_quorum,
    evaluate_role_output,
    load_intelligence_events,
    make_registry_record,
    tool_policy_sha256,
)

NOW = "2026-07-17T20:00:00Z"
REPAIR_CONTRACT = ToolContract(
    "mask.propose_roi_repair",
    "repair_proposer",
    ("label", "roi"),
    (),
    {"label": "string", "roi": "array"},
)
TOOL_CONTRACTS = {REPAIR_CONTRACT.tool_id: REPAIR_CONTRACT}


def _hash(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def _stack(
    role: str = "repair_proposer",
    *,
    family: str = "qwen-vl",
    stack_id: str = "repair-qwen-a",
    qualified_until: str = "2026-08-17T20:00:00Z",
) -> RoleStackIdentity:
    return RoleStackIdentity(
        stack_id=stack_id,
        role=role,
        model_family=family,
        model_revision=f"{family}@revision-fixture",
        runtime_sha256=_hash(f"{stack_id}:runtime"),
        prompt_sha256=_hash(f"{stack_id}:prompt"),
        parser_sha256=_hash(f"{stack_id}:parser"),
        tool_policy_sha256=tool_policy_sha256(
            TOOL_CONTRACTS.values() if role == "repair_proposer" else ()
        ),
        qualification_scope_sha256=_hash(f"{stack_id}:scope"),
        qualification_certificate_sha256=_hash(f"{stack_id}:qualification"),
        qualified_until=qualified_until,
    )


def _context(*, retained: tuple[str, ...] | None = None):
    records = (
        make_registry_record("release", "adopted_release", {"release": "r1"}),
        make_registry_record("policy", "active_policy", {"policy": "p1"}),
        make_registry_record("route", "qualified_route", {"route": "repair:left_hand"}),
        make_registry_record("chat", "conversation_cache", {"summary": "untrusted memory"}),
    )
    return build_context_bundle(
        bundle_id="bundle-fixture",
        records=records,
        required_record_ids=("release", "policy", "route"),
        retained_record_ids=retained,
    )


def _role_output(stack: RoleStackIdentity, **updates) -> str:
    context = _context().record_map()
    value = {
        "schema_version": "1.0.0",
        "role": stack.role,
        "stack_identity_sha256": stack.identity_sha256,
        "decision": "propose",
        "confidence": 0.82,
        "citations": [
            {"record_id": record_id, "payload_sha256": context[record_id].payload_sha256}
            for record_id in ("release", "policy", "route")
        ],
        "tool_call": {
            "tool_id": "mask.propose_roi_repair",
            "arguments": {"label": "left_hand", "roi": [1, 2, 8, 9]},
            "idempotency_key": "repair-fixture-001",
        },
        "uncertainty": ["boundary near occluder"],
    }
    value.update(updates)
    return json.dumps(value)


def test_exact_stack_and_hash_cited_closed_output_authorizes_proposal_but_never_executes() -> None:
    stack = _stack()
    decision = evaluate_role_output(
        _role_output(stack),
        stack=stack,
        context=_context(),
        tool_contracts=TOOL_CONTRACTS,
        at_time=NOW,
    )
    assert decision.status == "authorized_proposal"
    assert decision.proposal["tool_id"] == "mask.propose_roi_repair"
    assert decision.tool_authorized is True
    assert decision.may_execute_tool is False
    assert decision.may_promote_authority is False
    assert decision.uncertainty == ("boundary near occluder",)


def test_tool_argument_schema_and_stack_tool_policy_are_exact() -> None:
    stack = _stack()
    invalid = json.loads(_role_output(stack))
    invalid["tool_call"]["arguments"]["unexpected"] = True
    decision = evaluate_role_output(
        json.dumps(invalid),
        stack=stack,
        context=_context(),
        tool_contracts=TOOL_CONTRACTS,
        at_time=NOW,
    )
    assert "tool_arguments_schema" in decision.blockers

    mismatched = RoleStackIdentity(
        **{
            **stack.__dict__,
            "tool_policy_sha256": _hash("different-tool-policy"),
        }
    )
    invalid["stack_identity_sha256"] = mismatched.identity_sha256
    invalid["tool_call"]["arguments"].pop("unexpected")
    decision = evaluate_role_output(
        json.dumps(invalid),
        stack=mismatched,
        context=_context(),
        tool_contracts=TOOL_CONTRACTS,
        at_time=NOW,
    )
    assert "tool_policy_binding_mismatch" in decision.blockers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Use the repair tool now", "free_form_or_invalid_json"),
        (json.dumps({"role": "repair_proposer"}), "role_output_schema"),
    ],
)
def test_free_form_or_malformed_role_output_cannot_execute(raw: str, expected: str) -> None:
    stack = _stack()
    decision = evaluate_role_output(
        raw,
        stack=stack,
        context=_context(),
        tool_contracts=TOOL_CONTRACTS,
        at_time=NOW,
    )
    assert decision.status == "autonomous_abstention"
    assert expected in decision.blockers
    assert decision.proposal is None and not decision.may_execute_tool


def test_invalid_citations_conversation_memory_tool_scope_and_stale_stack_abstain() -> None:
    stack = _stack()
    records = _context().record_map()
    for raw, blocker in (
        (
            _role_output(
                stack,
                citations=[
                    {
                        "record_id": "chat",
                        "payload_sha256": records["chat"].payload_sha256,
                    }
                ],
            ),
            "citation_nonauthoritative:chat",
        ),
        (
            _role_output(
                stack,
                citations=[{"record_id": "missing", "payload_sha256": _hash("missing")}],
            ),
            "citation_missing:missing",
        ),
        (
            _role_output(
                stack,
                citations=[{"record_id": "release", "payload_sha256": _hash("wrong")}],
            ),
            "citation_hash_mismatch:release",
        ),
        (
            _role_output(
                stack,
                tool_call={
                    "tool_id": "certificate.issue",
                    "arguments": {},
                    "idempotency_key": "forbidden",
                },
            ),
            "tool_not_allowlisted_for_role",
        ),
    ):
        decision = evaluate_role_output(
            raw,
            stack=stack,
            context=_context(),
            tool_contracts=TOOL_CONTRACTS,
            at_time=NOW,
        )
        assert decision.status == "autonomous_abstention"
        assert blocker in decision.blockers
        assert decision.may_promote_authority is False

    expired = _stack(qualified_until="2026-07-17T19:59:59Z")
    decision = evaluate_role_output(
        _role_output(expired),
        stack=expired,
        context=_context(),
        tool_contracts=TOOL_CONTRACTS,
        at_time=NOW,
    )
    assert "stack_not_currently_qualified" in decision.blockers


def test_context_compaction_manifest_cannot_drop_required_authority() -> None:
    context = _context(retained=("release", "chat"))
    assert context.compaction_manifest["retained_record_ids"] == ["chat", "release"]
    assert context.compaction_manifest["dropped_required_record_ids"] == ["policy", "route"]
    assert context.authority_complete is False
    assert "dropped_required:policy" in context.blockers
    stack = _stack()
    decision = evaluate_role_output(
        _role_output(stack),
        stack=stack,
        context=context,
        tool_contracts=TOOL_CONTRACTS,
        at_time=NOW,
    )
    assert decision.status == "autonomous_abstention"
    assert "dropped_required:route" in decision.blockers


def _critic(
    critic_id: str,
    family: str,
    status: str = "pass",
    *,
    citations: tuple[str, ...] = ("release", "policy", "route"),
) -> CriticObservation:
    records = _context().record_map()
    return CriticObservation(
        critic_id,
        _stack("visual_critic", family=family, stack_id=f"critic-{critic_id}"),
        status,
        0.9 if status == "pass" else 0.4,
        tuple(
            Citation(
                record_id,
                (
                    records[record_id].payload_sha256
                    if record_id in records
                    else _hash(f"missing:{record_id}")
                ),
            )
            for record_id in citations
        ),
        _hash(f"critic-report:{critic_id}:{status}"),
    )


def test_critic_quorum_counts_families_not_correlated_variants() -> None:
    context = _context()
    correlated = evaluate_critic_quorum(
        (_critic("a1", "qwen-vl"), _critic("a2", "qwen-vl")),
        expected_critic_ids=("a1", "a2"),
        context=context,
        at_time=NOW,
    )
    assert correlated.status == "autonomous_abstention"
    assert correlated.independent_families == ("qwen-vl",)
    assert "independent_critic_quorum_missing" in correlated.blockers

    independent = evaluate_critic_quorum(
        (_critic("a", "qwen-vl"), _critic("b", "intern-vl")),
        expected_critic_ids=("a", "b"),
        context=context,
        at_time=NOW,
    )
    assert independent.status == "pass"
    assert independent.independent_families == ("intern-vl", "qwen-vl")
    assert independent.may_clear_hard_veto is False
    assert independent.may_issue_certificate is False


@pytest.mark.parametrize("bad_status", ["missing", "malformed", "timeout"])
def test_missing_malformed_or_timeout_critic_is_never_counted_as_pass(bad_status: str) -> None:
    decision = evaluate_critic_quorum(
        (_critic("a", "qwen-vl"), _critic("b", "intern-vl", bad_status)),
        expected_critic_ids=("a", "b"),
        context=_context(),
        at_time=NOW,
    )
    assert decision.status == "autonomous_abstention"
    assert "b" in decision.excluded_critic_ids
    assert f"critic_{bad_status}:b" in decision.blockers
    assert "intern-vl" not in decision.independent_families


def test_missing_expected_critic_disagreement_and_invalid_citation_abstain() -> None:
    missing = evaluate_critic_quorum(
        (_critic("a", "qwen-vl"),),
        expected_critic_ids=("a", "b"),
        context=_context(),
        at_time=NOW,
    )
    assert "critic_missing:b" in missing.blockers

    disagreement = evaluate_critic_quorum(
        (_critic("a", "qwen-vl"), _critic("b", "intern-vl", "fail")),
        expected_critic_ids=("a", "b"),
        context=_context(),
        at_time=NOW,
    )
    assert "critic_disagreement" in disagreement.blockers
    assert "critic_failure" in disagreement.blockers

    bad_citation = evaluate_critic_quorum(
        (_critic("a", "qwen-vl"), _critic("b", "intern-vl", citations=("chat",))),
        expected_critic_ids=("a", "b"),
        context=_context(),
        at_time=NOW,
    )
    assert "critic_citation_invalid:b:chat" in bad_citation.blockers
    assert "b" in bad_citation.excluded_critic_ids

    unexpected = evaluate_critic_quorum(
        (_critic("a", "qwen-vl"), _critic("extra", "intern-vl")),
        expected_critic_ids=("a",),
        context=_context(),
        at_time=NOW,
    )
    assert "critic_unexpected:extra" in unexpected.blockers
    assert "extra" in unexpected.excluded_critic_ids


def test_append_only_event_memory_is_hash_chained_and_observation_only(tmp_path: Path) -> None:
    path = tmp_path / "intelligence-events.jsonl"
    first = append_intelligence_event(
        path,
        stream_id="run-fixture",
        event_type="context_built",
        payload={"bundle_sha256": _context().bundle_sha256},
        created_at="2026-07-17T20:00:00Z",
    )
    second = append_intelligence_event(
        path,
        stream_id="run-fixture",
        event_type="role_evaluated",
        payload={"status": "autonomous_abstention", "conversation_cache_used": False},
        created_at="2026-07-17T20:00:01Z",
    )
    rows = load_intelligence_events(path)
    assert rows == (first, second)
    assert second["previous_event_sha256"] == first["event_sha256"]
    assert all(row["authority_effect"] == "none_observation_only" for row in rows)

    with pytest.raises(IntelligenceControlError, match="append stream ID differs"):
        append_intelligence_event(
            path,
            stream_id="different-run",
            event_type="abstained",
            payload={"reason": "wrong stream"},
            created_at="2026-07-17T20:00:02Z",
        )

    tampered = path.read_text().replace("autonomous_abstention", "authority_promoted")
    path.write_text(tampered)
    with pytest.raises(IntelligenceControlError, match="payload hash mismatch"):
        load_intelligence_events(path)
