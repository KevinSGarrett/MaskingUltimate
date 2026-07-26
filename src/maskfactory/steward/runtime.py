"""Reproducible runtime controller for bounded self-hosted steward missions.

The controller keeps the model advisory.  It owns only the vLLM process group
that it starts, grants exactly one durable request intent, persists responses
before terminal reconciliation, and never treats an idempotent ledger lookup as
permission to send a model request again.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .core import (
    AUTHORITY_KEYS,
    TERMINAL_RECEIPT_SCHEMA,
    MissionBindingError,
    MissionConflictError,
    StewardLedger,
    canonical_sha256,
)

RUNTIME_CONTRACT_SCHEMA = "maskfactory_self_hosted_steward_runtime_contract.v1"
LAUNCH_RECEIPT_SCHEMA = "maskfactory_self_hosted_steward_launch_receipt.v1"
SHUTDOWN_RECEIPT_SCHEMA = "maskfactory_self_hosted_steward_shutdown_receipt.v1"
SUBMISSION_RECEIPT_SCHEMA = "maskfactory_self_hosted_steward_submission_receipt.v1"
SHA256_LENGTH = 64

_TOP_LEVEL_KEYS = {
    "schema_version",
    "contract_sha256",
    "pod",
    "model",
    "engine",
    "server",
    "submission",
    "authority",
    "validated_runtime",
}
_POD_KEYS = {
    "id",
    "name",
    "gpu",
    "gpu_count",
    "network_volume_id",
    "mount",
}
_MODEL_KEYS = {
    "path",
    "revision",
    "architecture",
    "quantization",
    "tree_sha256",
    "file_count",
    "file_bytes",
    "config_sha256",
    "index_sha256",
}
_ENGINE_KEYS = {
    "vllm_executable",
    "vllm_executable_sha256",
    "python_executable",
    "vllm_version",
}
_SERVER_KEYS = {
    "host",
    "default_port",
    "served_model",
    "max_model_len",
    "max_num_seqs",
    "gpu_memory_utilization",
    "enforce_eager",
    "trust_remote_code",
    "seed",
    "startup_timeout_seconds",
    "shutdown_timeout_seconds",
}
_SUBMISSION_KEYS = {
    "path",
    "request_timeout_seconds",
    "temperature",
    "seed",
    "max_output_tokens",
    "strict_json_schema",
    "replay_runs",
    "thinking_enabled",
}
_VALIDATED_RUNTIME_KEYS = {
    "mission_root",
    "binding_file_sha256",
    "launch_once_sha256",
    "run_atomic_mission_sha256",
    "run_steward_client_sha256",
    "acceptance_file_sha256",
    "runner_terminal_sha256",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise MissionBindingError(f"{field} keys do not match the closed contract")


def _require_sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MissionBindingError(f"{field} must be lowercase SHA-256")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MissionBindingError(f"{field} must be a positive integer")
    return value


def _require_bounded_float(
    value: object, field: str, *, minimum: float, maximum: float
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not minimum <= float(value) <= maximum
    ):
        raise MissionBindingError(f"{field} is outside its closed range")
    return float(value)


def load_runtime_contract(path: Path) -> dict[str, Any]:
    """Load and fail closed on a self-hashed runtime contract."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MissionBindingError("runtime contract is unreadable") from exc
    if not isinstance(value, dict):
        raise MissionBindingError("runtime contract must be an object")
    _require_exact_keys(value, _TOP_LEVEL_KEYS, "runtime contract")
    if value["schema_version"] != RUNTIME_CONTRACT_SCHEMA:
        raise MissionBindingError("runtime contract schema mismatch")
    declared = _require_sha256(value["contract_sha256"], "contract_sha256")
    zeroed = deepcopy(value)
    zeroed["contract_sha256"] = "0" * SHA256_LENGTH
    if canonical_sha256(zeroed) != declared:
        raise MissionBindingError("runtime contract canonical self-hash mismatch")

    for field, keys in (
        ("pod", _POD_KEYS),
        ("model", _MODEL_KEYS),
        ("engine", _ENGINE_KEYS),
        ("server", _SERVER_KEYS),
        ("submission", _SUBMISSION_KEYS),
        ("validated_runtime", _VALIDATED_RUNTIME_KEYS),
    ):
        nested = value[field]
        if not isinstance(nested, dict):
            raise MissionBindingError(f"{field} must be an object")
        _require_exact_keys(nested, keys, field)

    pod = value["pod"]
    if (
        pod["id"] != "68psfqtaogg7s7"
        or pod["name"] != "vitreous_beige_centipede"
        or pod["gpu"] != "NVIDIA RTX 6000 Ada Generation"
        or pod["gpu_count"] != 1
        or pod["network_volume_id"] != "o9qv2ld91c"
        or pod["mount"] != "/workspace"
    ):
        raise MissionBindingError("runtime contract targets an unauthorized Pod")

    model = value["model"]
    for field in ("tree_sha256", "config_sha256", "index_sha256"):
        _require_sha256(model[field], f"model.{field}")
    _require_positive_int(model["file_count"], "model.file_count")
    _require_positive_int(model["file_bytes"], "model.file_bytes")
    if model["quantization"] != "fp8":
        raise MissionBindingError("model quantization must remain fp8")

    engine = value["engine"]
    _require_sha256(
        engine["vllm_executable_sha256"], "engine.vllm_executable_sha256"
    )
    server = value["server"]
    if server["host"] != "127.0.0.1":
        raise MissionBindingError("self-hosted endpoint must remain loopback-only")
    port = _require_positive_int(server["default_port"], "server.default_port")
    if port > 65535:
        raise MissionBindingError("server.default_port is invalid")
    _require_positive_int(server["max_model_len"], "server.max_model_len")
    _require_positive_int(server["max_num_seqs"], "server.max_num_seqs")
    _require_bounded_float(
        server["gpu_memory_utilization"],
        "server.gpu_memory_utilization",
        minimum=0.1,
        maximum=0.95,
    )
    _require_positive_int(
        server["startup_timeout_seconds"], "server.startup_timeout_seconds"
    )
    _require_positive_int(
        server["shutdown_timeout_seconds"], "server.shutdown_timeout_seconds"
    )
    if server["seed"] != 1337:
        raise MissionBindingError("server seed must remain deterministic")
    if server["enforce_eager"] is not True or server["trust_remote_code"] is not True:
        raise MissionBindingError("server execution flags do not match accepted runtime")

    submission = value["submission"]
    if (
        submission["path"] != "/v1/chat/completions"
        or submission["temperature"] != 0
        or submission["seed"] != 1337
        or submission["strict_json_schema"] is not True
        or submission["replay_runs"] != 2
        or submission["thinking_enabled"] is not False
    ):
        raise MissionBindingError("submission settings do not match accepted runtime")
    _require_positive_int(
        submission["request_timeout_seconds"], "submission.request_timeout_seconds"
    )
    _require_positive_int(
        submission["max_output_tokens"], "submission.max_output_tokens"
    )

    authority = value["authority"]
    if (
        not isinstance(authority, dict)
        or set(authority) != AUTHORITY_KEYS
        or any(item is not False for item in authority.values())
    ):
        raise MissionBindingError("runtime authority ceiling must deny every power")
    for field in _VALIDATED_RUNTIME_KEYS - {"mission_root"}:
        _require_sha256(value["validated_runtime"][field], f"validated_runtime.{field}")
    return value


