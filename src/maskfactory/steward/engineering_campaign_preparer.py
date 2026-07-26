"""Prepare one tracker-bound 25-mission engineering campaign for local Qwen.

The preparer is CPU-only.  It uses the authoritative goal selector and
campaign builder, extracts exact clean Git bytes into bounded repository
packets, creates strict authority-free review requests, and seals the runtime
campaign consumed by :mod:`engineering_campaign_runtime`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .campaign_builder import CampaignCandidate, build_campaigns
from .core import (
    AUTHORITY_KEYS,
    BINDING_SCHEMA as MISSION_BINDING_SCHEMA,
    canonical_sha256,
    seal_binding,
)
from .engineering_campaign_runtime import (
    BINDING_NAME,
    CAMPAIGN_SIZE,
    build_engineering_campaign_runtime_binding,
    validate_engineering_campaign_runtime_binding,
)
from .goal_selector import GoalSelection, select_next_plan27_work
from .repository_packet import (
    MANIFEST_NAME as REPOSITORY_MANIFEST_NAME,
    build_repository_packet,
    verify_repository_packet,
)
from .runtime import (
    atomic_write_json,
    file_sha256,
    load_runtime_contract,
    read_json,
    validate_request,
)

SOURCE_SCHEMA = "maskfactory.engineering_campaign_source.v1"
PREPARATION_SCHEMA = "maskfactory.engineering_campaign_preparation.v1"
SOURCE_NAME = "engineering_campaign_source.json"
PREPARATION_NAME = "engineering_campaign_preparation.json"
PROMPT_NAME = "prompt.txt"
REQUEST_NAME = "request.json"
PACKET_MANIFEST_NAME = "repository_packet_manifest.json"
ZERO_SHA256 = "0" * 64
MAX_TASK_BYTES = 16 * 1024
MAX_PROMPT_BYTES = 96 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class EngineeringCampaignPreparationError(RuntimeError):
    """A campaign source cannot be materialized without weakening authority."""


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = canonical_sha256(sealed)
    return sealed


def _self_hash(value: Mapping[str, Any], field: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise EngineeringCampaignPreparationError(f"{field} is invalid")
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignPreparationError(
            f"{field} canonical self-hash mismatch"
        )


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise EngineeringCampaignPreparationError(f"{field} is invalid")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise EngineeringCampaignPreparationError(f"{field} is invalid")
    if len(value.encode("utf-8")) > maximum:
        raise EngineeringCampaignPreparationError(f"{field} exceeds byte cap")
    return value


def _load_tracker(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value.get("items"), dict):
        raise EngineeringCampaignPreparationError("tracker items are unavailable")
    return value


def _source(path: Path) -> dict[str, Any]:
    value = read_json(path)
    required = {
        "schema_version",
        "session_id",
        "tracker_item_id",
        "compatibility_key",
        "completed_dependency_ids",
        "context_token_cap",
        "max_packet_bytes",
        "missions",
        "source_sha256",
    }
    if set(value) != required or value.get("schema_version") != SOURCE_SCHEMA:
        raise EngineeringCampaignPreparationError(
            "campaign source field or schema mismatch"
        )
    _self_hash(value, "source_sha256")
    _identity(value["session_id"], "session_id")
    _identity(value["tracker_item_id"], "tracker_item_id")
    _identity(value["compatibility_key"], "compatibility_key")
    if (
        not isinstance(value["completed_dependency_ids"], list)
        or len(value["completed_dependency_ids"])
        != len(set(value["completed_dependency_ids"]))
        or any(
            not isinstance(item, str) or not item
            for item in value["completed_dependency_ids"]
        )
    ):
        raise EngineeringCampaignPreparationError(
            "completed dependency identities are invalid"
        )
    if (
        not isinstance(value["context_token_cap"], int)
        or isinstance(value["context_token_cap"], bool)
        or value["context_token_cap"] <= 0
        or not isinstance(value["max_packet_bytes"], int)
        or isinstance(value["max_packet_bytes"], bool)
        or value["max_packet_bytes"] <= 0
    ):
        raise EngineeringCampaignPreparationError("campaign limits are invalid")
    missions = value["missions"]
    if not isinstance(missions, list) or len(missions) != CAMPAIGN_SIZE:
        raise EngineeringCampaignPreparationError(
            "campaign source requires exactly 25 missions"
        )
    seen: set[str] = set()
    for mission in missions:
        if not isinstance(mission, dict) or set(mission) != {
            "mission_id",
            "source_paths",
            "scope_roots",
            "task",
            "estimated_context_tokens",
            "dependency_ids",
        }:
            raise EngineeringCampaignPreparationError(
                "campaign mission source fields differ"
            )
        mission_id = _identity(mission["mission_id"], "mission_id")
        if mission_id in seen:
            raise EngineeringCampaignPreparationError(
                "campaign mission identities must be unique"
            )
        seen.add(mission_id)
        for field in ("source_paths", "scope_roots", "dependency_ids"):
            rows = mission[field]
            if (
                not isinstance(rows, list)
                or (field != "dependency_ids" and not rows)
                or len(rows) != len(set(rows))
                or any(not isinstance(row, str) or not row for row in rows)
            ):
                raise EngineeringCampaignPreparationError(
                    f"{mission_id}: {field} is invalid"
                )
        _text(mission["task"], f"{mission_id}.task", MAX_TASK_BYTES)
        if (
            not isinstance(mission["estimated_context_tokens"], int)
            or isinstance(mission["estimated_context_tokens"], bool)
            or mission["estimated_context_tokens"] <= 0
        ):
            raise EngineeringCampaignPreparationError(
                f"{mission_id}: estimated context is invalid"
            )
    return value


def seal_engineering_campaign_source(
    *,
    session_id: str,
    tracker_item_id: str,
    compatibility_key: str,
    completed_dependency_ids: Sequence[str],
    context_token_cap: int,
    max_packet_bytes: int,
    missions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Seal one deterministic campaign preparation source."""

    value = {
        "schema_version": SOURCE_SCHEMA,
        "session_id": session_id,
        "tracker_item_id": tracker_item_id,
        "compatibility_key": compatibility_key,
        "completed_dependency_ids": list(completed_dependency_ids),
        "context_token_cap": context_token_cap,
        "max_packet_bytes": max_packet_bytes,
        "missions": [dict(mission) for mission in missions],
        "source_sha256": ZERO_SHA256,
    }
    sealed = _seal(value, "source_sha256")
    # Replay the closed validator before returning bytes to a caller.
    temporary = None
    try:
        temporary = Path(tempfile.mkdtemp()) / SOURCE_NAME
        _write_exclusive(temporary, sealed)
        return _source(temporary)
    finally:
        if temporary is not None:
            shutil.rmtree(temporary.parent, ignore_errors=True)


