from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from maskfactory.steward.core import (
    AUTHORITY_KEYS,
    BINDING_SCHEMA,
    TERMINAL_RECEIPT_SCHEMA,
    AmbiguousMissionError,
    canonical_sha256,
    seal_binding,
)
from maskfactory.steward.engineering_campaign_runtime import (
    BINDING_NAME,
    CAMPAIGN_SIZE,
    EngineeringCampaignRuntimeController,
    EngineeringCampaignRuntimeError,
    build_engineering_campaign_runtime_binding,
    validate_engineering_campaign_runtime_binding,
    validate_engineering_campaign_runtime_terminal,
)
from maskfactory.steward.runtime import (
    LAUNCH_RECEIPT_SCHEMA,
    SHUTDOWN_RECEIPT_SCHEMA,
    SUBMISSION_RECEIPT_SCHEMA,
    StewardRuntimeController,
    atomic_write_json,
    file_sha256,
    load_runtime_contract,
    read_json,
)

CONTRACT_PATH = Path("configs/self_hosted_steward_runtime_v1.json")


def _request(contract: dict, job_id: str) -> dict:
    return {
        "model": contract["server"]["served_model"],
        "messages": [
            {"role": "system", "content": "Return bounded advisory JSON."},
            {"role": "user", "content": f"Review immutable mission {job_id}."},
        ],
        "temperature": 0,
        "seed": 1337,
        "max_tokens": 200,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bounded_review",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["decision", "authority_claimed"],
                    "properties": {
                        "decision": {"const": "ADVISE"},
                        "authority_claimed": {"const": False},
                    },
                },
                "strict": True,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }


def _prepare_campaign(tmp_path: Path) -> tuple[Path, list[Path], Path]:
    contract = load_runtime_contract(CONTRACT_PATH)
    campaign_root = tmp_path / "campaign"
    missions_root = campaign_root / "missions"
    missions_root.mkdir(parents=True)
    mission_roots: list[Path] = []
    for sequence in range(1, CAMPAIGN_SIZE + 1):
        job_id = f"mission-{sequence:02d}"
        root = missions_root / job_id
        root.mkdir()
        request_path = root / "request.json"
        atomic_write_json(request_path, _request(contract, job_id))
        payload = hashlib.sha256(f"payload:{job_id}".encode()).hexdigest()
        binding = seal_binding(
            {
                "schema_version": BINDING_SCHEMA,
                "session_id": "session-1",
                "job_id": job_id,
                "payload_sha256": payload,
                "model_tree_sha256": contract["model"]["tree_sha256"],
                "runtime_sha256": contract["contract_sha256"],
                "input_sha256": {"request.json": file_sha256(request_path)},
                "output_namespace": f"session-1/{job_id}",
                "requires_replay": True,
                "authority": {key: False for key in sorted(AUTHORITY_KEYS)},
            }
        )
        atomic_write_json(root / "binding.json", binding)
        mission_roots.append(root)
    database = tmp_path / "steward.sqlite"
    build_engineering_campaign_runtime_binding(
        campaign_root=campaign_root,
        campaign_id="campaign-25",
        contract_path=CONTRACT_PATH,
        mission_roots=mission_roots,
    )
    return campaign_root, mission_roots, database


