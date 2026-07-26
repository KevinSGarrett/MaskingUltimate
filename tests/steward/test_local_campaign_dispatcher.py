from __future__ import annotations

import json
import shutil
from pathlib import Path

from maskfactory.steward.engineering_campaign_runtime import (
    BINDING_NAME,
    build_engineering_campaign_runtime_binding,
)
from maskfactory.steward.local_campaign_dispatcher import (
    DISPATCH_TERMINAL_NAME,
    INTENT_NAME,
    LocalEngineeringCampaignDispatcher,
)

from .test_engineering_campaign_runtime import CONTRACT_PATH, _prepare_campaign


class Child:
    pid = 43210


def _prepared_inbox(tmp_path: Path) -> tuple[Path, Path]:
    original, _mission_roots, _database = _prepare_campaign(tmp_path / "source")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    campaign = inbox / "campaign-25"
    original.rename(campaign)
    return inbox, campaign


def _add_campaign(
    tmp_path: Path,
    *,
    inbox: Path,
    campaign_id: str,
    source_name: str,
) -> Path:
    original, _mission_roots, _database = _prepare_campaign(
        tmp_path / source_name
    )
    campaign = inbox / campaign_id
    shutil.copytree(original, campaign)
    (campaign / BINDING_NAME).unlink()
    (campaign / "binding.json").unlink()
    mission_roots = sorted((campaign / "missions").iterdir())
    build_engineering_campaign_runtime_binding(
        campaign_root=campaign,
        campaign_id=campaign_id,
        contract_path=CONTRACT_PATH,
        mission_roots=mission_roots,
    )
    return campaign


def _dispatcher(
    tmp_path: Path,
    *,
    popen_factory,
    process_identity_probe,
    process_discovery=lambda _campaign, _guard: (),
) -> LocalEngineeringCampaignDispatcher:
    support = tmp_path / "support"
    support.mkdir(exist_ok=True)
    manager = support / "manager.py"
    guard = support / "guard.py"
    runtime = support / "runtime.py"
    for path in (manager, guard, runtime):
        path.write_text("# immutable test support\n", encoding="utf-8")
    return LocalEngineeringCampaignDispatcher(
        inbox_root=tmp_path / "inbox",
        state_root=tmp_path / "state",
        runtime_contract_path=CONTRACT_PATH,
        steward_database=tmp_path / "steward.sqlite",
        lease_database=tmp_path / "leases.sqlite",
        lease_manager_path=manager,
        guard_tool_path=guard,
        runtime_tool_path=runtime,
        popen_factory=popen_factory,
        process_identity_probe=process_identity_probe,
        process_discovery=process_discovery,
    )


def test_launch_intent_precedes_one_guarded_child_and_replay_does_not_reissue(
    tmp_path: Path,
) -> None:
    _inbox, campaign = _prepared_inbox(tmp_path)
    launches: list[list[str]] = []
    alive = {Child.pid: "start-43210"}

    def popen(command, **kwargs):
        intent = json.loads(
            (
                tmp_path
                / "state"
                / "campaign-25"
                / INTENT_NAME
            ).read_text(encoding="utf-8")
        )
        assert intent["state"] == "prepared"
        launches.append(command)
        assert kwargs["cwd"] == str(campaign)
        assert kwargs["start_new_session"] is True
        return Child()

    dispatcher = _dispatcher(
        tmp_path,
        popen_factory=popen,
        process_identity_probe=lambda pid: alive.get(pid),
    )

    first = dispatcher.poll_once()
    second = dispatcher.poll_once()

    assert len(launches) == 1
    assert first[0]["state"] == second[0]["state"] == "active"
    command = launches[0]
    assert "--job-id" in command and "campaign-25" in command
    assert "--payload-sha256" in command
    assert "self_hosted_llm_engineering_campaign" in command
    assert "run" in command
    assert "serverless" not in " ".join(command).lower()
    assert "openrouter" not in " ".join(command).lower()


