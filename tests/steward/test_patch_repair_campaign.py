from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.steward.patch_repair_campaign import (
    TERMINAL_NAME,
    CampaignLimits,
    PatchRepairCampaignError,
    run_patch_repair_campaign,
    verify_campaign_terminal,
)

PACKET = "a" * 64
SOURCE = "b" * 64
EVIDENCE = "c" * 64


def _proposal(attempt: int, *, text: str | None = None) -> dict:
    replacement = text or f"value = {attempt}\n"
    return {
        "edits": [
            {
                "path": "src/worker.py",
                "expected_sha256": SOURCE,
                "replacement_text": replacement,
            }
        ],
        "authority_claimed": False,
        "completion_claimed": False,
    }


def _result(
    *,
    passed: bool,
    repairable: bool,
    code: str,
    diagnostic: str,
) -> dict:
    return {
        "passed": passed,
        "repairable": repairable,
        "diagnostic_code": code,
        "diagnostic": diagnostic,
        "evidence": [{"path": "pytest.txt", "sha256": EVIDENCE}],
    }


def _run(root: Path, proposal_supplier, attempt_runner, **kwargs: object) -> dict:
    return run_patch_repair_campaign(
        campaign_root=root,
        mission_id="mf-p6-16-02-test",
        packet_sha256=PACKET,
        editable_paths=["src/worker.py"],
        limits=kwargs.pop(
            "limits",
            CampaignLimits(max_attempts=3, timeout_seconds=60),
        ),
        proposal_supplier=proposal_supplier,
        attempt_runner=attempt_runner,
        **kwargs,
    )


