from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from maskfactory.steward.campaign_adoption_packet import (
    PACKET_NAME,
    CampaignAdoptionPacketError,
    build_campaign_adoption_packet,
    validate_campaign_adoption_packet,
)
from maskfactory.steward.patch_repair_campaign import (
    CampaignLimits,
    run_patch_repair_campaign,
)

PACKET = "a" * 64
SOURCE = "b" * 64
EVIDENCE = "c" * 64


def _campaign(tmp_path: Path, *, passed: bool) -> Path:
    root = tmp_path / ("campaign-pass" if passed else "campaign-fail")
    run_patch_repair_campaign(
        campaign_root=root,
        mission_id="mf-p6-16-04-test",
        packet_sha256=PACKET,
        editable_paths=["src/worker.py"],
        limits=CampaignLimits(max_attempts=1, timeout_seconds=60),
        proposal_supplier=lambda *_: {
            "edits": [
                {
                    "path": "src/worker.py",
                    "expected_sha256": SOURCE,
                    "replacement_text": "value = 42\n",
                }
            ],
            "authority_claimed": False,
            "completion_claimed": False,
        },
        attempt_runner=lambda *_: {
            "passed": passed,
            "repairable": False,
            "diagnostic_code": "PASS" if passed else "FAIL",
            "diagnostic": "focused tests passed" if passed else "deterministic failure",
            "evidence": [{"path": "pytest.txt", "sha256": EVIDENCE}],
        },
    )
    return root


def _build(campaign: Path, output: Path, **overrides: object) -> dict:
    values = {
        "decision": "ADOPT",
        "decision_reason": "The bounded campaign and focused tests passed.",
        "limitations": [],
        "exceptions": [],
        "tracker_proposals": [
            {
                "item_id": "MF-P6-16.04",
                "status": "complete",
                "percent": 100,
                "evidence": "Bound campaign and focused-test hashes validated.",
            }
        ],
    }
    values.update(overrides)
    return build_campaign_adoption_packet(
        campaign_root=campaign,
        output_root=output,
        **values,
    )


def _reseal(packet: dict) -> dict:
    packet["packet_sha256"] = "0" * 64
    packet["packet_sha256"] = hashlib.sha256(
        json.dumps(
            packet,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return packet


def test_builds_one_exact_adopt_packet_with_paths_hashes_and_tracker_proposal(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path, passed=True)
    output = tmp_path / "adoption"

    packet = _build(campaign, output)
    validated = validate_campaign_adoption_packet(
        output,
        campaign_root=campaign,
    )

    assert validated == packet
    assert packet["decision"] == "ADOPT"
    assert packet["campaign_terminal"]["outcome"] == "SUCCESS"
    assert packet["changes"][0]["path"] == "src/worker.py"
    assert packet["changes"][0]["proposal_file_sha256"]
    assert packet["focused_tests"][0]["status"] == "PASS"
    assert packet["focused_tests"][0]["result_file_sha256"]
    assert packet["tracker_proposals"][0]["status"] == "complete"
    assert all(value is False for value in packet["authority"].values())


def test_missing_and_duplicate_packets_fail_validation(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, passed=True)
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(CampaignAdoptionPacketError, match="exactly one"):
        validate_campaign_adoption_packet(missing, campaign_root=campaign)

    output = tmp_path / "adoption"
    _build(campaign, output)
    nested = output / "nested"
    nested.mkdir()
    (nested / "duplicate.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(CampaignAdoptionPacketError, match="exactly one"):
        validate_campaign_adoption_packet(output, campaign_root=campaign)


def test_unsupported_decision_and_output_reuse_fail_closed(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, passed=True)
    with pytest.raises(CampaignAdoptionPacketError, match="unsupported"):
        _build(
            campaign,
            tmp_path / "unsupported",
            decision="MAYBE",
        )

    output = tmp_path / "adoption"
    _build(campaign, output)
    with pytest.raises(CampaignAdoptionPacketError, match="already exists"):
        _build(campaign, output)
    with pytest.raises(CampaignAdoptionPacketError, match="outside"):
        _build(campaign, campaign / "adoption")


def test_adopt_and_tracker_completion_cannot_overclaim_failure(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path, passed=False)
    with pytest.raises(CampaignAdoptionPacketError, match="overclaims"):
        _build(campaign, tmp_path / "adopt-failure")

    with pytest.raises(CampaignAdoptionPacketError, match="overclaims"):
        _build(
            campaign,
            tmp_path / "partial-complete",
            decision="PARTIALLY_ADOPT",
            decision_reason="Some proposal content may be useful.",
            limitations=["Focused tests failed deterministically."],
        )


def test_partial_and_reject_require_limitations(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, passed=False)
    for decision in ("PARTIALLY_ADOPT", "REJECT"):
        with pytest.raises(CampaignAdoptionPacketError, match="limitation"):
            _build(
                campaign,
                tmp_path / decision.lower(),
                decision=decision,
                tracker_proposals=[],
                limitations=[],
            )


def test_partial_packet_preserves_exceptions_and_noncomplete_tracker_proposal(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path, passed=False)
    output = tmp_path / "partial"
    packet = _build(
        campaign,
        output,
        decision="PARTIALLY_ADOPT",
        decision_reason="The diagnosis is useful but the patch is not accepted.",
        limitations=["Focused tests failed."],
        exceptions=[
            {
                "code": "FOCUSED_TEST_FAILURE",
                "detail": "The deterministic fixture failed.",
                "evidence_sha256": EVIDENCE,
            }
        ],
        tracker_proposals=[
            {
                "item_id": "MF-P6-16.04",
                "status": "partially_complete",
                "percent": 50,
                "evidence": "Diagnosis retained; patch rejected.",
            }
        ],
    )

    assert validate_campaign_adoption_packet(
        output,
        campaign_root=campaign,
    ) == packet
    assert packet["exceptions"][0]["code"] == "FOCUSED_TEST_FAILURE"


def test_resealed_authority_decision_and_evidence_tampering_fail_closed(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path, passed=True)
    output = tmp_path / "adoption"
    packet = _build(campaign, output)
    packet_path = output / PACKET_NAME

    packet["authority"]["tracker"] = True
    _reseal(packet)
    packet_path.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CampaignAdoptionPacketError, match="authority"):
        validate_campaign_adoption_packet(output, campaign_root=campaign)

    shutil.rmtree(output)
    packet = _build(campaign, output)
    packet["changes"][0]["proposal_file_sha256"] = "d" * 64
    _reseal(packet)
    packet_path.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CampaignAdoptionPacketError, match="evidence mismatch"):
        validate_campaign_adoption_packet(output, campaign_root=campaign)
