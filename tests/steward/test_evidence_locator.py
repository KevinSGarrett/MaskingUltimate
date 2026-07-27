from __future__ import annotations

import copy
import hashlib
import json

import pytest

from maskfactory.steward.evidence_locator import (
    EvidenceLocatorError,
    build_evidence_locator,
    seal_evidence_locator,
    validate_evidence_locator,
    write_evidence_locator,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _entry(*, disposition: str = "accepted", parent: str | None = "campaign-25") -> dict:
    artifacts = [
        {
            "role": "input",
            "name": "mission_binding",
            "sha256": _sha("input"),
            "bytes": 5,
            "location": "qa/live_verification/mission_binding.json",
        },
        {
            "role": "runtime",
            "name": "runtime_contract",
            "sha256": _sha("runtime"),
            "bytes": 7,
            "location": "configs/runtime.json",
        },
        {
            "role": "output",
            "name": "campaign_packet",
            "sha256": _sha("output"),
            "bytes": 6,
            "location": "qa/live_verification/campaign_packet.json",
        },
        {
            "role": "terminal",
            "name": "terminal_receipt",
            "sha256": _sha("terminal"),
            "bytes": 8,
            "location": "qa/live_verification/terminal_receipt.json",
        },
    ]
    if disposition != "accepted":
        artifacts = artifacts[:1]
    return {
        "tracker_item": "MF-P6-19.01",
        "parent_campaign_id": parent,
        "disposition": disposition,
        "source": {
            "commit_sha": "a" * 40,
            "tree_sha": "b" * 40,
            "path": "src/maskfactory/steward/engineering_campaign_runtime.py",
        },
        "artifacts": artifacts,
        "locations": {
            "repository_relative": ["qa/live_verification/campaign_packet.json"],
            "pod_relative": [],
            "compact_recovery_relative": ["manifests/campaign_packet.json"],
        },
        "replay_command": "python -m pytest tests/steward/test_engineering_campaign_runtime.py -q",
        "limitations": ["This entry does not rerun immutable accepted work."],
        "supersedes": [],
    }


def _locator(*, entries: list[dict] | None = None) -> dict:
    return build_evidence_locator(
        entries=entries or [_entry()],
        authority_file_sha256={
            "Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md": _sha(
                "plan28"
            ),
            "Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md": _sha(
                "item24"
            ),
        },
        limitations=["The locator is an index, not a release or completion claim."],
    )


def test_builded_locator_is_deterministic_and_writeable(tmp_path) -> None:
    first = _locator()
    second = _locator()
    assert first == second
    validate_evidence_locator(first)
    destination = tmp_path / "locator.json"
    write_evidence_locator(destination, first)
    assert json.loads(destination.read_text(encoding="utf-8")) == first


def test_accepted_entry_requires_output_and_terminal() -> None:
    entry = _entry()
    entry["artifacts"] = entry["artifacts"][:-1]
    with pytest.raises(EvidenceLocatorError, match="output and terminal"):
        _locator(entries=[entry])


def test_historical_and_blocked_entries_remain_recorded_without_acceptance() -> None:
    historical = _entry(disposition="historical_provenance_only", parent=None)
    historical["tracker_item"] = "MF-P4-11.23"
    blocked = _entry(disposition="blocked", parent="campaign-visual")
    blocked["tracker_item"] = "MF-P6-17.03"
    locator = _locator(entries=[historical, blocked])
    assert [entry["disposition"] for entry in locator["entries"]] == [
        "historical_provenance_only",
        "blocked",
    ]
    assert locator["completion_credit_claimed"] is False


def test_tampering_relative_paths_hashes_and_duplicate_parent_are_rejected() -> None:
    locator = _locator()
    changed = copy.deepcopy(locator)
    changed["entries"][0]["locations"]["repository_relative"] = ["../escape.json"]
    with pytest.raises(EvidenceLocatorError, match="escapes"):
        validate_evidence_locator(seal_evidence_locator(changed))

    changed = copy.deepcopy(locator)
    changed["entries"].append(copy.deepcopy(changed["entries"][0]))
    changed["entries"].sort(key=lambda entry: (entry["tracker_item"], entry["parent_campaign_id"] or ""))
    with pytest.raises(EvidenceLocatorError, match="sorted and unique"):
        validate_evidence_locator(seal_evidence_locator(changed))

    changed = copy.deepcopy(locator)
    changed["self_sha256"] = "f" * 64
    with pytest.raises(EvidenceLocatorError, match="self hash"):
        validate_evidence_locator(changed)