def validate_runtime_files(
    contract: Mapping[str, Any], *, include_validated_mission: bool = True
) -> dict[str, str]:
    """Validate critical runtime bytes and the exact successful V3 executables."""
    model_root = Path(contract["model"]["path"])
    checks: list[tuple[str, Path, str]] = [
        (
            "model_config",
            model_root / "config.json",
            contract["model"]["config_sha256"],
        ),
        (
            "model_index",
            model_root / "model.safetensors.index.json",
            contract["model"]["index_sha256"],
        ),
        (
            "vllm_executable",
            Path(contract["engine"]["vllm_executable"]),
            contract["engine"]["vllm_executable_sha256"],
        ),
    ]
    if include_validated_mission:
        validated_root = Path(contract["validated_runtime"]["mission_root"])
        checks.extend(
            [
                (
                    "validated_binding",
                    validated_root / "binding.json",
                    contract["validated_runtime"]["binding_file_sha256"],
                ),
                (
                    "validated_launch_once",
                    validated_root / "launch_once.sh",
                    contract["validated_runtime"]["launch_once_sha256"],
                ),
                (
                    "validated_atomic_runner",
                    validated_root / "run_atomic_mission.sh",
                    contract["validated_runtime"]["run_atomic_mission_sha256"],
                ),
                (
                    "validated_client",
                    validated_root / "run_steward_client.py",
                    contract["validated_runtime"]["run_steward_client_sha256"],
                ),
                (
                    "validated_acceptance",
                    validated_root / "acceptance.json",
                    contract["validated_runtime"]["acceptance_file_sha256"],
                ),
                (
                    "validated_terminal",
                    validated_root / "runner_terminal.json",
                    contract["validated_runtime"]["runner_terminal_sha256"],
                ),
            ]
        )
    observed: dict[str, str] = {}
    for name, path, expected in checks:
        try:
            actual = file_sha256(path)
        except OSError as exc:
            raise MissionBindingError(f"runtime binding is missing: {name}") from exc
        if actual != expected:
            raise MissionBindingError(f"runtime binding drift: {name}")
        observed[name] = actual
    return observed


