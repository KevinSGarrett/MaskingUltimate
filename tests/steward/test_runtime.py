from __future__ import annotations

import io
import json
import urllib.error
from copy import deepcopy
from pathlib import Path

import pytest

from maskfactory.steward import (
    AmbiguousMissionError,
    MissionBindingError,
    MissionConflictError,
    seal_binding,
)
from maskfactory.steward.core import AUTHORITY_KEYS, BINDING_SCHEMA, StewardLedger
from maskfactory.steward.runtime import (
    AMBIGUOUS_COMPLETION_SCHEMA,
    REQUEST_REJECTION_SCHEMA,
    StewardRuntimeController,
    atomic_write_json,
    build_vllm_command,
    file_sha256,
    load_runtime_contract,
    probe_comfyui_queue,
    validate_request,
    validate_runtime_files,
)

CONTRACT_PATH = Path("configs/self_hosted_steward_runtime_v1.json")


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def request_document(contract: dict) -> dict:
    return {
        "model": contract["server"]["served_model"],
        "messages": [
            {"role": "system", "content": "Return bounded advisory JSON."},
            {"role": "user", "content": "Review one exact packet."},
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


def prepare_controller(tmp_path: Path) -> tuple[StewardRuntimeController, dict, Path]:
    contract = load_runtime_contract(CONTRACT_PATH)
    root = tmp_path / "session-1" / "runtime-job"
    root.mkdir(parents=True)
    request_path = root / "request.json"
    atomic_write_json(request_path, request_document(contract))
    binding = seal_binding(
        {
            "schema_version": BINDING_SCHEMA,
            "session_id": "session-1",
            "job_id": "runtime-job",
            "payload_sha256": "a" * 64,
            "model_tree_sha256": contract["model"]["tree_sha256"],
            "runtime_sha256": contract["contract_sha256"],
            "input_sha256": {"request.json": file_sha256(request_path)},
            "output_namespace": "session-1/runtime-job",
            "requires_replay": True,
            "authority": {key: False for key in sorted(AUTHORITY_KEYS)},
        }
    )
    atomic_write_json(root / "binding.json", binding)
    controller = StewardRuntimeController(
        contract_path=CONTRACT_PATH,
        mission_root=root,
        database=tmp_path / "steward.sqlite",
    )
    controller.admit()
    controller.ledger.mark_running(
        "session-1",
        "runtime-job",
        owner_pid=1234,
        owner_start_token="owned-start-token",
    )
    return controller, binding, request_path


def test_runtime_contract_is_closed_and_builds_exact_vllm_command(
    tmp_path: Path,
) -> None:
    contract = load_runtime_contract(CONTRACT_PATH)
    command = build_vllm_command(contract)

    assert command == [
        contract["engine"]["vllm_executable"],
        "serve",
        contract["model"]["path"],
        "--host",
        "127.0.0.1",
        "--port",
        "18008",
        "--served-model-name",
        "maskfactory-mission-steward-qwen3_5_27b_fp8",
        "--max-model-len",
        "4096",
        "--max-num-seqs",
        "1",
        "--gpu-memory-utilization",
        "0.66",
        "--enforce-eager",
        "--trust-remote-code",
        "--seed",
        "1337",
    ]

    tampered = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    tampered["server"]["host"] = "0.0.0.0"
    tampered_path = tmp_path / "invalid_runtime_contract.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MissionBindingError, match="self-hash"):
        load_runtime_contract(tampered_path)


def test_runtime_byte_validation_covers_model_engine_and_successful_v3(
    tmp_path: Path,
) -> None:
    contract = deepcopy(load_runtime_contract(CONTRACT_PATH))
    model_root = tmp_path / "model"
    validated_root = tmp_path / "validated"
    engine = tmp_path / "bin" / "vllm"
    model_root.mkdir()
    validated_root.mkdir()
    engine.parent.mkdir()
    (model_root / "config.json").write_bytes(b"config")
    (model_root / "model.safetensors.index.json").write_bytes(b"index")
    engine.write_bytes(b"vllm")
    validated_files = {
        "binding.json": "binding_file_sha256",
        "launch_once.sh": "launch_once_sha256",
        "run_atomic_mission.sh": "run_atomic_mission_sha256",
        "run_steward_client.py": "run_steward_client_sha256",
        "acceptance.json": "acceptance_file_sha256",
        "runner_terminal.json": "runner_terminal_sha256",
    }
    for file_name in validated_files:
        (validated_root / file_name).write_bytes(file_name.encode("ascii"))
    contract["model"]["path"] = str(model_root)
    contract["model"]["config_sha256"] = file_sha256(model_root / "config.json")
    contract["model"]["index_sha256"] = file_sha256(
        model_root / "model.safetensors.index.json"
    )
    contract["engine"]["vllm_executable"] = str(engine)
    contract["engine"]["vllm_executable_sha256"] = file_sha256(engine)
    contract["validated_runtime"]["mission_root"] = str(validated_root)
    for file_name, field in validated_files.items():
        contract["validated_runtime"][field] = file_sha256(validated_root / file_name)

    observed = validate_runtime_files(contract)
    assert set(observed) == {
        "model_config",
        "model_index",
        "vllm_executable",
        "validated_binding",
        "validated_launch_once",
        "validated_atomic_runner",
        "validated_client",
        "validated_acceptance",
        "validated_terminal",
    }

    (validated_root / "run_steward_client.py").write_bytes(b"drift")
    with pytest.raises(MissionBindingError, match="runtime binding drift"):
        validate_runtime_files(contract)


def test_submit_persists_two_runs_terminal_and_blocks_reissue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, binding, request_path = prepare_controller(tmp_path)
    monkeypatch.setattr(controller, "health", lambda: {"status": "PASS"})
    proposal = {"decision": "ADVISE", "authority_claimed": False}
    bodies = [
        json.dumps(
            {
                "choices": [{"message": {"content": json.dumps(proposal)}}],
                "usage": {"run": run_number},
            }
        ).encode("utf-8")
        for run_number in (1, 2)
    ]

    def fake_urlopen(_request, *, timeout):
        assert timeout == 300
        return FakeResponse(bodies.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    receipt = controller.submit(request_path)

    assert receipt["terminal_outcome"] == "reconciled_terminal_receipt"
    assert receipt["run_count"] == 2
    assert controller.ledger.get("session-1", "runtime-job")["state"] == "completed"
    assert len(controller.ledger.runs("session-1", "runtime-job")) == 2
    assert controller.terminal_receipt_path.exists()
    assert (controller.mission_root / "proposal.json").exists()
    with pytest.raises(MissionConflictError, match="running mission"):
        controller.submit(request_path)
    assert controller.ledger.admit(binding)["outcome"] == "reconciled_terminal"


def test_submit_requires_request_bytes_in_mission_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _binding, _request_path = prepare_controller(tmp_path)
    monkeypatch.setattr(controller, "health", lambda: {"status": "PASS"})
    outside = tmp_path / "outside_request.json"
    atomic_write_json(outside, request_document(controller.contract))

    with pytest.raises(MissionBindingError, match="escapes mission root"):
        controller.submit(outside)


def test_submit_refuses_authority_claim_and_leaves_ambiguous_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _binding, request_path = prepare_controller(tmp_path)
    monkeypatch.setattr(controller, "health", lambda: {"status": "PASS"})
    unsafe = {"decision": "ADVISE", "authority_claimed": True}
    envelope = json.dumps(
        {"choices": [{"message": {"content": json.dumps(unsafe)}}]}
    ).encode("utf-8")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(envelope),
    )

    with pytest.raises(MissionConflictError, match="authority ceiling"):
        controller.submit(request_path)

    assert controller.ledger.get("session-1", "runtime-job")["request_sha256"]
    assert controller.ledger.runs("session-1", "runtime-job") == []
    reconciled = controller.ledger.reconcile(
        "session-1", "runtime-job", owner_alive=False
    )
    assert reconciled["outcome"] == "recovery_required"
    assert not controller.terminal_receipt_path.exists()


def test_submit_persists_http_schema_rejection_and_terminalizes_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, binding, request_path = prepare_controller(tmp_path)
    monkeypatch.setattr(controller, "health", lambda: {"status": "PASS"})
    body = json.dumps(
        {
            "error": {
                "message": "unsupported JSON schema keyword",
                "type": "BadRequestError",
            }
        }
    ).encode("utf-8")

    def reject(_request, *, timeout):
        assert timeout == 300
        raise urllib.error.HTTPError(
            "http://127.0.0.1:18008/v1/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr("urllib.request.urlopen", reject)

    with pytest.raises(MissionConflictError, match="before generation"):
        controller.submit(request_path)

    response_path = controller.mission_root / "response_run1.json"
    rejection = json.loads(
        (controller.mission_root / "request_rejection.json").read_text(
            encoding="utf-8"
        )
    )
    terminal = json.loads(
        controller.terminal_receipt_path.read_text(encoding="utf-8")
    )
    assert response_path.read_bytes() == body + b"\n"
    assert rejection["schema_version"] == REQUEST_REJECTION_SCHEMA
    assert rejection["http_status"] == 400
    assert rejection["retry_permitted"] is False
    assert terminal["binding_sha256"] == binding["binding_sha256"]
    assert terminal["state"] == "failed"
    assert controller.ledger.get("session-1", "runtime-job")["state"] == "failed"
    with pytest.raises(MissionConflictError, match="running mission"):
        controller.submit(request_path)


def test_submit_transport_ambiguity_persists_no_resend_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _binding, request_path = prepare_controller(tmp_path)
    monkeypatch.setattr(controller, "health", lambda: {"status": "PASS"})
    calls = 0

    def disconnected(_request, *, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 300
        raise urllib.error.URLError("connection reset after request send")

    monkeypatch.setattr("urllib.request.urlopen", disconnected)

    with pytest.raises(AmbiguousMissionError, match="do not reissue"):
        controller.submit(request_path)

    ambiguous = json.loads(
        (controller.mission_root / "ambiguous_completion.json").read_text(
            encoding="utf-8"
        )
    )
    assert ambiguous["schema_version"] == AMBIGUOUS_COMPLETION_SCHEMA
    assert ambiguous["response_persisted"] is False
    assert ambiguous["retry_permitted"] is False
    assert controller.ledger.get("session-1", "runtime-job")["request_sha256"]
    with pytest.raises(AmbiguousMissionError, match="do not reissue"):
        controller.submit(request_path)
    assert calls == 1


def test_shutdown_records_terminal_release_without_touching_unowned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, binding, _request_path = prepare_controller(tmp_path)
    request_sha256 = controller.ledger.get("session-1", "runtime-job")[
        "request_sha256"
    ]
    assert request_sha256 is None
    controller.ledger.record_request_intent(
        "session-1", "runtime-job", request_sha256="1" * 64
    )
    for run_number, response, proposal in (
        (1, "2" * 64, "3" * 64),
        (2, "4" * 64, "5" * 64),
    ):
        controller.ledger.record_run(
            "session-1",
            "runtime-job",
            run_number=run_number,
            request_sha256="1" * 64,
            response_sha256=response,
            proposal_sha256=proposal,
            proposal_canonical_sha256="6" * 64,
        )
    controller.ledger.complete(
        "session-1",
        "runtime-job",
        proposal_canonical_sha256="6" * 64,
        authority_claimed=False,
    )
    atomic_write_json(
        controller.launch_receipt_path,
        {
            "schema_version": "maskfactory_self_hosted_steward_launch_receipt.v1",
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "binding_sha256": binding["binding_sha256"],
            "runtime_contract_sha256": controller.contract["contract_sha256"],
            "pid": 1234,
            "process_group_id": 1234,
            "owner_start_token": "owned-start-token",
            "port": 18008,
            "command_sha256": "7" * 64,
            "created_at": 1.0,
        },
    )
    monkeypatch.setattr(
        StewardLedger,
        "owner_process_alive",
        staticmethod(lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(controller, "_port_open", lambda *_args: False)

    result = controller.shutdown()

    assert result["owned_process_absent"] is True
    assert result["forced"] is False
    assert result["handoff_ready"] is True
    assert controller.ledger.handoff_ready("session-1", "runtime-job")
    replay = controller.shutdown()
    assert replay["release_sha256"] == result["release_sha256"]
    assert replay["handoff_ready"] is True


def test_request_contract_fails_closed() -> None:
    contract = load_runtime_contract(CONTRACT_PATH)
    request = request_document(contract)
    validate_request(contract, request)

    unsafe = deepcopy(request)
    unsafe["response_format"]["json_schema"]["strict"] = False
    with pytest.raises(MissionBindingError, match="strict JSON schema"):
        validate_request(contract, unsafe)


def test_comfyui_queue_probe_blocks_live_work_and_records_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            json.dumps({"queue_running": [], "queue_pending": []}).encode("utf-8")
        ),
    )
    assert probe_comfyui_queue()["state"] == "empty"

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            json.dumps({"queue_running": [["job"]], "queue_pending": []}).encode(
                "utf-8"
            )
        ),
    )
    with pytest.raises(MissionConflictError, match="not empty"):
        probe_comfyui_queue()

    def unavailable(*_args, **_kwargs):
        raise OSError("not listening")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    assert probe_comfyui_queue()["state"] == "unavailable"