def _selection(
    tracker: Mapping[str, Any],
    source: Mapping[str, Any],
) -> GoalSelection:
    selection = select_next_plan27_work(
        tracker,
        inference_available=True,
    )
    if selection is None:
        raise EngineeringCampaignPreparationError(
            "tracker has no unblocked Plan-27 work"
        )
    if selection.item_id != source["tracker_item_id"]:
        raise EngineeringCampaignPreparationError(
            "campaign source does not target the current pursuing-goal item"
        )
    return selection


def _response_schema(
    *,
    mission_id: str,
    packet_sha256: str,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "mission_id",
            "packet_sha256",
            "decision",
            "summary",
            "findings",
            "authority_claimed",
            "completion_claimed",
        ],
        "properties": {
            "mission_id": {"const": mission_id},
            "packet_sha256": {"const": packet_sha256},
            "decision": {
                "enum": [
                    "NO_CHANGE",
                    "PATCH_RECOMMENDED",
                    "TEST_RECOMMENDED",
                    "BLOCKED",
                ]
            },
            "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
            "findings": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "severity",
                        "path",
                        "evidence",
                        "recommendation",
                    ],
                    "properties": {
                        "severity": {
                            "enum": ["info", "low", "medium", "high", "critical"]
                        },
                        "path": {"type": "string", "minLength": 1, "maxLength": 300},
                        "evidence": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1200,
                        },
                        "recommendation": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1200,
                        },
                    },
                },
            },
            "authority_claimed": {"const": False},
            "completion_claimed": {"const": False},
        },
    }