def test_dead_guard_without_campaign_terminal_fails_closed_and_never_reissues(
    tmp_path: Path,
) -> None:
    _prepared_inbox(tmp_path)
    launches = 0
    alive = {Child.pid: "start-43210"}

    def popen(_command, **_kwargs):
        nonlocal launches
        launches += 1
        return Child()

    dispatcher = _dispatcher(
        tmp_path,
        popen_factory=popen,
        process_identity_probe=lambda pid: alive.get(pid),
    )
    dispatcher.poll_once()
    alive.clear()

    terminal = dispatcher.poll_once()[0]
    replay = dispatcher.poll_once()

    assert terminal["outcome"] == "failed_closed"
    assert terminal["reason_code"] == "ambiguous_guarded_child_exit"
    assert terminal["retry_permitted"] is False
    assert launches == 1
    assert replay == ()
    assert (
        tmp_path / "state" / "campaign-25" / DISPATCH_TERMINAL_NAME
    ).is_file()


def test_crash_before_pid_persist_reconstructs_exact_guard_process(
    tmp_path: Path,
) -> None:
    _prepared_inbox(tmp_path)
    launches = 0

    def popen(_command, **_kwargs):
        nonlocal launches
        launches += 1
        return Child()

    dispatcher = _dispatcher(
        tmp_path,
        popen_factory=popen,
        process_identity_probe=lambda pid: (
            "recovered-start" if pid == Child.pid else None
        ),
        process_discovery=lambda campaign, _guard: (
            ((Child.pid, "recovered-start"),)
            if campaign == "campaign-25"
            else ()
        ),
    )
    campaign_root, binding = dispatcher.discover()[0]
    # Use the production intent constructor path once, then simulate the exact
    # crash window by removing the persisted PID/start-token fields.
    dispatcher._launch(campaign_root=campaign_root, binding=binding)
    path = tmp_path / "state" / "campaign-25" / INTENT_NAME
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted["state"] = "prepared"
    persisted["pid"] = None
    persisted["process_start_token"] = None
    persisted["intent_sha256"] = "0" * 64
    from maskfactory.steward.core import canonical_sha256

    persisted["intent_sha256"] = canonical_sha256(persisted)
    path.write_text(
        json.dumps(persisted, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    launches = 0

    result = dispatcher.poll_once()

    assert result[0]["state"] == "active"
    assert launches == 0
    reconstructed = json.loads(path.read_text(encoding="utf-8"))
    assert reconstructed["pid"] == Child.pid
    assert reconstructed["process_start_token"] == "recovered-start"


def test_same_identity_on_other_route_blocks_local_launch(tmp_path: Path) -> None:
    _prepared_inbox(tmp_path)
    launches = 0

    def popen(_command, **_kwargs):
        nonlocal launches
        launches += 1
        return Child()

    dispatcher = _dispatcher(
        tmp_path,
        popen_factory=popen,
        process_identity_probe=lambda _pid: None,
    )

    result = dispatcher.poll_once(excluded_campaign_ids=("campaign-25",))

    assert result[0]["state"] == "blocked"
    assert launches == 0
    assert not (
        tmp_path / "state" / "campaign-25" / INTENT_NAME
    ).exists()


def test_existing_later_sorted_active_intent_prevents_new_local_launch(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _add_campaign(
        tmp_path,
        inbox=inbox,
        campaign_id="a-new-campaign",
        source_name="source-a",
    )
    active_root = _add_campaign(
        tmp_path,
        inbox=inbox,
        campaign_id="z-active-campaign",
        source_name="source-z",
    )
    alive = {Child.pid: "start-43210"}
    launches: list[str] = []

    def popen(command, **_kwargs):
        launches.append(command[command.index("--job-id") + 1])
        return Child()

    dispatcher = _dispatcher(
        tmp_path,
        popen_factory=popen,
        process_identity_probe=lambda pid: alive.get(pid),
    )
    binding = dispatcher._binding(active_root)
    dispatcher._launch(campaign_root=active_root, binding=binding)
    launches.clear()

    results = dispatcher.poll_once()

    assert launches == []
    by_campaign = {result["campaign_id"]: result for result in results}
    assert by_campaign["z-active-campaign"]["state"] == "active"
    assert by_campaign["a-new-campaign"]["state"] == "queued"
