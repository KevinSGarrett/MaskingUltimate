from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.steward import engineering_campaign_preparer
from maskfactory.steward.core import canonical_sha256
from maskfactory.steward.engineering_campaign_preparer import (
    EngineeringCampaignPreparationError,
    prepare_engineering_campaign,
    seal_engineering_campaign_source,
)
from maskfactory.steward.engineering_campaign_runtime import (
    CAMPAIGN_SIZE,
    validate_engineering_campaign_runtime_binding,
)
from maskfactory.steward.goal_selector import PLAN27_ITEM_ORDER
from maskfactory.steward.runtime import atomic_write_json, file_sha256, read_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "configs" / "self_hosted_steward_runtime_v1.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    source = repo / "src" / "bounded.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@maskfactory.invalid")
    _git(repo, "config", "user.name", "MaskFactory Tests")
    _git(repo, "add", "src/bounded.py")
    _git(repo, "commit", "-m", "fixture")
    return repo


def _tracker(path: Path, *, selected_item: str = "MF-P6-13.01") -> Path:
    items = {
        item_id: {
            "id": item_id,
            "status": "complete",
            "description": "",
            "orphaned": False,
            "conditional": False,
        }
        for item_id in PLAN27_ITEM_ORDER
    }
    items[selected_item]["status"] = "open"
    atomic_write_json(path, {"items": items})
    return path


def _source(
    path: Path,
    *,
    tracker_item_id: str = "MF-P6-13.01",
    context_token_cap: int = 2500,
) -> Path:
    missions = [
        {
            "mission_id": f"engineering-{sequence:02d}",
            "source_paths": ["src/bounded.py"],
            "scope_roots": ["src"],
            "task": f"Review bounded implementation concern {sequence}.",
            "estimated_context_tokens": 100,
            "dependency_ids": [],
        }
        for sequence in range(1, CAMPAIGN_SIZE + 1)
    ]
    sealed = seal_engineering_campaign_source(
        session_id="self-hosted-campaign-test",
        tracker_item_id=tracker_item_id,
        compatibility_key="qwen35-engineering-review-v1",
        completed_dependency_ids=[],
        context_token_cap=context_token_cap,
        max_packet_bytes=32 * 1024,
        missions=missions,
    )
    atomic_write_json(path, sealed)
    return path