def build_vllm_command(
    contract: Mapping[str, Any], *, port: int | None = None
) -> list[str]:
    server = contract["server"]
    selected_port = server["default_port"] if port is None else port
    if (
        not isinstance(selected_port, int)
        or isinstance(selected_port, bool)
        or not 1024 <= selected_port <= 65535
    ):
        raise MissionBindingError("vLLM port is outside the allowed range")
    command = [
        contract["engine"]["vllm_executable"],
        "serve",
        contract["model"]["path"],
        "--host",
        server["host"],
        "--port",
        str(selected_port),
        "--served-model-name",
        server["served_model"],
        "--max-model-len",
        str(server["max_model_len"]),
        "--max-num-seqs",
        str(server["max_num_seqs"]),
        "--gpu-memory-utilization",
        str(server["gpu_memory_utilization"]),
    ]
    if server["enforce_eager"]:
        command.append("--enforce-eager")
    if server["trust_remote_code"]:
        command.append("--trust-remote-code")
    command.extend(["--seed", str(server["seed"])])
    return command


def process_start_token(pid: int, *, proc_root: Path = Path("/proc")) -> str:
    try:
        stat = (Path(proc_root) / str(pid) / "stat").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MissionConflictError("owned process identity is unavailable") from exc
    closing_parenthesis = stat.rfind(")")
    fields = stat[closing_parenthesis + 1 :].split() if closing_parenthesis >= 0 else []
    if len(fields) <= 19:
        raise MissionConflictError("owned process stat is malformed")
    return fields[19]


