"""Cautious five-row routing; VLM has no approval, BLOCK-clear, or mask-write authority."""

from __future__ import annotations

from dataclasses import dataclass

from .client import VlmVerdict


@dataclass(frozen=True)
class RoutingDecision:
    queue: str
    priority: str
    correction_hint: str | None
    pin_disagreement_heatmap: bool
    may_approve_gold: bool = False
    may_clear_block: bool = False
    may_edit_mask: bool = False


def route(auto_qa: str, verdict: VlmVerdict) -> RoutingDecision:
    """Implement doc-10's five rows plus immutable authority constraints."""
    if auto_qa not in {"all_pass", "route", "block"}:
        raise ValueError("auto_qa must be all_pass, route, or block")
    if verdict.verdict == "uncertain" or (verdict.verdict == "pass" and verdict.confidence < 0.7):
        return RoutingDecision("careful", "normal", None, False)
    if auto_qa == "block":
        return RoutingDecision("careful", "highest", None, True)
    if auto_qa == "all_pass" and verdict.verdict == "pass":
        return RoutingDecision("quick_pass", "normal", None, False)
    if auto_qa == "all_pass" and verdict.verdict == "fail":
        hint = "MACHINE-GENERATED SUGGESTION: " + verdict.correction_instruction
        return RoutingDecision("careful", "normal", hint, False)
    if auto_qa == "route" and verdict.verdict == "pass":
        return RoutingDecision("careful", "normal", None, False)
    hint = "MACHINE-GENERATED SUGGESTION: " + verdict.correction_instruction
    return RoutingDecision("careful", "high", hint, True)


def cvat_task_description(base_description: str, decision: RoutingDecision) -> str:
    """Attach only explicitly machine-marked suggestions; uncertain routes add no hint."""
    if decision.correction_hint is None:
        return base_description
    return base_description.rstrip() + "\n\n" + decision.correction_hint
