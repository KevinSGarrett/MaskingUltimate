from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys

import pytest

from maskfactory.steward.evidence_locator import (
    EvidenceLocatorError,
    build_evidence_locator,
    seal_evidence_locator,
    validate_evidence_locator,
    verify_repository_evidence,
    write_evidence_locator,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


AUTHORITY_CONTENT = {
    "Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md": "plan28",
    "Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md": "item24",
}


def _write_authority_files(root) -> None:
    for location, content in AUTHORITY_CONTENT.items():
        path = root / location
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


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
    repository_locations = ["qa/live_verification/campaign_packet.json"]
    if disposition != "accepted":
        artifacts = artifacts[:1]
        repository_locations = [artifacts[0]["location"]]
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
            "repository_relative": repository_locations,
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
        authority_file_sha256={location: _sha(content) for location, content in AUTHORITY_CONTENT.items()},
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


def test_repository_locations_require_exact_artifact_bindings() -> None:
    changed = _locator()
    changed["entries"][0]["locations"]["repository_relative"] = [
        "qa/live_verification/unbound.json"
    ]
    with pytest.raises(EvidenceLocatorError, match="lacks an exact artifact binding"):
        validate_evidence_locator(seal_evidence_locator(changed))


def test_repository_evidence_verification_checks_exact_bytes_and_hashes(tmp_path) -> None:
    locator = _locator()
    location = "qa/live_verification/campaign_packet.json"
    artifact_path = tmp_path / location
    artifact_path.parent.mkdir(parents=True)
    _write_authority_files(tmp_path)

    with pytest.raises(EvidenceLocatorError, match="absent or not a regular file"):
        verify_repository_evidence(locator, tmp_path)

    artifact_path.write_bytes(b"output")
    verify_repository_evidence(locator, tmp_path)

    artifact_path.write_bytes(b"tampered")
    with pytest.raises(EvidenceLocatorError, match="byte mismatch"):
        verify_repository_evidence(locator, tmp_path)

    artifact_path.write_bytes(b"x" * 6)
    with pytest.raises(EvidenceLocatorError, match="SHA-256 mismatch"):
        verify_repository_evidence(locator, tmp_path)


def test_repository_evidence_verification_requires_current_authority_files(tmp_path) -> None:
    locator = _locator()
    artifact_path = tmp_path / "qa/live_verification/campaign_packet.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"output")

    with pytest.raises(EvidenceLocatorError, match="authority is absent"):
        verify_repository_evidence(locator, tmp_path)

    _write_authority_files(tmp_path)
    verify_repository_evidence(locator, tmp_path)

    authority_path = tmp_path / next(iter(AUTHORITY_CONTENT))
    authority_path.write_text("drift", encoding="utf-8")
    with pytest.raises(EvidenceLocatorError, match="authority SHA-256 mismatch"):
        verify_repository_evidence(locator, tmp_path)


def test_authority_paths_are_relative_and_cannot_escape() -> None:
    locator = _locator()
    locator["authority_file_sha256"] = {"../authority.md": _sha("authority")}
    with pytest.raises(EvidenceLocatorError, match="escapes"):
        validate_evidence_locator(seal_evidence_locator(locator))


def test_read_only_verifier_cli_checks_bound_repository_bytes(tmp_path) -> None:
    _write_authority_files(tmp_path)
    artifact_path = tmp_path / "qa/live_verification/campaign_packet.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"output")
    locator_path = tmp_path / "qa/live_verification/locator.json"
    write_evidence_locator(locator_path, _locator())

    command = [
        sys.executable,
        "tools/verify_completion_evidence_locator.py",
        "--repository-root",
        str(tmp_path),
        "--locator",
        "qa/live_verification/locator.json",
    ]
    passed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["status"] == "PASS"

    authority_path = tmp_path / next(iter(AUTHORITY_CONTENT))
    authority_path.write_text("drift", encoding="utf-8")
    failed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["status"] == "FAIL_CLOSED"


def test_read_only_verifier_cli_rejects_locator_escape(tmp_path) -> None:
    command = [
        sys.executable,
        "tools/verify_completion_evidence_locator.py",
        "--repository-root",
        str(tmp_path),
        "--locator",
        "../locator.json",
    ]
    failed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["status"] == "FAIL_CLOSED"