def _install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_job_id: str | None = None,
    launch_error: bool = False,
) -> dict[str, object]:
    state: dict[str, object] = {
        "alive": False,
        "launch_attempts": 0,
        "launches": 0,
        "submits": [],
        "shutdowns": 0,
        "pid": 43210,
        "start_token": "owned-service-start-token",
    }

    def fake_launch(self: StewardRuntimeController) -> dict:
        state["launch_attempts"] = int(state["launch_attempts"]) + 1
        if launch_error:
            raise RuntimeError("simulated runtime launch failure")
        admitted = self.admit()
        assert admitted["outcome"] in {"admitted", "duplicate_nonterminal"}
        binding = read_json(self.binding_path)
        self.ledger.mark_running(
            binding["session_id"],
            binding["job_id"],
            owner_pid=int(state["pid"]),
            owner_start_token=str(state["start_token"]),
        )
        receipt = {
            "schema_version": LAUNCH_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "binding_sha256": binding["binding_sha256"],
            "runtime_contract_sha256": self.contract["contract_sha256"],
            "pid": state["pid"],
            "process_group_id": state["pid"],
            "owner_start_token": state["start_token"],
            "port": self.port,
            "comfyui_queue_state": "unavailable",
            "command_sha256": "c" * 64,
            "created_at": 1.0,
        }
        atomic_write_json(self.launch_receipt_path, receipt)
        state["alive"] = True
        state["launches"] = int(state["launches"]) + 1
        return receipt

    def fake_health(self: StewardRuntimeController) -> dict:
        if not state["alive"]:
            raise RuntimeError("fake runtime is not alive")
        return {
            "url": "http://127.0.0.1:18008/v1/models",
            "served_model": self.contract["server"]["served_model"],
        }

    def fake_submit(
        self: StewardRuntimeController, request_path: Path
    ) -> dict:
        binding = read_json(self.binding_path)
        request_sha256 = file_sha256(request_path)
        self.ledger.record_request_intent(
            binding["session_id"],
            binding["job_id"],
            request_sha256=request_sha256,
        )
        submits = state["submits"]
        assert isinstance(submits, list)
        submits.append(binding["job_id"])
        if binding["job_id"] == fail_job_id:
            raise AmbiguousMissionError("simulated lost acknowledgement")
        proposal = {"decision": "ADVISE", "authority_claimed": False}
        proposal_canonical = canonical_sha256(proposal)
        for run_number in (1, 2):
            response_path = self.mission_root / f"response_run{run_number}.json"
            proposal_path = self.mission_root / f"proposal_run{run_number}.json"
            atomic_write_json(
                response_path,
                {"choices": [{"message": {"content": proposal}}]},
            )
            atomic_write_json(proposal_path, proposal)
            self.ledger.record_run(
                binding["session_id"],
                binding["job_id"],
                run_number=run_number,
                request_sha256=request_sha256,
                response_sha256=file_sha256(response_path),
                proposal_sha256=file_sha256(proposal_path),
                proposal_canonical_sha256=proposal_canonical,
            )
        proposal_path = self.mission_root / "proposal.json"
        atomic_write_json(proposal_path, proposal)
        terminal = {
            "schema_version": TERMINAL_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "payload_sha256": binding["payload_sha256"],
            "binding_sha256": binding["binding_sha256"],
            "state": "completed",
            "proposal_canonical_sha256": proposal_canonical,
            "authority_claimed": False,
        }
        atomic_write_json(self.terminal_receipt_path, terminal)
        reconciled = self.ledger.reconcile_recorded_owner(
            binding["session_id"],
            binding["job_id"],
            terminal_receipt=terminal,
        )
        receipt = {
            "schema_version": SUBMISSION_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "request_sha256": request_sha256,
            "proposal_sha256": file_sha256(proposal_path),
            "proposal_canonical_sha256": proposal_canonical,
            "run_count": 2,
            "terminal_outcome": reconciled["outcome"],
            "created_at": 2.0,
        }
        atomic_write_json(self.mission_root / "submission_receipt.json", receipt)
        return receipt

    def fake_shutdown(self: StewardRuntimeController) -> dict:
        binding = read_json(self.binding_path)
        launch = read_json(self.launch_receipt_path)
        state["alive"] = False
        state["shutdowns"] = int(state["shutdowns"]) + 1
        receipt = {
            "schema_version": SHUTDOWN_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "pid": launch["pid"],
            "owner_start_token": launch["owner_start_token"],
            "process_group_id": launch["process_group_id"],
            "owned_process_absent": True,
            "loopback_port_closed": True,
            "forced": False,
            "created_at": 3.0,
        }
        atomic_write_json(self.shutdown_receipt_path, receipt)
        released = self.ledger.record_release(
            binding["session_id"],
            binding["job_id"],
            release_kind="direct_process_exit",
            release_sha256=file_sha256(self.shutdown_receipt_path),
        )
        receipt["release_sha256"] = released["release_sha256"]
        receipt["handoff_ready"] = True
        return receipt

    monkeypatch.setattr(StewardRuntimeController, "launch", fake_launch)
    monkeypatch.setattr(StewardRuntimeController, "health", fake_health)
    monkeypatch.setattr(StewardRuntimeController, "submit", fake_submit)
    monkeypatch.setattr(StewardRuntimeController, "shutdown", fake_shutdown)
    monkeypatch.setattr(
        EngineeringCampaignRuntimeController,
        "_owned_process_alive",
        staticmethod(lambda _receipt: bool(state["alive"])),
    )
    monkeypatch.setattr(
        EngineeringCampaignRuntimeController,
        "_port_open",
        staticmethod(lambda _host, _port: bool(state["alive"])),
    )
    return state