def test_success_persists_and_replays_without_callback_reissue(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    calls = {"proposal": 0, "runner": 0}

    def proposal_supplier(attempt: int, previous: dict | None) -> dict:
        calls["proposal"] += 1
        assert previous is None
        return _proposal(attempt)

    def runner(proposal: dict, attempt: int) -> dict:
        calls["runner"] += 1
        assert proposal["attempt"] == attempt == 1
        return _result(
            passed=True,
            repairable=False,
            code="PASS",
            diagnostic="focused tests passed",
        )

    terminal = _run(root, proposal_supplier, runner)
    replay = _run(
        root,
        lambda *_: pytest.fail("proposal was reissued"),
        lambda *_: pytest.fail("runner was reissued"),
    )

    assert terminal["outcome"] == "SUCCESS"
    assert terminal == replay == verify_campaign_terminal(root)
    assert calls == {"proposal": 1, "runner": 1}
    assert terminal["attempt_count"] == 1
    assert terminal["attempts"][0]["proposal_sha256"]
    assert terminal["attempts"][0]["result_sha256"]


def test_deterministic_nonrepairable_failure_terminates_honestly(
    tmp_path: Path,
) -> None:
    terminal = _run(
        tmp_path / "campaign",
        lambda attempt, _: _proposal(attempt),
        lambda *_: _result(
            passed=False,
            repairable=False,
            code="CONTRACT_MISMATCH",
            diagnostic="the bounded contract cannot be satisfied",
        ),
    )

    assert terminal["outcome"] == "FAILED_DETERMINISTIC"
    assert terminal["attempt_count"] == 1


def test_repair_exhaustion_persists_every_proposal_and_result(tmp_path: Path) -> None:
    terminal = _run(
        tmp_path / "campaign",
        lambda attempt, _: _proposal(attempt),
        lambda _, attempt: _result(
            passed=False,
            repairable=True,
            code=f"FAIL_{attempt}",
            diagnostic=f"distinct focused failure {attempt}",
        ),
        limits=CampaignLimits(
            max_attempts=3,
            timeout_seconds=60,
            no_progress_limit=2,
        ),
    )

    assert terminal["outcome"] == "REPAIR_EXHAUSTED"
    assert terminal["attempt_count"] == 3
    assert len({row["proposal_sha256"] for row in terminal["attempts"]}) == 3
    assert len({row["result_sha256"] for row in terminal["attempts"]}) == 3


def test_timeout_after_proposal_blocks_runner_and_persists_terminal(
    tmp_path: Path,
) -> None:
    now = [0.0]
    runner_calls = 0

    def proposal_supplier(attempt: int, _: dict | None) -> dict:
        now[0] = 6.0
        return _proposal(attempt)

    def runner(*_: object) -> dict:
        nonlocal runner_calls
        runner_calls += 1
        return {}

    terminal = _run(
        tmp_path / "campaign",
        proposal_supplier,
        runner,
        limits=CampaignLimits(max_attempts=3, timeout_seconds=5),
        monotonic=lambda: now[0],
    )

    assert terminal["outcome"] == "TIMEOUT"
    assert terminal["attempt_count"] == 1
    assert terminal["attempts"][0]["result_sha256"] is None
    assert runner_calls == 0


def test_repeated_diagnostic_terminates_no_progress(tmp_path: Path) -> None:
    terminal = _run(
        tmp_path / "campaign",
        lambda attempt, _: _proposal(attempt),
        lambda *_: _result(
            passed=False,
            repairable=True,
            code="SAME_FAILURE",
            diagnostic="the same focused assertion failed",
        ),
        limits=CampaignLimits(
            max_attempts=5,
            timeout_seconds=60,
            no_progress_limit=2,
        ),
    )

    assert terminal["outcome"] == "NO_PROGRESS"
    assert terminal["attempt_count"] == 2
    assert all(row["result_sha256"] for row in terminal["attempts"])


def test_repeated_proposal_terminates_before_duplicate_runner_call(
    tmp_path: Path,
) -> None:
    runner_calls = 0

    def runner(*_: object) -> dict:
        nonlocal runner_calls
        runner_calls += 1
        return _result(
            passed=False,
            repairable=True,
            code=f"FAIL_{runner_calls}",
            diagnostic=f"failure {runner_calls}",
        )

    terminal = _run(
        tmp_path / "campaign",
        lambda *_: _proposal(1, text="same = True\n"),
        runner,
    )

    assert terminal["outcome"] == "NO_PROGRESS"
    assert terminal["attempt_count"] == 2
    assert terminal["attempts"][1]["result_sha256"] is None
    assert runner_calls == 1


def test_callback_exception_becomes_hashed_deterministic_failure(
    tmp_path: Path,
) -> None:
    def runner(*_: object) -> dict:
        raise ValueError("sensitive detail is not persisted")

    terminal = _run(
        tmp_path / "campaign",
        lambda attempt, _: _proposal(attempt),
        runner,
    )
    result_path = tmp_path / "campaign" / terminal["attempts"][0]["result_file"]
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert terminal["outcome"] == "FAILED_DETERMINISTIC"
    assert result["diagnostic"] == "ValueError: callback failed closed"
    assert "sensitive detail" not in result_path.read_text(encoding="utf-8")


def test_incomplete_or_tampered_durable_state_blocks_reissue(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    root.mkdir()
    with pytest.raises(PatchRepairCampaignError, match="reconciliation"):
        _run(root, lambda attempt, _: _proposal(attempt), lambda *_: {})

    root.rmdir()
    terminal = _run(
        root,
        lambda attempt, _: _proposal(attempt),
        lambda *_: _result(
            passed=True,
            repairable=False,
            code="PASS",
            diagnostic="passed",
        ),
    )
    terminal_path = root / TERMINAL_NAME
    tampered = dict(terminal)
    tampered["outcome"] = "FAILED_CLOSED"
    terminal_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(PatchRepairCampaignError, match="self-hash mismatch"):
        _run(root, lambda *_: {}, lambda *_: {})


def test_invalid_scope_authority_and_noop_edits_fail_closed(tmp_path: Path) -> None:
    invalid_proposals = [
        {
            **_proposal(1),
            "authority_claimed": True,
        },
        {
            **_proposal(1),
            "edits": [
                {
                    "path": "../outside.py",
                    "expected_sha256": SOURCE,
                    "replacement_text": "changed = True\n",
                }
            ],
        },
        {
            **_proposal(1),
            "edits": [
                {
                    "path": "src/worker.py",
                    "expected_sha256": (__import__("hashlib").sha256(b"same\n").hexdigest()),
                    "replacement_text": "same\n",
                }
            ],
        },
    ]
    for index, proposal in enumerate(invalid_proposals):
        terminal = _run(
            tmp_path / f"campaign-{index}",
            lambda *_args, value=proposal: value,
            lambda *_: pytest.fail("invalid proposal reached the runner"),
        )
        assert terminal["outcome"] == "FAILED_CLOSED"
        assert terminal["attempt_count"] == 0


def test_terminal_verifier_rejects_path_substitution_and_extra_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "campaign"
    terminal = _run(
        root,
        lambda attempt, _: _proposal(attempt),
        lambda *_: _result(
            passed=True,
            repairable=False,
            code="PASS",
            diagnostic="passed",
        ),
    )
    (root / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(PatchRepairCampaignError, match="unexpected path set"):
        verify_campaign_terminal(root)

    (root / "unexpected.json").unlink()
    terminal["attempts"][0]["proposal_file"] = "../outside.json"
    terminal["terminal_sha256"] = "0" * 64
    terminal["terminal_sha256"] = (
        __import__("hashlib")
        .sha256(
            json.dumps(
                terminal,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        .hexdigest()
    )
    (root / TERMINAL_NAME).write_text(
        json.dumps(terminal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PatchRepairCampaignError, match="proposal path mismatch"):
        verify_campaign_terminal(root)