def _prompt(
    *,
    mission: Mapping[str, Any],
    packet_root: Path,
    manifest: Mapping[str, Any],
) -> str:
    sections = [
        "MASKFACTORY BOUNDED ENGINEERING REVIEW",
        "You are an advisory self-hosted engineering worker.",
        "Use only the exact immutable repository packet below.",
        "Do not request tools, credentials, Git/GitHub, infrastructure, "
        "RunPod lifecycle, tracker, completion, or final-adoption authority.",
        "Return only JSON matching the supplied response schema.",
        f"MISSION_ID: {mission['mission_id']}",
        f"PACKET_SHA256: {manifest['packet_sha256']}",
        f"TASK:\n{mission['task']}",
        "IMMUTABLE_PACKET_MANIFEST:\n"
        + json.dumps(manifest, sort_keys=True, ensure_ascii=False),
    ]
    for row in manifest["files"]:
        source = packet_root / "files" / Path(row["path"])
        sections.append(
            "FILE "
            + row["path"]
            + " SHA256 "
            + row["sha256"]
            + "\n"
            + source.read_text(encoding="utf-8")
        )
    prompt = "\n\n".join(sections) + "\n"
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise EngineeringCampaignPreparationError(
            f"{mission['mission_id']}: materialized prompt exceeds byte cap"
        )
    return prompt