def test_binding_requires_exact_unique_25_missions(tmp_path: Path) -> None:
    campaign_root, mission_roots, _database = _prepare_campaign(tmp_path)
    binding = validate_engineering_campaign_runtime_binding(
        campaign_root / BINDING_NAME,
        campaign_root=campaign_root,
        contract_path=CONTRACT_PATH,
    )
    assert binding["mission_count"] == 25
    assert [entry["sequence"] for entry in binding["mission_entries"]] == list(
        range(1, 26)
    )

    other = tmp_path / "too-small"
    (other / "missions").mkdir(parents=True)
    with pytest.raises(EngineeringCampaignRuntimeError, match="exactly 25"):
        build_engineering_campaign_runtime_binding(
            campaign_root=other,
            campaign_id="too-small",
            contract_path=CONTRACT_PATH,
            mission_roots=mission_roots[:24],
        )

    (mission_roots[3] / "request.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EngineeringCampaignRuntimeError, match="drift"):
        validate_engineering_campaign_runtime_binding(
            campaign_root / BINDING_NAME,
            campaign_root=campaign_root,
            contract_path=CONTRACT_PATH,
        )


def test_one_runtime_lifetime_executes_and_releases_all_25(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_root, _mission_roots, database = _prepare_campaign(tmp_path)
    state = _install_fake_runtime(monkeypatch)
    controller = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    )

    terminal = controller.run()

    assert terminal["outcome"] == "SUCCESS"
    assert terminal["completed_count"] == 25
    assert terminal["failed_count"] == 0
    assert terminal["service_generation_count"] == 1
    assert state["launches"] == 1
    assert state["shutdowns"] == 1
    assert state["submits"] == [f"mission-{index:02d}" for index in range(1, 26)]
    assert all(row["handoff_ready"] for row in terminal["mission_outcomes"])
    assert validate_engineering_campaign_runtime_terminal(
        campaign_root / "engineering_campaign_runtime_terminal.json",
        campaign_root=campaign_root,
        contract_path=CONTRACT_PATH,
        database=database,
    ) == terminal

    assert controller.run() == terminal
    assert state["launches"] == 1
    assert len(state["submits"]) == 25


def test_ambiguous_request_is_never_reissued_and_unrelated_missions_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_root, mission_roots, database = _prepare_campaign(tmp_path)
    state = _install_fake_runtime(monkeypatch, fail_job_id="mission-05")
    terminal = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    ).run()

    assert terminal["outcome"] == "FAILED_CLOSED"
    assert terminal["completed_count"] == 24
    assert terminal["failed_count"] == 1
    assert state["submits"].count("mission-05") == 1
    assert len(state["submits"]) == 25
    failure = read_json(mission_roots[4] / "campaign_failure_receipt.json")
    assert failure["reason_code"] == "ambiguous_request_completion"
    assert failure["retry_permitted"] is False
    assert next(
        row for row in terminal["mission_outcomes"] if row["job_id"] == "mission-05"
    )["handoff_ready"]


def test_restart_reconstructs_live_owned_service_without_second_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_root, mission_roots, database = _prepare_campaign(tmp_path)
    state = _install_fake_runtime(monkeypatch)
    first = StewardRuntimeController(
        contract_path=CONTRACT_PATH,
        mission_root=mission_roots[0],
        database=database,
    )
    first.launch()
    first.submit(mission_roots[0] / "request.json")
    assert state["launches"] == 1

    terminal = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    ).run()

    assert terminal["outcome"] == "SUCCESS"
    assert state["launches"] == 1
    assert state["shutdowns"] == 1
    assert len(state["submits"]) == 25


def test_restart_with_durable_request_intent_never_reissues_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_root, mission_roots, database = _prepare_campaign(tmp_path)
    state = _install_fake_runtime(monkeypatch)
    first = StewardRuntimeController(
        contract_path=CONTRACT_PATH,
        mission_root=mission_roots[0],
        database=database,
    )
    first.launch()
    binding = read_json(first.binding_path)
    first.ledger.record_request_intent(
        binding["session_id"],
        binding["job_id"],
        request_sha256=file_sha256(mission_roots[0] / "request.json"),
    )

    terminal = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    ).run()

    assert terminal["outcome"] == "FAILED_CLOSED"
    assert terminal["completed_count"] == 24
    assert terminal["failed_count"] == 1
    assert "mission-01" not in state["submits"]
    assert state["submits"] == [
        f"mission-{index:02d}" for index in range(2, 26)
    ]
    assert state["launches"] == 1
    assert state["shutdowns"] == 1
    failure = read_json(mission_roots[0] / "campaign_failure_receipt.json")
    assert failure["reason_code"] == "ambiguous_request_intent"
    assert failure["retry_permitted"] is False


def test_restart_after_attach_before_request_resumes_without_second_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_root, mission_roots, database = _prepare_campaign(tmp_path)
    state = _install_fake_runtime(monkeypatch)
    owner = StewardRuntimeController(
        contract_path=CONTRACT_PATH,
        mission_root=mission_roots[0],
        database=database,
    )
    owner.launch()
    owner.submit(mission_roots[0] / "request.json")
    attached = StewardRuntimeController(
        contract_path=CONTRACT_PATH,
        mission_root=mission_roots[1],
        database=database,
    )
    preparer = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    )
    preparer._attach(attached, owner_controller=owner)
    assert attached.ledger.get("session-1", "mission-02")["request_sha256"] is None

    terminal = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    ).run()

    assert terminal["outcome"] == "SUCCESS"
    assert state["launches"] == 1
    assert state["shutdowns"] == 1
    assert state["submits"] == [
        "mission-01",
        *[f"mission-{index:02d}" for index in range(2, 26)],
    ]


def test_runtime_launch_failure_is_not_retried_and_all_missions_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_root, _mission_roots, database = _prepare_campaign(tmp_path)
    state = _install_fake_runtime(monkeypatch, launch_error=True)

    terminal = EngineeringCampaignRuntimeController(
        contract_path=CONTRACT_PATH,
        campaign_root=campaign_root,
        database=database,
    ).run()

    assert terminal["outcome"] == "FAILED_CLOSED"
    assert terminal["completed_count"] == 0
    assert terminal["failed_count"] == 25
    assert terminal["service_generation_count"] == 0
    assert state["launch_attempts"] == 1
    assert state["launches"] == 0
    assert state["submits"] == []
    assert all(row["handoff_ready"] for row in terminal["mission_outcomes"])
