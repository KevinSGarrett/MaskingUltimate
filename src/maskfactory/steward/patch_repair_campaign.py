"""Durable bounded patch/test/diagnose/repair campaign state machine.

The controller owns deterministic state and evidence only.  Patch application
and focused testing are injected by the caller and must operate inside an
already-isolated staging area.  The controller never invokes Git, a provider,
or infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "maskfactory_patch_repair_campaign.v1"
BINDING_NAME = "campaign_binding.json"
TERMINAL_NAME = "campaign_terminal.json"
ZERO_SHA256 = "0" * 64
TERMINAL_OUTCOMES = frozenset(
    {
        "SUCCESS",
        "FAILED_DETERMINISTIC",
        "REPAIR_EXHAUSTED",
        "TIMEOUT",
        "NO_PROGRESS",
        "FAILED_CLOSED",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_AUTHORITY_CEILING = {
    "git": False,
    "github": False,
    "credentials": False,
    "runpod": False,
    "infrastructure": False,
    "destructive_actions": False,
    "tracker": False,
    "final_adoption": False,
}


class PatchRepairCampaignError(RuntimeError):
    """Campaign input or durable state is unsafe or contradictory."""


@dataclass(frozen=True)
class CampaignLimits:
    max_attempts: int
    timeout_seconds: float
    no_progress_limit: int = 2
    max_edit_bytes: int = 512 * 1024

    def validate(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts <= 0
        ):
            raise PatchRepairCampaignError("max_attempts must be positive")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise PatchRepairCampaignError("timeout_seconds must be positive")
        if (
            not isinstance(self.no_progress_limit, int)
            or isinstance(self.no_progress_limit, bool)
            or self.no_progress_limit < 2
        ):
            raise PatchRepairCampaignError("no_progress_limit must be at least two")
        if (
            not isinstance(self.max_edit_bytes, int)
            or isinstance(self.max_edit_bytes, bool)
            or self.max_edit_bytes <= 0
        ):
            raise PatchRepairCampaignError("max_edit_bytes must be positive")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = _canonical_sha256(sealed)
    return sealed


def _verify_self_hash(value: Mapping[str, Any], field: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise PatchRepairCampaignError(f"{field} is invalid")
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if _canonical_sha256(zeroed) != declared:
        raise PatchRepairCampaignError(f"{field} canonical self-hash mismatch")


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8") + b"\n"
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PatchRepairCampaignError(
            f"durable campaign path already exists: {path.name}"
        ) from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PatchRepairCampaignError(f"campaign evidence is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PatchRepairCampaignError(f"campaign evidence must be an object: {path}")
    return value


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise PatchRepairCampaignError(f"{field} is invalid")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PatchRepairCampaignError(f"{field} is invalid")
    return value


def _relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PatchRepairCampaignError(f"{field} must be a relative path")
    if any(character in value for character in "\r\n\x00"):
        raise PatchRepairCampaignError(f"{field} contains a prohibited character")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PatchRepairCampaignError(f"{field} escapes the staging root")
    return path.as_posix()


def _binding(
    *,
    mission_id: str,
    packet_sha256: str,
    editable_paths: Sequence[str],
    limits: CampaignLimits,
) -> dict[str, Any]:
    limits.validate()
    normalized_paths = tuple(
        sorted(_relative_path(path, field="editable path") for path in editable_paths)
    )
    if not normalized_paths or len(normalized_paths) != len(set(normalized_paths)):
        raise PatchRepairCampaignError("editable paths must be non-empty and unique")
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": _identifier(mission_id, field="mission_id"),
            "packet_sha256": _sha256(packet_sha256, field="packet_sha256"),
            "editable_paths": list(normalized_paths),
            "limits": {
                "max_attempts": limits.max_attempts,
                "timeout_seconds": limits.timeout_seconds,
                "no_progress_limit": limits.no_progress_limit,
                "max_edit_bytes": limits.max_edit_bytes,
            },
            "authority": dict(_AUTHORITY_CEILING),
            "binding_sha256": ZERO_SHA256,
        },
        "binding_sha256",
    )


def _validate_existing_binding(
    existing: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    _verify_self_hash(existing, "binding_sha256")
    if dict(existing) != dict(expected):
        raise PatchRepairCampaignError("campaign binding differs from durable state")


def _validate_proposal(
    raw: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    attempt: int,
    limits: CampaignLimits,
) -> tuple[dict[str, Any], str]:
    if not isinstance(raw, Mapping) or set(raw) != {
        "edits",
        "authority_claimed",
        "completion_claimed",
    }:
        raise PatchRepairCampaignError("proposal field set mismatch")
    if raw["authority_claimed"] is not False or raw["completion_claimed"] is not False:
        raise PatchRepairCampaignError("proposal attempted to widen authority")
    edits = raw["edits"]
    if not isinstance(edits, list) or not edits:
        raise PatchRepairCampaignError("proposal edits must be a non-empty list")
    editable = frozenset(binding["editable_paths"])
    normalized_edits: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    for edit in edits:
        if not isinstance(edit, Mapping) or set(edit) != {
            "path",
            "expected_sha256",
            "replacement_text",
        }:
            raise PatchRepairCampaignError("proposal edit field set mismatch")
        path = _relative_path(edit["path"], field="proposal edit path")
        if path not in editable:
            raise PatchRepairCampaignError(
                f"{path}: proposal edit is outside the packet scope"
            )
        if path in seen:
            raise PatchRepairCampaignError("proposal edit paths must be unique")
        seen.add(path)
        expected_sha256 = _sha256(
            edit["expected_sha256"],
            field=f"{path} expected_sha256",
        )
        replacement = edit["replacement_text"]
        if not isinstance(replacement, str) or "\x00" in replacement:
            raise PatchRepairCampaignError(
                f"{path}: replacement_text must be UTF-8-compatible text"
            )
        encoded = replacement.encode("utf-8")
        total_bytes += len(encoded)
        if total_bytes > limits.max_edit_bytes:
            raise PatchRepairCampaignError("proposal edits exceed their byte cap")
        if hashlib.sha256(encoded).hexdigest() == expected_sha256:
            raise PatchRepairCampaignError(
                f"{path}: proposal replacement does not change the bound source"
            )
        normalized_edits.append(
            {
                "path": path,
                "expected_sha256": expected_sha256,
                "replacement_text": replacement,
                "replacement_sha256": hashlib.sha256(encoded).hexdigest(),
                "replacement_bytes": len(encoded),
            }
        )
    normalized_edits.sort(key=lambda row: row["path"])
    content_sha256 = _canonical_sha256(normalized_edits)
    proposal = _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": binding["mission_id"],
            "packet_sha256": binding["packet_sha256"],
            "attempt": attempt,
            "edits": normalized_edits,
            "proposal_content_sha256": content_sha256,
            "authority_claimed": False,
            "completion_claimed": False,
            "proposal_sha256": ZERO_SHA256,
        },
        "proposal_sha256",
    )
    return proposal, content_sha256


def _validate_result(
    raw: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    proposal: Mapping[str, Any],
    attempt: int,
) -> tuple[dict[str, Any], str]:
    if not isinstance(raw, Mapping) or set(raw) != {
        "passed",
        "repairable",
        "diagnostic_code",
        "diagnostic",
        "evidence",
    }:
        raise PatchRepairCampaignError("focused-test result field set mismatch")
    if not isinstance(raw["passed"], bool) or not isinstance(raw["repairable"], bool):
        raise PatchRepairCampaignError("focused-test booleans are invalid")
    if raw["passed"] and raw["repairable"]:
        raise PatchRepairCampaignError("a passing test result cannot be repairable")
    code = _identifier(raw["diagnostic_code"], field="diagnostic_code")
    diagnostic = raw["diagnostic"]
    if (
        not isinstance(diagnostic, str)
        or not diagnostic
        or len(diagnostic.encode("utf-8")) > 4096
        or "\x00" in diagnostic
    ):
        raise PatchRepairCampaignError("diagnostic is invalid")
    evidence = raw["evidence"]
    if not isinstance(evidence, list):
        raise PatchRepairCampaignError("focused-test evidence must be a list")
    normalized_evidence: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in evidence:
        if not isinstance(row, Mapping) or set(row) != {"path", "sha256"}:
            raise PatchRepairCampaignError("focused-test evidence row is invalid")
        path = _relative_path(row["path"], field="evidence path")
        if path in seen:
            raise PatchRepairCampaignError("focused-test evidence paths must be unique")
        seen.add(path)
        normalized_evidence.append(
            {
                "path": path,
                "sha256": _sha256(row["sha256"], field=f"{path} evidence SHA-256"),
            }
        )
    normalized_evidence.sort(key=lambda row: row["path"])
    diagnostic_sha256 = _canonical_sha256(
        {
            "passed": raw["passed"],
            "repairable": raw["repairable"],
            "diagnostic_code": code,
            "diagnostic": diagnostic,
        }
    )
    result = _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": binding["mission_id"],
            "packet_sha256": binding["packet_sha256"],
            "attempt": attempt,
            "proposal_sha256": proposal["proposal_sha256"],
            "passed": raw["passed"],
            "repairable": raw["repairable"],
            "diagnostic_code": code,
            "diagnostic": diagnostic,
            "diagnostic_sha256": diagnostic_sha256,
            "evidence": normalized_evidence,
            "result_sha256": ZERO_SHA256,
        },
        "result_sha256",
    )
    return result, diagnostic_sha256


def _synthetic_failure_result(
    *,
    binding: Mapping[str, Any],
    proposal: Mapping[str, Any],
    attempt: int,
    error: Exception,
) -> tuple[dict[str, Any], str]:
    raw = {
        "passed": False,
        "repairable": False,
        "diagnostic_code": "CALLBACK_EXCEPTION",
        "diagnostic": f"{type(error).__name__}: callback failed closed",
        "evidence": [],
    }
    return _validate_result(
        raw,
        binding=binding,
        proposal=proposal,
        attempt=attempt,
    )


def _terminal(
    *,
    binding: Mapping[str, Any],
    outcome: str,
    reason: str,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if outcome not in TERMINAL_OUTCOMES:
        raise PatchRepairCampaignError("terminal outcome is invalid")
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": binding["mission_id"],
            "packet_sha256": binding["packet_sha256"],
            "binding_sha256": binding["binding_sha256"],
            "outcome": outcome,
            "reason": reason,
            "attempt_count": len(attempts),
            "attempts": [dict(row) for row in attempts],
            "authority": dict(_AUTHORITY_CEILING),
            "terminal_sha256": ZERO_SHA256,
        },
        "terminal_sha256",
    )


def verify_campaign_terminal(campaign_root: Path) -> dict[str, Any]:
    """Validate a terminal record and all proposal/result evidence it binds."""

    root = campaign_root.resolve(strict=True)
    binding = _read_json(root / BINDING_NAME)
    _verify_self_hash(binding, "binding_sha256")
    if (
        set(binding)
        != {
            "schema_version",
            "mission_id",
            "packet_sha256",
            "editable_paths",
            "limits",
            "authority",
            "binding_sha256",
        }
        or not isinstance(binding.get("mission_id"), str)
        or not _IDENTIFIER_RE.fullmatch(binding["mission_id"])
        or not isinstance(binding.get("packet_sha256"), str)
        or not _SHA256_RE.fullmatch(binding["packet_sha256"])
        or binding.get("schema_version") != SCHEMA_VERSION
        or binding.get("authority") != _AUTHORITY_CEILING
    ):
        raise PatchRepairCampaignError("campaign binding schema or authority mismatch")
    try:
        bound_limits = CampaignLimits(**binding["limits"])
        regenerated_binding = _binding(
            mission_id=binding["mission_id"],
            packet_sha256=binding["packet_sha256"],
            editable_paths=binding["editable_paths"],
            limits=bound_limits,
        )
    except (KeyError, TypeError, PatchRepairCampaignError) as exc:
        raise PatchRepairCampaignError("campaign binding semantics are invalid") from exc
    if regenerated_binding != binding:
        raise PatchRepairCampaignError("campaign binding semantic mismatch")
    terminal = _read_json(root / TERMINAL_NAME)
    _verify_self_hash(terminal, "terminal_sha256")
    if (
        set(terminal)
        != {
            "schema_version",
            "mission_id",
            "packet_sha256",
            "binding_sha256",
            "outcome",
            "reason",
            "attempt_count",
            "attempts",
            "authority",
            "terminal_sha256",
        }
        or not isinstance(terminal.get("reason"), str)
        or not terminal["reason"]
        or terminal.get("binding_sha256") != binding.get("binding_sha256")
        or terminal.get("mission_id") != binding.get("mission_id")
        or terminal.get("packet_sha256") != binding.get("packet_sha256")
        or terminal.get("authority") != _AUTHORITY_CEILING
        or terminal.get("outcome") not in TERMINAL_OUTCOMES
    ):
        raise PatchRepairCampaignError("terminal binding or authority mismatch")
    attempts = terminal.get("attempts")
    if not isinstance(attempts, list) or terminal.get("attempt_count") != len(attempts):
        raise PatchRepairCampaignError("terminal attempt accounting mismatch")
    expected_paths = {BINDING_NAME, TERMINAL_NAME}
    for index, row in enumerate(attempts, start=1):
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "attempt",
                "proposal_file",
                "proposal_sha256",
                "result_file",
                "result_sha256",
            }
            or row.get("attempt") != index
        ):
            raise PatchRepairCampaignError("terminal attempt sequence mismatch")
        expected_proposal_name = f"attempt_{index:03d}_proposal.json"
        if row.get("proposal_file") != expected_proposal_name:
            raise PatchRepairCampaignError("terminal proposal path mismatch")
        expected_paths.add(expected_proposal_name)
        proposal_path = root / expected_proposal_name
        proposal = _read_json(proposal_path)
        _verify_self_hash(proposal, "proposal_sha256")
        if (
            set(proposal)
            != {
                "schema_version",
                "mission_id",
                "packet_sha256",
                "attempt",
                "edits",
                "proposal_content_sha256",
                "authority_claimed",
                "completion_claimed",
                "proposal_sha256",
            }
            or proposal["proposal_sha256"] != row.get("proposal_sha256")
            or proposal.get("schema_version") != SCHEMA_VERSION
            or proposal.get("mission_id") != binding.get("mission_id")
            or proposal.get("packet_sha256") != binding.get("packet_sha256")
            or proposal.get("attempt") != index
            or proposal.get("authority_claimed") is not False
            or proposal.get("completion_claimed") is not False
        ):
            raise PatchRepairCampaignError("terminal proposal hash mismatch")
        stored_edits = proposal.get("edits")
        raw_edits: object = stored_edits
        if isinstance(stored_edits, list):
            raw_edits = [
                {
                    "path": edit.get("path"),
                    "expected_sha256": edit.get("expected_sha256"),
                    "replacement_text": edit.get("replacement_text"),
                }
                for edit in stored_edits
                if isinstance(edit, Mapping)
            ]
        raw_proposal = {
            "edits": raw_edits,
            "authority_claimed": proposal.get("authority_claimed"),
            "completion_claimed": proposal.get("completion_claimed"),
        }
        regenerated_proposal, _ = _validate_proposal(
            raw_proposal,
            binding=binding,
            attempt=index,
            limits=bound_limits,
        )
        if regenerated_proposal != proposal:
            raise PatchRepairCampaignError("terminal proposal semantic mismatch")
        result_name = row.get("result_file")
        result_sha256 = row.get("result_sha256")
        if result_name is None and result_sha256 is None:
            continue
        expected_result_name = f"attempt_{index:03d}_result.json"
        if (
            result_name != expected_result_name
            or not isinstance(result_sha256, str)
        ):
            raise PatchRepairCampaignError("terminal result binding is incomplete")
        expected_paths.add(expected_result_name)
        result = _read_json(root / result_name)
        _verify_self_hash(result, "result_sha256")
        if (
            set(result)
            != {
                "schema_version",
                "mission_id",
                "packet_sha256",
                "attempt",
                "proposal_sha256",
                "passed",
                "repairable",
                "diagnostic_code",
                "diagnostic",
                "diagnostic_sha256",
                "evidence",
                "result_sha256",
            }
            or result["result_sha256"] != result_sha256
            or result.get("proposal_sha256") != proposal["proposal_sha256"]
            or result.get("schema_version") != SCHEMA_VERSION
            or result.get("mission_id") != binding.get("mission_id")
            or result.get("packet_sha256") != binding.get("packet_sha256")
            or result.get("attempt") != index
        ):
            raise PatchRepairCampaignError("terminal result hash mismatch")
        raw_result = {
            "passed": result.get("passed"),
            "repairable": result.get("repairable"),
            "diagnostic_code": result.get("diagnostic_code"),
            "diagnostic": result.get("diagnostic"),
            "evidence": result.get("evidence"),
        }
        regenerated_result, _ = _validate_result(
            raw_result,
            binding=binding,
            proposal=proposal,
            attempt=index,
        )
        if regenerated_result != result:
            raise PatchRepairCampaignError("terminal result semantic mismatch")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.iterdir()
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise PatchRepairCampaignError("campaign contains an unexpected path set")
    return terminal


def run_patch_repair_campaign(
    *,
    campaign_root: Path,
    mission_id: str,
    packet_sha256: str,
    editable_paths: Sequence[str],
    limits: CampaignLimits,
    proposal_supplier: Callable[[int, Mapping[str, Any] | None], Mapping[str, Any]],
    attempt_runner: Callable[[Mapping[str, Any], int], Mapping[str, Any]],
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run or replay one bounded campaign with exactly one terminal outcome."""

    expected_binding = _binding(
        mission_id=mission_id,
        packet_sha256=packet_sha256,
        editable_paths=editable_paths,
        limits=limits,
    )
    root = campaign_root.resolve(strict=False)
    if root.exists():
        if (root / TERMINAL_NAME).is_file():
            existing_binding = _read_json(root / BINDING_NAME)
            _validate_existing_binding(existing_binding, expected_binding)
            return verify_campaign_terminal(root)
        raise PatchRepairCampaignError(
            "incomplete campaign requires reconciliation; callback reissue is blocked"
        )
    if not root.parent.is_dir():
        raise PatchRepairCampaignError("campaign parent must already exist")
    root.mkdir()
    _write_exclusive(root / BINDING_NAME, expected_binding)

    started = monotonic()
    attempt_rows: list[dict[str, Any]] = []
    proposal_content_hashes: set[str] = set()
    diagnostic_streak_hash: str | None = None
    diagnostic_streak_count = 0
    previous_result: dict[str, Any] | None = None

    def finish(outcome: str, reason: str) -> dict[str, Any]:
        record = _terminal(
            binding=expected_binding,
            outcome=outcome,
            reason=reason,
            attempts=attempt_rows,
        )
        _write_exclusive(root / TERMINAL_NAME, record)
        return verify_campaign_terminal(root)

    for attempt in range(1, limits.max_attempts + 1):
        if monotonic() - started >= limits.timeout_seconds:
            return finish("TIMEOUT", "campaign timeout reached before next proposal")
        try:
            raw_proposal = proposal_supplier(attempt, deepcopy(previous_result))
            proposal, content_sha256 = _validate_proposal(
                raw_proposal,
                binding=expected_binding,
                attempt=attempt,
                limits=limits,
            )
        except Exception as exc:
            if isinstance(exc, PatchRepairCampaignError):
                reason = str(exc)
            else:
                reason = f"{type(exc).__name__}: proposal callback failed closed"
            return finish("FAILED_CLOSED", reason)

        proposal_name = f"attempt_{attempt:03d}_proposal.json"
        _write_exclusive(root / proposal_name, proposal)
        attempt_row: dict[str, Any] = {
            "attempt": attempt,
            "proposal_file": proposal_name,
            "proposal_sha256": proposal["proposal_sha256"],
            "result_file": None,
            "result_sha256": None,
        }
        attempt_rows.append(attempt_row)
        if content_sha256 in proposal_content_hashes:
            return finish("NO_PROGRESS", "proposal content repeated without progress")
        proposal_content_hashes.add(content_sha256)
        if monotonic() - started >= limits.timeout_seconds:
            return finish("TIMEOUT", "campaign timeout reached before focused test")

        try:
            raw_result = attempt_runner(deepcopy(proposal), attempt)
            result, diagnostic_sha256 = _validate_result(
                raw_result,
                binding=expected_binding,
                proposal=proposal,
                attempt=attempt,
            )
        except Exception as exc:
            result, diagnostic_sha256 = _synthetic_failure_result(
                binding=expected_binding,
                proposal=proposal,
                attempt=attempt,
                error=exc,
            )
        result_name = f"attempt_{attempt:03d}_result.json"
        _write_exclusive(root / result_name, result)
        attempt_row["result_file"] = result_name
        attempt_row["result_sha256"] = result["result_sha256"]
        previous_result = result

        if monotonic() - started >= limits.timeout_seconds:
            return finish("TIMEOUT", "campaign timeout reached after focused test")
        if result["passed"]:
            return finish("SUCCESS", "focused tests passed")
        if not result["repairable"]:
            return finish(
                "FAILED_DETERMINISTIC",
                "focused-test failure was marked non-repairable",
            )
        if diagnostic_sha256 == diagnostic_streak_hash:
            diagnostic_streak_count += 1
        else:
            diagnostic_streak_hash = diagnostic_sha256
            diagnostic_streak_count = 1
        if diagnostic_streak_count >= limits.no_progress_limit:
            return finish(
                "NO_PROGRESS",
                "focused-test diagnostic repeated without progress",
            )
    return finish("REPAIR_EXHAUSTED", "maximum repair attempts exhausted")


__all__ = [
    "BINDING_NAME",
    "CampaignLimits",
    "PatchRepairCampaignError",
    "SCHEMA_VERSION",
    "TERMINAL_NAME",
    "TERMINAL_OUTCOMES",
    "run_patch_repair_campaign",
    "verify_campaign_terminal",
]
