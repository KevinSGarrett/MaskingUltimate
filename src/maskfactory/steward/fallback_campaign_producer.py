"""CPU-safe tracker producer for governed OpenRouter fallback campaigns.

The dispatcher can only advance immutable work already present in its inbox.
This producer closes the other half of continuous fallback operation: it reads
the authoritative tracker, batches every currently unblocked Plan-27
engineering item, and materializes one immutable advisory mission per bounded
campaign.  It never calls a provider or grants the advisory execution
authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .campaign_builder import CampaignCandidate, build_campaigns
from .fallback_dispatcher import (
    WORK_ITEM_NAME,
    WORK_ITEM_SCHEMA,
    fallback_child_mission_id,
    seal_fallback_work_item,
)
from .goal_selector import (
    ACTIONABLE_STATUSES,
    DEPENDENCY_DONE_STATUSES,
    PLAN27_ITEM_ORDER,
    parse_dependency_ids,
)
from .openrouter_advisory import MANAGER_PATH, POLICY_PATH

PRODUCER_SCHEMA = "maskfactory.steward.fallback_campaign_producer.v1"
REQUEST_SCHEMA = "maskfactory.openrouter_advisory_request.v2"
SESSION_ID = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
DEFAULT_ADVISORY_WORK_KINDS = (
    "implementation_review",
    "code_review",
    "test_strategy",
    "test_generation",
    "root_cause_analysis",
    "dependency_analysis",
    "repair_planning",
    "evidence_compaction",
)
BLOCKED_ANALYSIS_WORK_KINDS = frozenset(
    {"root_cause_analysis", "dependency_analysis", "repair_planning"}
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
AUTHORITY = {
    "read_secrets": False,
    "execute_tools": False,
    "git": False,
    "github": False,
    "runpod_lifecycle": False,
    "infrastructure": False,
    "destructive_filesystem": False,
    "final_acceptance": False,
}


class FallbackCampaignProducerError(RuntimeError):
    """Tracker state cannot be converted into a safe immutable campaign."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _dependency_done(items: Mapping[str, object], item_id: str) -> bool:
    item = items.get(item_id)
    return (
        isinstance(item, Mapping)
        and not item.get("orphaned")
        and item.get("status") in DEPENDENCY_DONE_STATUSES
    )


def _bounded_item(item_id: str, item: Mapping[str, object]) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "cluster_id": str(item.get("cluster_id") or ""),
        "cluster_title": str(item.get("cluster_title") or ""),
        "spec_ref": str(item.get("spec_ref") or ""),
        "description": str(item.get("description") or ""),
        "status": str(item.get("status") or ""),
        "percent_complete": int(item.get("percent_complete") or 0),
        "blocked_reason": (str(item["blocked_reason"]) if item.get("blocked_reason") else None),
        "dependency_ids": list(parse_dependency_ids(str(item.get("description") or ""))),
    }


def _prompt(packet: Mapping[str, Any], *, work_kind: str) -> str:
    focus = {
        "implementation_review": (
            "Produce the smallest executable implementation plan with exact source "
            "paths, state transitions, and rollback boundaries."
        ),
        "test_strategy": (
            "Produce a focused adversarial test matrix, including restart, ambiguity, "
            "duplicate-execution, and route-unavailable cases."
        ),
        "code_review": (
            "Review the likely implementation boundaries for correctness, security, "
            "idempotency, race conditions, and regression risks."
        ),
        "test_generation": (
            "Draft concrete focused test cases and fixtures that would prove the "
            "tracker acceptance criteria without weakening fail-closed behavior."
        ),
        "root_cause_analysis": (
            "Diagnose the concrete blockers and likely root causes. Distinguish missing "
            "runtime evidence from missing implementation and static coverage."
        ),
        "dependency_analysis": (
            "Reconstruct the dependency DAG and identify the smallest safe work that can "
            "advance each blocked item without claiming completion."
        ),
        "repair_planning": (
            "Produce bounded hypothesis-distinct repair steps, their stop conditions, "
            "and the exact evidence that would distinguish each hypothesis."
        ),
        "evidence_compaction": (
            "Design one compact acceptance packet that reconciles every required "
            "runtime, test, route, duplicate, budget, and release fact."
        ),
    }.get(work_kind)
    if focus is None:
        raise FallbackCampaignProducerError(
            f"unsupported OpenRouter advisory work kind: {work_kind}"
        )
    return "\n".join(
        (
            "You are a read-only engineering adviser for MaskFactory.",
            "Analyze this bounded tracker-driven Plan-27 campaign and return one "
            "consolidated implementation proposal.",
            focus,
            "For each item provide: exact likely source paths, smallest safe change, "
            "focused tests, failure/recovery cases, evidence needed, and unresolved "
            "risks. Prioritize executable engineering detail over status prose.",
            "Do not claim execution, Git, provider, RunPod, tracker-completion, mask, "
            "visual-QA, security, or final acceptance authority. Do not request or "
            "invent secrets. Codex independently reviews any proposal.",
            "Return concise JSON with keys campaign_summary, item_proposals, "
            "cross_item_tests, risks, and adoption_recommendation.",
            "",
            json.dumps(packet, sort_keys=True, indent=2, ensure_ascii=False),
        )
    )