def _prepare(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    repo = _repository(tmp_path)
    tracker = _tracker(tmp_path / "tracker.json")
    source = _source(tmp_path / "source.json")
    packet_parent = tmp_path / "packets"
    inbox = tmp_path / "inbox"
    packet_parent.mkdir()
    preparation = prepare_engineering_campaign(
        repo_root=repo,
        tracker_path=tracker,
        source_path=source,
        packet_parent=packet_parent,
        campaign_inbox=inbox,
        runtime_contract_path=CONTRACT_PATH,
    )
    return preparation, inbox / preparation["campaign_id"], repo, source


def test_prepares_exact_tracker_bound_25_mission_campaign(tmp_path: Path) -> None:
    preparation, campaign_root, _repo, _source_path = _prepare(tmp_path)

    assert preparation["mission_count"] == CAMPAIGN_SIZE
    assert preparation["tracker_item_id"] == "MF-P6-13.01"
    assert preparation["authority_claimed"] is False
    assert preparation["completion_claimed"] is False
    assert len(preparation["mission_evidence"]) == CAMPAIGN_SIZE
    binding = validate_engineering_campaign_runtime_binding(
        campaign_root / "engineering_campaign_runtime_binding.json",
        campaign_root=campaign_root,
        contract_path=CONTRACT_PATH,
    )
    assert binding["mission_count"] == CAMPAIGN_SIZE
    assert [row["job_id"] for row in binding["mission_entries"]] == [
        f"engineering-{sequence:02d}"
        for sequence in range(1, CAMPAIGN_SIZE + 1)
    ]
    for evidence in preparation["mission_evidence"]:
        mission = campaign_root / "missions" / evidence["mission_id"]
        request = read_json(mission / "request.json")
        assert request["temperature"] == 0
        assert request["seed"] == 1337
        assert request["chat_template_kwargs"] == {"enable_thinking": False}
        assert (
            request["response_format"]["json_schema"]["schema"]["properties"][
                "authority_claimed"
            ]
            == {"const": False}
        )
        assert evidence["request_sha256"] == file_sha256(mission / "request.json")


def test_exact_replay_and_evidence_drift_refusal(tmp_path: Path) -> None:
    preparation, campaign_root, repo, source = _prepare(tmp_path)
    replay = prepare_engineering_campaign(
        repo_root=repo,
        tracker_path=tmp_path / "tracker.json",
        source_path=source,
        packet_parent=tmp_path / "packets",
        campaign_inbox=tmp_path / "inbox",
        runtime_contract_path=CONTRACT_PATH,
    )
    assert replay == preparation

    prompt = campaign_root / "missions" / "engineering-01" / "prompt.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    with pytest.raises(Exception, match="drift|hash mismatch"):
        prepare_engineering_campaign(
            repo_root=repo,
            tracker_path=tmp_path / "tracker.json",
            source_path=source,
            packet_parent=tmp_path / "packets",
            campaign_inbox=tmp_path / "inbox",
            runtime_contract_path=CONTRACT_PATH,
        )


def test_repeated_source_set_uses_one_git_packet_snapshot_per_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original = engineering_campaign_preparer.build_repository_packet

    def counted_build(**kwargs):
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(engineering_campaign_preparer, "build_repository_packet", counted_build)
    preparation, campaign_root, _repo, _source_path = _prepare(tmp_path)

    assert calls == 1
    assert preparation["mission_count"] == CAMPAIGN_SIZE
    for sequence in range(1, CAMPAIGN_SIZE + 1):
        manifest = read_json(
            campaign_root / "missions" / f"engineering-{sequence:02d}" / "repository_packet_manifest.json"
        )
        assert manifest["packet_sha256"] == preparation["mission_evidence"][0]["packet_sha256"]


def test_tracker_selection_mismatch_fails_before_packet_creation(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    tracker = _tracker(tmp_path / "tracker.json", selected_item="MF-P6-13.02")
    source = _source(tmp_path / "source.json", tracker_item_id="MF-P6-13.01")
    packets = tmp_path / "packets"
    inbox = tmp_path / "inbox"
    packets.mkdir()

    with pytest.raises(
        EngineeringCampaignPreparationError,
        match="current pursuing-goal item",
    ):
        prepare_engineering_campaign(
            repo_root=repo,
            tracker_path=tracker,
            source_path=source,
            packet_parent=packets,
            campaign_inbox=inbox,
            runtime_contract_path=CONTRACT_PATH,
        )
    assert list(packets.iterdir()) == []


def test_lossless_batch_and_clean_git_bytes_are_mandatory(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    tracker = _tracker(tmp_path / "tracker.json")
    source = _source(tmp_path / "source.json", context_token_cap=2499)
    packets = tmp_path / "packets"
    packets.mkdir()

    with pytest.raises(
        EngineeringCampaignPreparationError,
        match="one lossless 25-mission batch",
    ):
        prepare_engineering_campaign(
            repo_root=repo,
            tracker_path=tracker,
            source_path=source,
            packet_parent=packets,
            campaign_inbox=tmp_path / "inbox",
            runtime_contract_path=CONTRACT_PATH,
        )

    source_value = read_json(source)
    source_value["context_token_cap"] = 2500
    source_value["source_sha256"] = "0" * 64
    source_value["source_sha256"] = canonical_sha256(source_value)
    source.write_text(
        json.dumps(source_value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "src" / "bounded.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(Exception, match="uncommitted|worktree bytes"):
        prepare_engineering_campaign(
            repo_root=repo,
            tracker_path=tracker,
            source_path=source,
            packet_parent=packets,
            campaign_inbox=tmp_path / "inbox",
            runtime_contract_path=CONTRACT_PATH,
        )


def test_noncanonical_source_materialization_fails_closed(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    tracker = _tracker(tmp_path / "tracker.json")
    source = _source(tmp_path / "source.json")
    value = copy.deepcopy(read_json(source))
    source.write_text(json.dumps(value), encoding="utf-8")
    packets = tmp_path / "packets"
    packets.mkdir()

    with pytest.raises(
        EngineeringCampaignPreparationError,
        match="not canonically materialized",
    ):
        prepare_engineering_campaign(
            repo_root=repo,
            tracker_path=tracker,
            source_path=source,
            packet_parent=packets,
            campaign_inbox=tmp_path / "inbox",
            runtime_contract_path=CONTRACT_PATH,
        )


def test_standalone_preparer_resolves_project_imports(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "run_engineering_campaign_preparer.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--campaign-inbox" in result.stdout