def _atomic_write_bytes(path: Path, body: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    body = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, body)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MissionConflictError(f"JSON artifact is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise MissionConflictError(f"JSON artifact is not an object: {path}")
    return value


def _endpoint_url(contract: Mapping[str, Any], port: int) -> str:
    return f"http://{contract['server']['host']}:{port}"


def endpoint_health(
    contract: Mapping[str, Any], *, port: int, timeout_seconds: float = 2.0
) -> dict[str, Any]:
    url = f"{_endpoint_url(contract, port)}/v1/models"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            document = json.loads(response.read())
    except Exception as exc:
        raise MissionConflictError("self-hosted endpoint health check failed") from exc
    models = document.get("data") if isinstance(document, dict) else None
    model_ids = {
        item.get("id")
        for item in models or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if contract["server"]["served_model"] not in model_ids:
        raise MissionConflictError("self-hosted endpoint served-model binding mismatch")
    return {"url": url, "served_model": contract["server"]["served_model"]}


def validate_request(
    contract: Mapping[str, Any], request_document: Mapping[str, Any]
) -> None:
    expected_keys = {
        "model",
        "messages",
        "temperature",
        "seed",
        "max_tokens",
        "response_format",
        "chat_template_kwargs",
    }
    _require_exact_keys(request_document, expected_keys, "request")
    submission = contract["submission"]
    if (
        request_document["model"] != contract["server"]["served_model"]
        or request_document["temperature"] != submission["temperature"]
        or request_document["seed"] != submission["seed"]
        or not isinstance(request_document["messages"], list)
        or not request_document["messages"]
        or not isinstance(request_document["max_tokens"], int)
        or not 1 <= request_document["max_tokens"] <= submission["max_output_tokens"]
    ):
        raise MissionBindingError("request does not match the runtime contract")
    response_format = request_document["response_format"]
    if (
        not isinstance(response_format, dict)
        or response_format.get("type") != "json_schema"
        or not isinstance(response_format.get("json_schema"), dict)
        or response_format["json_schema"].get("strict") is not True
    ):
        raise MissionBindingError("request must use strict JSON schema")
    template = request_document["chat_template_kwargs"]
    if (
        not isinstance(template, dict)
        or template != {"enable_thinking": submission["thinking_enabled"]}
    ):
        raise MissionBindingError("request thinking mode does not match contract")


def probe_idle_authorized_gpu(contract: Mapping[str, Any]) -> dict[str, Any]:
    names = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    normalized_names = [name.strip() for name in names if name.strip()]
    if normalized_names != [contract["pod"]["gpu"]]:
        raise MissionConflictError("authorized GPU identity mismatch")
    processes = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    active = [line.strip() for line in processes if line.strip()]
    if active:
        raise MissionConflictError("GPU compute process is already present")
    return {"gpu_name": normalized_names[0], "compute_process_count": 0}


def probe_comfyui_queue(
    *, url: str = "http://127.0.0.1:8188/queue", timeout_seconds: float = 3.0
) -> dict[str, Any]:
    """Reject live ComfyUI work; an unreachable service is recorded, not invented."""
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            document = json.loads(response.read())
    except Exception:
        return {"state": "unavailable", "url": url}
    if not isinstance(document, dict):
        raise MissionConflictError("ComfyUI queue response is malformed")
    running = document.get("queue_running")
    pending = document.get("queue_pending")
    if running or pending:
        raise MissionConflictError("ComfyUI queue is not empty")
    return {"state": "empty", "url": url}


class StewardRuntimeController:
    """Bind launcher, health, submit, recovery, and shutdown to one mission."""

    def __init__(
        self,
        *,
        contract_path: Path,
        mission_root: Path,
        database: Path,
        port: int | None = None,
    ):
        self.contract_path = Path(contract_path)
        self.contract = load_runtime_contract(self.contract_path)
        self.mission_root = Path(mission_root)
        self.ledger = StewardLedger(Path(database))
        self.port = self.contract["server"]["default_port"] if port is None else port
        build_vllm_command(self.contract, port=self.port)

    @property
    def binding_path(self) -> Path:
        return self.mission_root / "binding.json"

    @property
    def launch_receipt_path(self) -> Path:
        return self.mission_root / "runtime_launch_receipt.json"

    @property
    def terminal_receipt_path(self) -> Path:
        return self.mission_root / "terminal_receipt.json"

    @property
    def shutdown_receipt_path(self) -> Path:
        return self.mission_root / "runtime_shutdown_receipt.json"

    def _binding(self) -> dict[str, Any]:
        binding = read_json(self.binding_path)
        for name, expected in binding.get("input_sha256", {}).items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise MissionBindingError("binding input path escapes mission root")
            if file_sha256(self.mission_root / relative) != expected:
                raise MissionBindingError(f"binding input drift: {name}")
        return binding

    def admit(self) -> dict[str, Any]:
        return self.ledger.admit(self._binding())

    def launch(self) -> dict[str, Any]:
        validate_runtime_files(self.contract)
        admitted = self.admit()
        if admitted["outcome"] != "admitted":
            raise MissionConflictError(
                f"new launch refused for {admitted['outcome']}; reconcile instead"
            )
        probe_idle_authorized_gpu(self.contract)
        queue = probe_comfyui_queue()
        if self.launch_receipt_path.exists():
            raise MissionConflictError("runtime launch receipt already exists")
        command = build_vllm_command(self.contract, port=self.port)
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HOME": "/workspace/.cache/huggingface",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
                "CUDA_VISIBLE_DEVICES": "0",
            }
        )
        log_path = self.mission_root / "vllm_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_path.open("xb")
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    start_token = process_start_token(process.pid)
                    break
                except MissionConflictError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            binding = self._binding()
            self.ledger.mark_running(
                binding["session_id"],
                binding["job_id"],
                owner_pid=process.pid,
                owner_start_token=start_token,
            )
            receipt = {
                "schema_version": LAUNCH_RECEIPT_SCHEMA,
                "session_id": binding["session_id"],
                "job_id": binding["job_id"],
                "binding_sha256": binding["binding_sha256"],
                "runtime_contract_sha256": self.contract["contract_sha256"],
                "pid": process.pid,
                "process_group_id": process.pid,
                "owner_start_token": start_token,
                "port": self.port,
                "comfyui_queue_state": queue["state"],
                "command_sha256": canonical_sha256(command),
                "created_at": time.time(),
            }
            atomic_write_json(self.launch_receipt_path, receipt)
            deadline = (
                time.monotonic() + self.contract["server"]["startup_timeout_seconds"]
            )
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise MissionConflictError("owned vLLM process exited before ready")
                try:
                    endpoint_health(self.contract, port=self.port)
                    return receipt
                except MissionConflictError:
                    time.sleep(1.0)
            raise MissionConflictError("owned vLLM startup exceeded timeout")
        except BaseException:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            binding = self._binding()
            mission = self.ledger.get(binding["session_id"], binding["job_id"])
            if mission and mission["state"] in {"admitted", "running"}:
                self.ledger.fail(
                    binding["session_id"], binding["job_id"], "runtime_launch_failed"
                )
            raise
        finally:
            log_stream.close()

    def health(self) -> dict[str, Any]:
        receipt = read_json(self.launch_receipt_path)
        if not StewardLedger.owner_process_alive(
            int(receipt["pid"]), str(receipt["owner_start_token"])
        ):
            raise MissionConflictError("recorded runtime owner is not alive")
        result = endpoint_health(self.contract, port=int(receipt["port"]))
        result["pid"] = receipt["pid"]
        result["owner_start_token"] = receipt["owner_start_token"]
        return result

    def submit(self, request_path: Path) -> dict[str, Any]:
        binding = self._binding()
        mission = self.ledger.get(binding["session_id"], binding["job_id"])
        if mission is None or mission["state"] != "running":
            raise MissionConflictError("submission requires a running mission")
        self.health()
        request_path = Path(request_path)
        try:
            request_relative = request_path.resolve().relative_to(
                self.mission_root.resolve()
            )
        except ValueError as exc:
            raise MissionBindingError("request path escapes mission root") from exc
        if len(request_relative.parts) != 1:
            raise MissionBindingError("request path must be a mission-root file")
        request_document = read_json(request_path)
        validate_request(self.contract, request_document)
        request_digest = file_sha256(request_path)
        expected_request_digest = binding["input_sha256"].get(request_relative.name)
        if expected_request_digest != request_digest:
            raise MissionBindingError("request bytes are not in the immutable binding")
        self.ledger.record_request_intent(
            binding["session_id"],
            binding["job_id"],
            request_sha256=request_digest,
        )
        network_body = json.dumps(
            request_document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        proposals: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []
        for run_number in range(1, self.contract["submission"]["replay_runs"] + 1):
            request = urllib.request.Request(
                _endpoint_url(self.contract, self.port)
                + self.contract["submission"]["path"],
                data=network_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(
                request,
                timeout=self.contract["submission"]["request_timeout_seconds"],
            ) as response:
                raw = response.read()
            response_path = self.mission_root / f"response_run{run_number}.json"
            _atomic_write_bytes(
                response_path, raw + (b"" if raw.endswith(b"\n") else b"\n")
            )
            try:
                envelope = json.loads(raw)
                proposal = json.loads(envelope["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise MissionConflictError("model response is not strict proposal JSON") from exc
            if not isinstance(proposal, dict):
                raise MissionConflictError("model proposal must be an object")
            if proposal.get("authority_claimed") is not False:
                raise MissionConflictError("model proposal exceeded the authority ceiling")
            proposal_path = self.mission_root / f"proposal_run{run_number}.json"
            atomic_write_json(proposal_path, proposal)
            proposal_canonical = canonical_sha256(proposal)
            run = self.ledger.record_run(
                binding["session_id"],
                binding["job_id"],
                run_number=run_number,
                request_sha256=request_digest,
                response_sha256=file_sha256(response_path),
                proposal_sha256=file_sha256(proposal_path),
                proposal_canonical_sha256=proposal_canonical,
            )
            proposals.append(proposal)
            runs.append(run)
        proposal_digest = canonical_sha256(proposals[0])
        if any(canonical_sha256(proposal) != proposal_digest for proposal in proposals):
            raise MissionConflictError("deterministic proposal replay drift")
        proposal_path = self.mission_root / "proposal.json"
        atomic_write_json(proposal_path, proposals[0])
        terminal = {
            "schema_version": TERMINAL_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "payload_sha256": binding["payload_sha256"],
            "binding_sha256": binding["binding_sha256"],
            "state": "completed",
            "proposal_canonical_sha256": proposal_digest,
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
            "request_sha256": request_digest,
            "proposal_sha256": file_sha256(proposal_path),
            "proposal_canonical_sha256": proposal_digest,
            "run_count": len(runs),
            "terminal_outcome": reconciled["outcome"],
            "created_at": time.time(),
        }
        atomic_write_json(self.mission_root / "submission_receipt.json", receipt)
        return receipt

    def reconcile(self) -> dict[str, Any]:
        binding = self._binding()
        terminal = (
            read_json(self.terminal_receipt_path)
            if self.terminal_receipt_path.exists()
            else None
        )
        return self.ledger.reconcile_recorded_owner(
            binding["session_id"],
            binding["job_id"],
            terminal_receipt=terminal,
        )

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    def shutdown(self) -> dict[str, Any]:
        binding = self._binding()
        launch = read_json(self.launch_receipt_path)
        pid = int(launch["pid"])
        start_token = str(launch["owner_start_token"])
        owned_alive = StewardLedger.owner_process_alive(pid, start_token)
        terminated = False
        forced = False
        if owned_alive:
            if os.getpgid(pid) != int(launch["process_group_id"]):
                raise MissionConflictError("recorded process group identity mismatch")
            os.killpg(int(launch["process_group_id"]), signal.SIGTERM)
            deadline = (
                time.monotonic() + self.contract["server"]["shutdown_timeout_seconds"]
            )
            while time.monotonic() < deadline:
                if not StewardLedger.owner_process_alive(pid, start_token):
                    terminated = True
                    break
                time.sleep(0.1)
            if not terminated:
                os.killpg(int(launch["process_group_id"]), signal.SIGKILL)
                forced = True
                for _ in range(100):
                    if not StewardLedger.owner_process_alive(pid, start_token):
                        terminated = True
                        break
                    time.sleep(0.05)
        else:
            terminated = True
        if not terminated:
            raise MissionConflictError("owned runtime did not terminate")
        if self._port_open(self.contract["server"]["host"], int(launch["port"])):
            raise MissionConflictError("owned loopback port remains open after shutdown")
        if self.shutdown_receipt_path.exists():
            receipt = read_json(self.shutdown_receipt_path)
            if (
                receipt.get("schema_version") != SHUTDOWN_RECEIPT_SCHEMA
                or receipt.get("session_id") != binding["session_id"]
                or receipt.get("job_id") != binding["job_id"]
                or receipt.get("pid") != pid
                or receipt.get("owner_start_token") != start_token
                or receipt.get("process_group_id")
                != int(launch["process_group_id"])
                or receipt.get("owned_process_absent") is not True
                or receipt.get("loopback_port_closed") is not True
            ):
                raise MissionConflictError("existing shutdown receipt conflicts")
        else:
            receipt = {
                "schema_version": SHUTDOWN_RECEIPT_SCHEMA,
                "session_id": binding["session_id"],
                "job_id": binding["job_id"],
                "pid": pid,
                "owner_start_token": start_token,
                "process_group_id": int(launch["process_group_id"]),
                "owned_process_absent": True,
                "loopback_port_closed": True,
                "forced": forced,
                "created_at": time.time(),
            }
            atomic_write_json(self.shutdown_receipt_path, receipt)
        release_sha256 = file_sha256(self.shutdown_receipt_path)
        released = self.ledger.record_release(
            binding["session_id"],
            binding["job_id"],
            release_kind="direct_process_exit",
            release_sha256=release_sha256,
        )
        receipt["release_sha256"] = released["release_sha256"]
        receipt["handoff_ready"] = self.ledger.handoff_ready(
            binding["session_id"], binding["job_id"]
        )
        return receipt


__all__ = [
    "LAUNCH_RECEIPT_SCHEMA",
    "RUNTIME_CONTRACT_SCHEMA",
    "SHUTDOWN_RECEIPT_SCHEMA",
    "SUBMISSION_RECEIPT_SCHEMA",
    "StewardRuntimeController",
    "atomic_write_json",
    "build_vllm_command",
    "endpoint_health",
    "file_sha256",
    "load_runtime_contract",
    "probe_comfyui_queue",
    "probe_idle_authorized_gpu",
    "process_start_token",
    "read_json",
    "validate_request",
    "validate_runtime_files",
]