class FallbackCampaignProducer:
    """Materialize deterministic OpenRouter advisory campaigns from tracker truth."""

    def __init__(
        self,
        *,
        tracker_path: Path,
        inbox_root: Path,
        session_id: str = SESSION_ID,
        context_token_cap: int = 12_000,
        engineering_mission_cap: int = 25,
        max_output_tokens: int = 4096,
        advisory_work_kinds: tuple[str, ...] = ("implementation_review",),
        openrouter_manager_path: Path = MANAGER_PATH,
        openrouter_policy_path: Path = POLICY_PATH,
    ) -> None:
        if not session_id:
            raise FallbackCampaignProducerError("session_id is required")
        if context_token_cap <= 0 or engineering_mission_cap <= 0:
            raise FallbackCampaignProducerError("campaign bounds must be positive")
        if max_output_tokens <= 0 or max_output_tokens > 4096:
            raise FallbackCampaignProducerError("max_output_tokens is out of policy")
        self.tracker_path = Path(tracker_path)
        self.inbox_root = Path(inbox_root)
        self.session_id = session_id
        self.context_token_cap = int(context_token_cap)
        self.engineering_mission_cap = int(engineering_mission_cap)
        self.max_output_tokens = int(max_output_tokens)
        if (
            len(advisory_work_kinds) != 1
            or advisory_work_kinds[0] not in DEFAULT_ADVISORY_WORK_KINDS
        ):
            raise FallbackCampaignProducerError(
                "exactly one governed consolidated advisory work kind is required"
            )
        self.advisory_work_kinds = tuple(advisory_work_kinds)
        self.openrouter_manager_path = Path(openrouter_manager_path)
        self.openrouter_policy_path = Path(openrouter_policy_path)
        if not self.openrouter_manager_path.is_file():
            raise FallbackCampaignProducerError("OpenRouter manager is missing")
        if not self.openrouter_policy_path.is_file():
            raise FallbackCampaignProducerError("OpenRouter policy is missing")
        self.inbox_root.mkdir(parents=True, exist_ok=True)

    def _load_tracker(self) -> dict[str, Any]:
        try:
            tracker = json.loads(self.tracker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FallbackCampaignProducerError("tracker is unreadable") from exc
        if not isinstance(tracker, dict) or not isinstance(tracker.get("items"), dict):
            raise FallbackCampaignProducerError("tracker items are missing")
        return tracker

    def _candidates(
        self,
        tracker: Mapping[str, Any],
        *,
        include_blocked_dependencies: bool = False,
    ) -> tuple[list[CampaignCandidate], dict[str, dict[str, Any]], set[str]]:
        items = tracker["items"]
        completed = {
            item_id
            for item_id, item in items.items()
            if isinstance(item, Mapping)
            and not item.get("orphaned")
            and item.get("status") in DEPENDENCY_DONE_STATUSES
        }
        packets: dict[str, dict[str, Any]] = {}
        candidates: list[CampaignCandidate] = []
        for item_id in PLAN27_ITEM_ORDER:
            item = items.get(item_id)
            if (
                not isinstance(item, Mapping)
                or item.get("orphaned")
                or item.get("status") not in ACTIONABLE_STATUSES
            ):
                continue
            packet = _bounded_item(item_id, item)
            dependencies_done = all(
                _dependency_done(items, dependency) for dependency in packet["dependency_ids"]
            )
            if not dependencies_done and not include_blocked_dependencies:
                continue
            packets[item_id] = packet
            encoded = _canonical_bytes(packet)
            candidates.append(
                CampaignCandidate(
                    item_id=item_id,
                    work_kind="engineering",
                    compatibility_key=f"plan27:{packet['cluster_id']}",
                    payload_sha256=hashlib.sha256(encoded).hexdigest(),
                    estimated_context_tokens=max(256, (len(encoded) + 3) // 4),
                    dependency_ids=(
                        () if include_blocked_dependencies else tuple(packet["dependency_ids"])
                    ),
                    status=str(item.get("status")),
                )
            )
        return candidates, packets, completed

    def _terminal_campaign(self, *, campaign_id: str, tracker_sha256: str) -> str | None:
        for mission_root in self.inbox_root.iterdir():
            packet_path = mission_root / "campaign_input.json"
            terminal_path = mission_root / "fallback_terminal_receipt.json"
            if (
                not mission_root.is_dir()
                or not packet_path.is_file()
                or not terminal_path.is_file()
            ):
                continue
            try:
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(packet, dict)
                and packet.get("campaign_id") == campaign_id
                and packet.get("tracker_sha256") == tracker_sha256
            ):
                return mission_root.name
        return None

    def produce(self) -> list[dict[str, Any]]:
        """Create each missing immutable campaign and return compact receipts."""

        tracker = self._load_tracker()
        tracker_sha256 = _file_sha256(self.tracker_path)
        manager_sha256 = _file_sha256(self.openrouter_manager_path)
        policy_sha256 = _file_sha256(self.openrouter_policy_path)
        receipts: list[dict[str, Any]] = []
        for work_kind in self.advisory_work_kinds:
            include_blocked = work_kind in BLOCKED_ANALYSIS_WORK_KINDS
            candidates, packets, completed = self._candidates(
                tracker,
                include_blocked_dependencies=include_blocked,
            )
            built = build_campaigns(
                candidates,
                completed_dependency_ids=completed,
                context_token_cap=self.context_token_cap,
                engineering_mission_cap=self.engineering_mission_cap,
            )
            for campaign in built.campaigns:
                receipts.append(
                    self._produce_campaign(
                        campaign=campaign,
                        packets=packets,
                        tracker_sha256=tracker_sha256,
                        manager_sha256=manager_sha256,
                        policy_sha256=policy_sha256,
                        work_kind=work_kind,
                        include_blocked=include_blocked,
                    )
                )
        return receipts

    def _produce_campaign(
        self,
        *,
        campaign: Any,
        packets: Mapping[str, dict[str, Any]],
        tracker_sha256: str,
        manager_sha256: str,
        policy_sha256: str,
        work_kind: str,
        include_blocked: bool,
    ) -> dict[str, Any]:
        prior_terminal = self._terminal_campaign(
            campaign_id=campaign.campaign_id,
            tracker_sha256=tracker_sha256,
        )
        if prior_terminal is not None:
            return {
                "mission_id": prior_terminal,
                "campaign_id": campaign.campaign_id,
                "work_kind": work_kind,
                "item_ids": list(campaign.item_ids),
                "created": False,
                "terminal_reused": True,
            }
        packet = {
            "schema_version": PRODUCER_SCHEMA,
            "tracker_sha256": tracker_sha256,
            "openrouter_manager_sha256": manager_sha256,
            "openrouter_policy_sha256": policy_sha256,
            "campaign_id": campaign.campaign_id,
            "campaign_kind": "plan27_engineering",
            "advisory_work_kind": work_kind,
            "blocked_dependency_analysis": include_blocked,
            "item_count": len(campaign.item_ids),
            "item_ids": list(campaign.item_ids),
            "items": [packets[item_id] for item_id in campaign.item_ids],
            "authority": AUTHORITY,
        }
        parent_contract_sha256 = _canonical_sha256(packet)
        parent_campaign_id = _canonical_sha256(
            {
                "schema_version": "maskfactory.steward.fallback_parent_identity.v1",
                "session_id": self.session_id,
                "source_campaign_id": campaign.campaign_id,
                "parent_contract_sha256": parent_contract_sha256,
            }
        )
        prompt = _prompt(packet, work_kind=work_kind)
        prompt_bytes = prompt.encode("utf-8")
        prompt_sha256 = hashlib.sha256(prompt_bytes).hexdigest()
        required_child_roles = ("consolidated_advisory",)
        mission_id = fallback_child_mission_id(
            session_id=self.session_id,
            parent_campaign_id=parent_campaign_id,
            parent_contract_sha256=parent_contract_sha256,
            required_child_roles=required_child_roles,
            child_role="consolidated_advisory",
            route="openrouter_advisory",
        )
        if not SHA256_RE.fullmatch(mission_id):
            raise FallbackCampaignProducerError("derived mission identity is invalid")
        mission_root = self.inbox_root / mission_id
        if mission_root.exists():
            return {
                "mission_id": mission_id,
                "campaign_id": campaign.campaign_id,
                "parent_campaign_id": parent_campaign_id,
                "work_kind": work_kind,
                "item_ids": list(campaign.item_ids),
                "created": False,
            }

        temporary = self.inbox_root / f".{mission_id}.{os.getpid()}.tmp"
        temporary.mkdir(mode=0o700)
        try:
            _write_exclusive(temporary / "campaign_input.json", _json_bytes(packet))
            _write_exclusive(temporary / "prompt.txt", prompt_bytes)
            request = {
                "schema_version": REQUEST_SCHEMA,
                "mission_id": mission_id,
                "session_id": self.session_id,
                "job_id": f"mf-plan27-{mission_id[:20]}",
                "parent_campaign_id": parent_campaign_id,
                "parent_contract_sha256": parent_contract_sha256,
                "child_role": "consolidated_advisory",
                "work_kind": work_kind,
                "model_tier": "routine",
                "materially_difficult": False,
                "prompt_sha256": prompt_sha256,
                "max_output_tokens": self.max_output_tokens,
                "attachments": [],
                "attachment_sha256": [],
                "system_prompt_file": None,
                "system_prompt_sha256": None,
                "authority": AUTHORITY,
            }
            _write_exclusive(temporary / "request.json", _json_bytes(request))
            work_item = seal_fallback_work_item(
                {
                    "schema_version": WORK_ITEM_SCHEMA,
                    "mission_id": mission_id,
                    "session_id": self.session_id,
                    "parent_campaign_id": parent_campaign_id,
                    "parent_contract_sha256": parent_contract_sha256,
                    "required_child_roles": list(required_child_roles),
                    "child_role": "consolidated_advisory",
                    "route": "openrouter_advisory",
                    "payload_sha256": _file_sha256(temporary / "request.json"),
                    "request_file": "request.json",
                    "prompt_file": "prompt.txt",
                    "pod_state": "unavailable",
                    "serverless_state": "available",
                    "tracker_item_ids": list(campaign.item_ids),
                    "openrouter_manager_sha256": manager_sha256,
                    "openrouter_policy_sha256": policy_sha256,
                }
            )
            _write_exclusive(temporary / WORK_ITEM_NAME, _json_bytes(work_item))
            os.replace(temporary, mission_root)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return {
            "mission_id": mission_id,
            "campaign_id": campaign.campaign_id,
            "parent_campaign_id": parent_campaign_id,
            "work_kind": work_kind,
            "item_ids": list(campaign.item_ids),
            "created": True,
            "request_sha256": _file_sha256(mission_root / "request.json"),
            "work_item_sha256": _file_sha256(mission_root / WORK_ITEM_NAME),
        }


__all__ = [
    "FallbackCampaignProducer",
    "FallbackCampaignProducerError",
    "DEFAULT_ADVISORY_WORK_KINDS",
    "PRODUCER_SCHEMA",
]