def _prepare_mission(
    *,
    repo_root: Path,
    packet_root: Path,
    mission_root: Path,
    mission: Mapping[str, Any],
    source: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = build_repository_packet(
        repo_root=repo_root,
        packet_root=packet_root,
        source_paths=mission["source_paths"],
        scope_roots=mission["scope_roots"],
        tracker_item_ids=[source["tracker_item_id"]],
        max_packet_bytes=source["max_packet_bytes"],
        minimum_free_bytes=0,
    )
    verify_repository_packet(
        packet_root,
        repo_root=repo_root,
        require_current_source=True,
    )
    mission_root.mkdir(parents=True)
    prompt = _prompt(
        mission=mission,
        packet_root=packet_root,
        manifest=manifest,
    )
    (mission_root / PROMPT_NAME).write_text(
        prompt,
        encoding="utf-8",
        newline="\n",
    )
    (mission_root / PACKET_MANIFEST_NAME).write_bytes(
        (packet_root / REPOSITORY_MANIFEST_NAME).read_bytes()
    )
    schema = _response_schema(
        mission_id=mission["mission_id"],
        packet_sha256=manifest["packet_sha256"],
    )
    request = {
        "model": contract["server"]["served_model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return one concise authority-free MaskFactory engineering "
                    "review as strict JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "seed": 1337,
        "max_tokens": 900,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "maskfactory_engineering_review",
                "schema": schema,
                "strict": True,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    atomic_write_json(mission_root / REQUEST_NAME, request)
    validate_request(contract, request)
    binding = seal_binding(
        {
            "schema_version": MISSION_BINDING_SCHEMA,
            "session_id": source["session_id"],
            "job_id": mission["mission_id"],
            "payload_sha256": canonical_sha256(
                {
                    "packet_sha256": manifest["packet_sha256"],
                    "task": mission["task"],
                }
            ),
            "model_tree_sha256": contract["model"]["tree_sha256"],
            "runtime_sha256": contract["contract_sha256"],
            "input_sha256": {
                PACKET_MANIFEST_NAME: file_sha256(
                    mission_root / PACKET_MANIFEST_NAME
                ),
                PROMPT_NAME: file_sha256(mission_root / PROMPT_NAME),
                REQUEST_NAME: file_sha256(mission_root / REQUEST_NAME),
            },
            "output_namespace": (
                f"{source['session_id']}/{mission['mission_id']}"
            ),
            "requires_replay": True,
            "authority": {key: False for key in sorted(AUTHORITY_KEYS)},
        }
    )
    atomic_write_json(mission_root / "binding.json", binding)
    return {
        "mission_id": mission["mission_id"],
        "packet_sha256": manifest["packet_sha256"],
        "packet_manifest_file_sha256": file_sha256(
            mission_root / PACKET_MANIFEST_NAME
        ),
        "prompt_sha256": file_sha256(mission_root / PROMPT_NAME),
        "request_sha256": file_sha256(mission_root / REQUEST_NAME),
        "binding_sha256": binding["binding_sha256"],
        "binding_file_sha256": file_sha256(mission_root / "binding.json"),
    }


def _validate_preparation(
    *,
    campaign_root: Path,
    source: Mapping[str, Any],
    runtime_contract_path: Path,
) -> dict[str, Any]:
    binding = validate_engineering_campaign_runtime_binding(
        campaign_root / BINDING_NAME,
        campaign_root=campaign_root,
        contract_path=runtime_contract_path,
    )
    preparation = read_json(campaign_root / PREPARATION_NAME)
    _self_hash(preparation, "preparation_sha256")
    if set(preparation) != {
        "schema_version",
        "campaign_id",
        "session_id",
        "tracker_item_id",
        "goal_selection",
        "source_sha256",
        "source_file_sha256",
        "campaign_binding_sha256",
        "campaign_binding_file_sha256",
        "mission_count",
        "mission_evidence",
        "authority_claimed",
        "completion_claimed",
        "preparation_sha256",
    }:
        raise EngineeringCampaignPreparationError(
            "prepared campaign field set mismatch"
        )
    if (
        preparation.get("schema_version") != PREPARATION_SCHEMA
        or preparation.get("campaign_id") != binding["campaign_id"]
        or preparation.get("session_id") != source["session_id"]
        or preparation.get("tracker_item_id") != source["tracker_item_id"]
        or preparation.get("source_sha256") != source["source_sha256"]
        or preparation.get("source_file_sha256")
        != file_sha256(campaign_root / SOURCE_NAME)
        or preparation.get("campaign_binding_sha256")
        != binding["binding_sha256"]
        or preparation.get("campaign_binding_file_sha256")
        != file_sha256(campaign_root / BINDING_NAME)
        or preparation.get("mission_count") != CAMPAIGN_SIZE
        or preparation.get("authority_claimed") is not False
        or preparation.get("completion_claimed") is not False
    ):
        raise EngineeringCampaignPreparationError(
            "prepared campaign binding mismatch"
        )
    if (campaign_root / SOURCE_NAME).read_bytes() != _json_bytes(source):
        raise EngineeringCampaignPreparationError(
            "prepared campaign source bytes drifted"
        )
    evidence = preparation.get("mission_evidence")
    if not isinstance(evidence, list) or len(evidence) != CAMPAIGN_SIZE:
        raise EngineeringCampaignPreparationError(
            "prepared campaign mission evidence is incomplete"
        )
    entry_by_id = {
        row["job_id"]: row for row in binding["mission_entries"]
    }
    if len(entry_by_id) != CAMPAIGN_SIZE:
        raise EngineeringCampaignPreparationError(
            "prepared campaign mission binding is contradictory"
        )
    for row in evidence:
        if not isinstance(row, dict) or set(row) != {
            "mission_id",
            "packet_sha256",
            "packet_manifest_file_sha256",
            "prompt_sha256",
            "request_sha256",
            "binding_sha256",
            "binding_file_sha256",
        }:
            raise EngineeringCampaignPreparationError(
                "prepared campaign mission evidence fields differ"
            )
        mission_id = _identity(row["mission_id"], "mission_id")
        entry = entry_by_id.get(mission_id)
        if entry is None:
            raise EngineeringCampaignPreparationError(
                "prepared campaign mission evidence is not bound"
            )
        mission_root = campaign_root / entry["mission_root"]
        mission_binding = read_json(mission_root / "binding.json")
        packet_manifest = read_json(mission_root / PACKET_MANIFEST_NAME)
        if (
            row["packet_sha256"] != packet_manifest.get("packet_sha256")
            or row["packet_manifest_file_sha256"]
            != file_sha256(mission_root / PACKET_MANIFEST_NAME)
            or row["prompt_sha256"] != file_sha256(mission_root / PROMPT_NAME)
            or row["request_sha256"] != file_sha256(mission_root / REQUEST_NAME)
            or row["binding_sha256"] != mission_binding.get("binding_sha256")
            or row["binding_file_sha256"]
            != file_sha256(mission_root / "binding.json")
        ):
            raise EngineeringCampaignPreparationError(
                f"{mission_id}: prepared mission evidence drifted"
            )
    return preparation


def prepare_engineering_campaign(
    *,
    repo_root: Path,
    tracker_path: Path,
    source_path: Path,
    packet_parent: Path,
    campaign_inbox: Path,
    runtime_contract_path: Path,
) -> dict[str, Any]:
    """Prepare or replay one exact tracker-selected engineering campaign."""

    source_file = Path(source_path)
    source = _source(source_file)
    if source_file.read_bytes() != _json_bytes(source):
        raise EngineeringCampaignPreparationError(
            "campaign source is not canonically materialized"
        )
    tracker = _load_tracker(Path(tracker_path))
    selection = _selection(tracker, source)
    candidates = [
        CampaignCandidate(
            item_id=mission["mission_id"],
            work_kind="engineering",
            compatibility_key=source["compatibility_key"],
            payload_sha256=canonical_sha256(mission),
            estimated_context_tokens=mission["estimated_context_tokens"],
            dependency_ids=tuple(mission["dependency_ids"]),
        )
        for mission in source["missions"]
    ]
    result = build_campaigns(
        candidates,
        completed_dependency_ids=source["completed_dependency_ids"],
        context_token_cap=source["context_token_cap"],
        engineering_mission_cap=CAMPAIGN_SIZE,
    )
    if (
        result.excluded_count != 0
        or len(result.campaigns) != 1
        or len(result.campaigns[0].item_ids) != CAMPAIGN_SIZE
    ):
        raise EngineeringCampaignPreparationError(
            "campaign builder did not produce one lossless 25-mission batch"
        )
    batch = result.campaigns[0]
    inbox = Path(campaign_inbox).resolve()
    packets = Path(packet_parent).resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    packets.mkdir(parents=True, exist_ok=True)
    final_root = inbox / batch.campaign_id
    if final_root.exists():
        return _validate_preparation(
            campaign_root=final_root,
            source=source,
            runtime_contract_path=runtime_contract_path,
        )
    contract = load_runtime_contract(runtime_contract_path)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{batch.campaign_id}.tmp-", dir=inbox)
    )
    created_packets: list[Path] = []
    try:
        missions_root = temporary / "missions"
        missions_root.mkdir()
        source_by_id = {
            mission["mission_id"]: mission for mission in source["missions"]
        }
        evidence: list[dict[str, Any]] = []
        mission_roots: list[Path] = []
        for mission_id in batch.item_ids:
            mission = source_by_id[mission_id]
            packet_root = packets / f"{batch.campaign_id}--{mission_id}"
            mission_root = missions_root / mission_id
            evidence.append(
                _prepare_mission(
                    repo_root=Path(repo_root),
                    packet_root=packet_root,
                    mission_root=mission_root,
                    mission=mission,
                    source=source,
                    contract=contract,
                )
            )
            created_packets.append(packet_root)
            mission_roots.append(mission_root)
        (temporary / SOURCE_NAME).write_bytes(source_file.read_bytes())
        binding = build_engineering_campaign_runtime_binding(
            campaign_root=temporary,
            campaign_id=batch.campaign_id,
            contract_path=runtime_contract_path,
            mission_roots=mission_roots,
        )
        preparation = _seal(
            {
                "schema_version": PREPARATION_SCHEMA,
                "campaign_id": batch.campaign_id,
                "session_id": source["session_id"],
                "tracker_item_id": selection.item_id,
                "goal_selection": {
                    "priority_index": selection.priority_index,
                    "campaign_kind": selection.campaign_kind,
                    "work_mode": selection.work_mode,
                    "dependency_ids": list(selection.dependency_ids),
                    "reason": selection.reason,
                },
                "source_sha256": source["source_sha256"],
                "source_file_sha256": file_sha256(temporary / SOURCE_NAME),
                "campaign_binding_sha256": binding["binding_sha256"],
                "campaign_binding_file_sha256": file_sha256(
                    temporary / BINDING_NAME
                ),
                "mission_count": CAMPAIGN_SIZE,
                "mission_evidence": evidence,
                "authority_claimed": False,
                "completion_claimed": False,
                "preparation_sha256": ZERO_SHA256,
            },
            "preparation_sha256",
        )
        _write_exclusive(temporary / PREPARATION_NAME, preparation)
        os.replace(temporary, final_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        for packet in created_packets:
            shutil.rmtree(packet, ignore_errors=True)
        raise
    return _validate_preparation(
        campaign_root=final_root,
        source=source,
        runtime_contract_path=runtime_contract_path,
    )


__all__ = [
    "EngineeringCampaignPreparationError",
    "PREPARATION_NAME",
    "SOURCE_NAME",
    "prepare_engineering_campaign",
    "seal_engineering_campaign_source",
]
