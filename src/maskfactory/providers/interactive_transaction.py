"""Serialized three-file promotion and exact rollback for interactive providers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..governance import validate_external_source_registry, validate_model_registry
from ..validation import validate_document
from .interactive_promotion import (
    INTERACTIVE_ROLE,
    InteractivePromotionCertificateError,
    verify_interactive_promotion_certificate,
)
from .selection import ProviderSelectionError, validate_provider_selection

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PIPELINE = ROOT / "configs" / "pipeline.yaml"
DEFAULT_EXTERNAL_REGISTRY = ROOT / "configs" / "external_sources.yaml"
DEFAULT_MODEL_REGISTRY = ROOT / "models" / "model_registry.json"
DEFAULT_HISTORY = ROOT / "runs" / "interactive_provider_history.jsonl"
DEFAULT_SNAPSHOT_ROOT = ROOT / "runs" / "interactive_provider_transactions"

InteractiveSmokeRunner = Callable[[Path, Path, Path, str, str], Mapping[str, Any]]


class InteractiveProviderTransactionError(RuntimeError):
    """An interactive-provider mutation cannot prove atomic governance."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: str | None = None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InteractiveProviderTransactionError("transaction timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise InteractiveProviderTransactionError("transaction timestamp lacks a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _load_yaml(path: Path, name: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InteractiveProviderTransactionError(f"{name} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise InteractiveProviderTransactionError(f"{name} must be a mapping")
    return value


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InteractiveProviderTransactionError(f"{name} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise InteractiveProviderTransactionError(f"{name} must be an object")
    return value


def _yaml_bytes(value: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True).encode("utf-8")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_bytes(path: Path, value: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _transaction_lock(pipeline_path: Path, *, timeout_seconds: float = 10.0):
    lock = Path(f"{pipeline_path}.interactive-promotion.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > 300
            except FileNotFoundError:
                continue
            if stale:
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise InteractiveProviderTransactionError(
                    "timed out waiting for the interactive promotion lock"
                )
            time.sleep(0.05)
    try:
        os.write(descriptor, f"pid={os.getpid()} started={time.time()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def _validate_model_document(value: dict[str, Any]) -> None:
    issues = validate_document(value, "model_registry")
    if issues:
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in issues
        )
        raise InteractiveProviderTransactionError(f"model registry schema is invalid: {detail}")
    try:
        validate_model_registry(value)
    except ValueError as exc:
        raise InteractiveProviderTransactionError(
            f"model registry governance failed: {exc}"
        ) from exc


def _validate_proposed(
    pipeline: dict[str, Any],
    external: dict[str, Any],
    models: dict[str, Any],
    *,
    directory: Path,
) -> tuple[bytes, bytes, bytes]:
    try:
        validate_external_source_registry(external)
    except ValueError as exc:
        raise InteractiveProviderTransactionError(
            f"external registry governance failed: {exc}"
        ) from exc
    _validate_model_document(models)
    pipeline_bytes = _yaml_bytes(pipeline)
    external_bytes = _yaml_bytes(external)
    model_bytes = _json_bytes(models)
    paths = (
        directory / "pipeline.yaml",
        directory / "external_sources.yaml",
        directory / "model_registry.json",
    )
    for path, value in zip(paths, (pipeline_bytes, external_bytes, model_bytes), strict=True):
        path.write_bytes(value)
    try:
        validate_provider_selection(
            pipeline,
            external_registry_path=paths[1],
            model_registry_path=paths[2],
        )
    except (ProviderSelectionError, ValueError) as exc:
        raise InteractiveProviderTransactionError(
            f"proposed provider selection is invalid: {exc}"
        ) from exc
    return pipeline_bytes, external_bytes, model_bytes


def _validate_smoke(
    smoke: Mapping[str, Any],
    *,
    action: str,
    provider_key: str,
    checkpoint_sha256: str,
    runtime_sha256: str | None = None,
) -> dict[str, Any]:
    required = {
        "result",
        "action",
        "role",
        "provider_key",
        "checkpoint_sha256",
        "runtime_sha256",
        "output_sha256",
    }
    value = dict(smoke)
    if (
        set(value) != required
        or value.get("result") != "pass"
        or value.get("action") != action
        or value.get("role") != INTERACTIVE_ROLE
        or value.get("provider_key") != provider_key
        or value.get("checkpoint_sha256") != checkpoint_sha256
        or runtime_sha256 is not None
        and value.get("runtime_sha256") != runtime_sha256
    ):
        raise InteractiveProviderTransactionError("interactive serving smoke is invalid")
    for field in ("checkpoint_sha256", "runtime_sha256", "output_sha256"):
        item = value.get(field)
        if (
            not isinstance(item, str)
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item)
        ):
            raise InteractiveProviderTransactionError(f"interactive smoke {field} is invalid")
    return value


def load_smoke_evidence_runner(evidence_path: Path) -> InteractiveSmokeRunner:
    """Load an exact-input live-smoke receipt for one CLI transaction attempt."""
    evidence = _load_json(Path(evidence_path), "interactive smoke evidence")
    required = {"schema_version", "inputs", "smoke", "sha256"}
    if set(evidence) != required or evidence.get("schema_version") != "1.0.0":
        raise InteractiveProviderTransactionError("interactive smoke evidence is incomplete")
    claimed = evidence.get("sha256")
    payload = {key: value for key, value in evidence.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise InteractiveProviderTransactionError("interactive smoke evidence hash mismatch")
    inputs = evidence.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "pipeline_sha256",
        "external_registry_sha256",
        "model_registry_sha256",
    }:
        raise InteractiveProviderTransactionError("interactive smoke input binding is invalid")
    for value in inputs.values():
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise InteractiveProviderTransactionError("interactive smoke input hash is invalid")
    smoke = evidence.get("smoke")
    if not isinstance(smoke, Mapping):
        raise InteractiveProviderTransactionError("interactive smoke result is missing")

    def runner(
        pipeline_path: Path,
        external_registry_path: Path,
        model_registry_path: Path,
        provider_key: str,
        action: str,
    ) -> Mapping[str, Any]:
        observed = {
            "pipeline_sha256": _file_sha256(pipeline_path),
            "external_registry_sha256": _file_sha256(external_registry_path),
            "model_registry_sha256": _file_sha256(model_registry_path),
        }
        if observed != dict(inputs):
            raise InteractiveProviderTransactionError(
                "interactive smoke evidence targets different authoritative inputs"
            )
        if smoke.get("provider_key") != provider_key or smoke.get("action") != action:
            raise InteractiveProviderTransactionError(
                "interactive smoke evidence targets a different transaction action"
            )
        return dict(smoke)

    return runner


def build_smoke_evidence(
    *,
    pipeline_path: Path,
    external_registry_path: Path,
    model_registry_path: Path,
    smoke: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one already-executed live smoke against its exact proposed inputs."""
    value = _validate_smoke(
        smoke,
        action=str(smoke.get("action")),
        provider_key=str(smoke.get("provider_key")),
        checkpoint_sha256=str(smoke.get("checkpoint_sha256")),
    )
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "inputs": {
            "pipeline_sha256": _file_sha256(pipeline_path),
            "external_registry_sha256": _file_sha256(external_registry_path),
            "model_registry_sha256": _file_sha256(model_registry_path),
        },
        "smoke": value,
    }
    document["sha256"] = _canonical_sha256(document)
    return document


def _write_snapshots(
    snapshot_root: Path,
    transaction_id: str,
    before: Mapping[str, bytes],
    after: Mapping[str, bytes],
) -> tuple[Path, dict[str, Any]]:
    root = Path(snapshot_root) / transaction_id
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InteractiveProviderTransactionError("transaction snapshot already exists") from exc
    files: dict[str, Any] = {}
    for key in ("pipeline", "external_registry", "model_registry"):
        before_path = root / f"before.{key}"
        after_path = root / f"after.{key}"
        before_path.write_bytes(before[key])
        after_path.write_bytes(after[key])
        files[key] = {
            "before_sha256": _bytes_sha256(before[key]),
            "after_sha256": _bytes_sha256(after[key]),
        }
    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "transaction_id": transaction_id,
        "files": files,
    }
    manifest["sha256"] = _canonical_sha256(manifest)
    (root / "manifest.json").write_bytes(_json_bytes(manifest))
    return root, manifest


def _verify_snapshots(
    snapshot_root: Path, record: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    root = Path(snapshot_root) / str(record["transaction_id"])
    manifest = _load_json(root / "manifest.json", "interactive snapshot manifest")
    if manifest.get("sha256") != record.get("snapshot_manifest_sha256"):
        raise InteractiveProviderTransactionError("interactive snapshot manifest binding failed")
    if manifest.get("sha256") != _canonical_sha256(
        {key: value for key, value in manifest.items() if key != "sha256"}
    ) or manifest.get("files") != record.get("files"):
        raise InteractiveProviderTransactionError("interactive snapshot manifest is invalid")
    before: dict[str, bytes] = {}
    after: dict[str, bytes] = {}
    for key, state in record["files"].items():
        before[key] = (root / f"before.{key}").read_bytes()
        after[key] = (root / f"after.{key}").read_bytes()
        if (
            _bytes_sha256(before[key]) != state["before_sha256"]
            or _bytes_sha256(after[key]) != state["after_sha256"]
        ):
            raise InteractiveProviderTransactionError("interactive transaction snapshot drifted")
    return before, after


def _validate_record(record: dict[str, Any], schema: str) -> None:
    issues = validate_document(record, schema)
    if issues:
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in issues
        )
        raise InteractiveProviderTransactionError(
            f"interactive transaction schema failed: {detail}"
        )
    payload = {key: value for key, value in record.items() if key != "sha256"}
    if record.get("sha256") != _canonical_sha256(payload):
        raise InteractiveProviderTransactionError("interactive transaction record hash mismatch")


def _append_history(path: Path, record: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _publish_or_restore(
    paths: Mapping[str, Path],
    after: Mapping[str, bytes],
    before: Mapping[str, bytes],
    *,
    publish_order: tuple[str, str, str],
    restore_order: tuple[str, str, str],
) -> None:
    try:
        for key in publish_order:
            _atomic_bytes(paths[key], after[key])
            if _file_sha256(paths[key]) != _bytes_sha256(after[key]):
                raise InteractiveProviderTransactionError(f"published {key} hash mismatch")
    except Exception as exc:
        restore_errors = []
        for key in restore_order:
            try:
                _atomic_bytes(paths[key], before[key])
            except Exception as restore_exc:  # pragma: no cover - catastrophic filesystem failure
                restore_errors.append(f"{key}={restore_exc}")
        if restore_errors:
            raise InteractiveProviderTransactionError(
                f"interactive publication failed and restoration was incomplete: {exc}; "
                + "; ".join(restore_errors)
            ) from exc
        raise InteractiveProviderTransactionError(
            f"interactive publication failed; exact inputs restored: {exc}"
        ) from exc


def _current_documents(
    pipeline_path: Path, external_registry_path: Path, model_registry_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, bytes]]:
    pipeline = _load_yaml(pipeline_path, "pipeline")
    external = _load_yaml(external_registry_path, "external registry")
    models = _load_json(model_registry_path, "model registry")
    try:
        validate_provider_selection(
            pipeline,
            external_registry_path=external_registry_path,
            model_registry_path=model_registry_path,
        )
    except (ProviderSelectionError, ValueError) as exc:
        raise InteractiveProviderTransactionError(
            f"current provider selection is invalid: {exc}"
        ) from exc
    return (
        pipeline,
        external,
        models,
        {
            "pipeline": Path(pipeline_path).read_bytes(),
            "external_registry": Path(external_registry_path).read_bytes(),
            "model_registry": Path(model_registry_path).read_bytes(),
        },
    )


def promote_interactive_provider(
    candidate_key: str,
    *,
    promotion_certificate: Mapping[str, Any],
    matrix_bundle_root: Path,
    candidate_checkpoint_path: Path,
    candidate_runtime_lock_path: Path,
    smoke_runner: InteractiveSmokeRunner,
    pipeline_path: Path = DEFAULT_PIPELINE,
    external_registry_path: Path = DEFAULT_EXTERNAL_REGISTRY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    history_path: Path = DEFAULT_HISTORY,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
    project_root: Path = ROOT,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    """Smoke, publish, and seal one benchmarked interactive-provider promotion."""
    if not callable(smoke_runner):
        raise InteractiveProviderTransactionError("interactive promotion requires a smoke runner")
    paths = {
        "pipeline": Path(pipeline_path),
        "external_registry": Path(external_registry_path),
        "model_registry": Path(model_registry_path),
    }
    with _transaction_lock(paths["pipeline"]):
        pipeline, external, models, before_bytes = _current_documents(
            paths["pipeline"], paths["external_registry"], paths["model_registry"]
        )
        before_pipeline = copy.deepcopy(pipeline)
        selection = validate_provider_selection(
            pipeline,
            external_registry_path=paths["external_registry"],
            model_registry_path=paths["model_registry"],
        )
        incumbent_key = selection["active"].get(INTERACTIVE_ROLE)
        if not isinstance(incumbent_key, str) or incumbent_key == candidate_key:
            raise InteractiveProviderTransactionError(
                "interactive incumbent/candidate scope is invalid"
            )
        role = pipeline["provider_roles"][INTERACTIVE_ROLE]
        if candidate_key not in role.get("challengers", ()):
            raise InteractiveProviderTransactionError(
                "candidate is not a governed shadow challenger"
            )
        candidate_binding = pipeline["provider_catalog"].get(candidate_key)
        incumbent_binding = pipeline["provider_catalog"].get(incumbent_key)
        if (
            not isinstance(candidate_binding, Mapping)
            or candidate_binding.get("registry") != "external_sources"
            or not isinstance(incumbent_binding, Mapping)
            or incumbent_binding.get("registry") != "model_registry"
        ):
            raise InteractiveProviderTransactionError(
                "interactive transaction requires external candidate and model-registry incumbent"
            )
        candidate_entry = external["providers"].get(candidate_binding["key"])
        model_entries = {str(row.get("key")): row for row in models["models"]}
        incumbent_entry = model_entries.get(str(incumbent_binding["key"]))
        if not isinstance(candidate_entry, dict) or not isinstance(incumbent_entry, dict):
            raise InteractiveProviderTransactionError("interactive authority entry is missing")
        if candidate_entry.get("lifecycle_state") != "benchmarked":
            raise InteractiveProviderTransactionError("interactive candidate must be benchmarked")
        if incumbent_entry.get("lifecycle_state") != "promoted":
            raise InteractiveProviderTransactionError("interactive incumbent must be promoted")
        benchmark = candidate_entry.get("benchmark_certificate")
        if not isinstance(benchmark, Mapping):
            raise InteractiveProviderTransactionError(
                "interactive candidate benchmark certificate is missing"
            )
        checkpoint = candidate_entry.get("checkpoint")
        if not isinstance(checkpoint, Mapping):
            raise InteractiveProviderTransactionError("interactive candidate checkpoint is missing")
        candidate_checkpoint_sha = _file_sha256(Path(candidate_checkpoint_path))
        if candidate_checkpoint_sha != checkpoint.get("sha256"):
            raise InteractiveProviderTransactionError(
                "candidate checkpoint hash differs from registry"
            )
        runtime_lock_sha = _file_sha256(Path(candidate_runtime_lock_path))
        runtime_declared = candidate_entry.get("runtime_lock")
        if (
            not isinstance(runtime_declared, str)
            or (Path(project_root) / runtime_declared).resolve()
            != Path(candidate_runtime_lock_path).resolve()
        ):
            raise InteractiveProviderTransactionError(
                "candidate runtime lock path differs from registry"
            )
        incumbent_checkpoint = (Path(project_root) / str(incumbent_entry["file"])).resolve()
        incumbent_checkpoint_sha = _file_sha256(incumbent_checkpoint)
        if incumbent_checkpoint_sha != incumbent_entry.get("sha256"):
            raise InteractiveProviderTransactionError(
                "incumbent checkpoint hash differs from registry"
            )
        incumbent_runtime = incumbent_entry.get("runtime")
        if not isinstance(incumbent_runtime, str) or not incumbent_runtime:
            raise InteractiveProviderTransactionError("incumbent runtime identity is missing")
        incumbent_runtime_sha = hashlib.sha256(incumbent_runtime.encode("utf-8")).hexdigest()
        try:
            verify_interactive_promotion_certificate(
                promotion_certificate,
                matrix_bundle_root=matrix_bundle_root,
                benchmark_certificate=benchmark,
                rollback_evidence=promotion_certificate["rollback_evidence"],
                candidate_key=candidate_key,
                incumbent_key=incumbent_key,
                candidate_artifact_key=str(promotion_certificate["candidate_artifact_key"]),
                incumbent_artifact_key=str(promotion_certificate["incumbent_artifact_key"]),
                candidate_checkpoint_sha256=candidate_checkpoint_sha,
                incumbent_checkpoint_sha256=incumbent_checkpoint_sha,
                candidate_runtime_lock_sha256=runtime_lock_sha,
            )
        except (InteractivePromotionCertificateError, KeyError) as exc:
            raise InteractiveProviderTransactionError(
                f"interactive promotion certificate failed: {exc}"
            ) from exc
        if promotion_certificate["rollback_evidence"]["pipeline_before_sha256"] != _bytes_sha256(
            before_bytes["pipeline"]
        ):
            raise InteractiveProviderTransactionError(
                "live pipeline differs from the rollback-rehearsed baseline"
            )

        proposed_pipeline = copy.deepcopy(before_pipeline)
        proposed_external = copy.deepcopy(external)
        proposed_models = copy.deepcopy(models)
        proposed_role = proposed_pipeline["provider_roles"][INTERACTIVE_ROLE]
        proposed_role["active"] = candidate_key
        proposed_role["challengers"] = [
            incumbent_key,
            *[
                key
                for key in proposed_role["challengers"]
                if key not in {candidate_key, incumbent_key}
            ],
        ]
        proposed_role["rollback"] = incumbent_key
        proposed_pipeline["stages"]["S07"]["primary_model"] = candidate_key
        proposed_external["providers"][candidate_binding["key"]]["lifecycle_state"] = "promoted"
        proposed_model_entries = {str(row.get("key")): row for row in proposed_models["models"]}
        proposed_model_entries[str(incumbent_binding["key"])]["lifecycle_state"] = "benchmarked"
        transaction_id = uuid.uuid4().hex
        staging = Path(snapshot_root) / f".{transaction_id}.staging"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            proposed_values = _validate_proposed(
                proposed_pipeline, proposed_external, proposed_models, directory=staging
            )
            after_bytes = dict(
                zip(
                    ("pipeline", "external_registry", "model_registry"),
                    proposed_values,
                    strict=True,
                )
            )
            if (
                _bytes_sha256(after_bytes["pipeline"])
                != promotion_certificate["rollback_evidence"]["pipeline_promoted_sha256"]
            ):
                raise InteractiveProviderTransactionError(
                    "proposed pipeline differs from the rollback-rehearsed promotion"
                )
            snapshot_dir, manifest = _write_snapshots(
                snapshot_root, transaction_id, before_bytes, after_bytes
            )
        finally:
            for child in staging.glob("*"):
                child.unlink(missing_ok=True)
            staging.rmdir()
        smoke = _validate_smoke(
            smoke_runner(
                snapshot_dir / "after.pipeline",
                snapshot_dir / "after.external_registry",
                snapshot_dir / "after.model_registry",
                candidate_key,
                "promote",
            ),
            action="promote",
            provider_key=candidate_key,
            checkpoint_sha256=candidate_checkpoint_sha,
            runtime_sha256=runtime_lock_sha,
        )
        record: dict[str, Any] = {
            "schema_version": "1.0.0",
            "action": "promote",
            "transaction_kind": "interactive_provider",
            "transaction_id": transaction_id,
            "recorded_at": _timestamp(promoted_at),
            "role": INTERACTIVE_ROLE,
            "candidate_key": candidate_key,
            "candidate_previous_lifecycle_state": "benchmarked",
            "incumbent_key": incumbent_key,
            "incumbent_previous_lifecycle_state": "promoted",
            "oom_fallback_key": selection["fallbacks"][INTERACTIVE_ROLE]["oom_fallback"],
            "promotion_certificate_id": promotion_certificate["certificate_id"],
            "promotion_certificate_sha256": promotion_certificate["certificate_sha256"],
            "matrix_certificate_sha256": promotion_certificate["matrix_certificate_sha256"],
            "benchmark_certificate_sha256": benchmark["sha256"],
            "candidate_checkpoint_sha256": candidate_checkpoint_sha,
            "incumbent_checkpoint_sha256": incumbent_checkpoint_sha,
            "candidate_runtime_lock_sha256": runtime_lock_sha,
            "incumbent_runtime_sha256": incumbent_runtime_sha,
            "files": manifest["files"],
            "snapshot_manifest_sha256": manifest["sha256"],
            "serving_smoke": smoke,
        }
        record["sha256"] = _canonical_sha256(record)
        _validate_record(record, "interactive_provider_transaction")
        _publish_or_restore(
            paths,
            after_bytes,
            before_bytes,
            publish_order=("external_registry", "pipeline", "model_registry"),
            restore_order=("model_registry", "pipeline", "external_registry"),
        )
        try:
            _append_history(history_path, record)
        except Exception as exc:
            _publish_or_restore(
                paths,
                before_bytes,
                after_bytes,
                publish_order=("model_registry", "pipeline", "external_registry"),
                restore_order=("external_registry", "pipeline", "model_registry"),
            )
            raise InteractiveProviderTransactionError(
                f"interactive history failed; exact inputs restored: {exc}"
            ) from exc
        return record


def _history_records(path: Path) -> list[dict[str, Any]]:
    records = []
    if not Path(path).is_file():
        return records
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InteractiveProviderTransactionError(
                f"invalid interactive history row {number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise InteractiveProviderTransactionError(
                f"interactive history row {number} is not an object"
            )
        records.append(value)
    return records


def load_interactive_promotion(
    transaction_id: str, *, history_path: Path = DEFAULT_HISTORY
) -> dict[str, Any]:
    """Load one unused, hash-valid interactive promotion record."""
    records = _history_records(history_path)
    matches = [
        row
        for row in records
        if row.get("action") == "promote"
        and row.get("transaction_kind") == "interactive_provider"
        and row.get("transaction_id") == transaction_id
    ]
    if len(matches) != 1:
        raise InteractiveProviderTransactionError(
            "interactive promotion transaction id is missing or ambiguous"
        )
    record = matches[0]
    _validate_record(record, "interactive_provider_transaction")
    rollbacks = [
        row
        for row in records
        if row.get("action") == "rollback"
        and row.get("transaction_kind") == "interactive_provider"
        and row.get("promotion_transaction_id") == transaction_id
    ]
    for rollback in rollbacks:
        _validate_record(rollback, "interactive_provider_rollback")
        if rollback.get("promotion_transaction_sha256") != record["sha256"]:
            raise InteractiveProviderTransactionError(
                "interactive rollback promotion binding is invalid"
            )
    if rollbacks:
        raise InteractiveProviderTransactionError(
            "interactive promotion transaction was already rolled back"
        )
    return record


def rollback_interactive_provider(
    transaction_id: str,
    *,
    smoke_runner: InteractiveSmokeRunner,
    pipeline_path: Path = DEFAULT_PIPELINE,
    external_registry_path: Path = DEFAULT_EXTERNAL_REGISTRY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    history_path: Path = DEFAULT_HISTORY,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
    rolled_back_at: str | None = None,
) -> dict[str, Any]:
    """Restore all three exact pre-promotion files by immutable transaction id."""
    paths = {
        "pipeline": Path(pipeline_path),
        "external_registry": Path(external_registry_path),
        "model_registry": Path(model_registry_path),
    }
    with _transaction_lock(paths["pipeline"]):
        record = load_interactive_promotion(transaction_id, history_path=history_path)
        before_bytes, after_bytes = _verify_snapshots(snapshot_root, record)
        for key, path in paths.items():
            if _file_sha256(path) != record["files"][key]["after_sha256"]:
                raise InteractiveProviderTransactionError(
                    "cannot rollback: an authoritative file changed after promotion"
                )
        snapshot_dir = Path(snapshot_root) / transaction_id
        smoke = _validate_smoke(
            smoke_runner(
                snapshot_dir / "before.pipeline",
                snapshot_dir / "before.external_registry",
                snapshot_dir / "before.model_registry",
                record["incumbent_key"],
                "rollback",
            ),
            action="rollback",
            provider_key=record["incumbent_key"],
            checkpoint_sha256=record["incumbent_checkpoint_sha256"],
            runtime_sha256=record["incumbent_runtime_sha256"],
        )
        rollback_record: dict[str, Any] = {
            "schema_version": "1.0.0",
            "action": "rollback",
            "transaction_kind": "interactive_provider",
            "transaction_id": uuid.uuid4().hex,
            "promotion_transaction_id": transaction_id,
            "promotion_transaction_sha256": record["sha256"],
            "recorded_at": _timestamp(rolled_back_at),
            "role": INTERACTIVE_ROLE,
            "candidate_key": record["candidate_key"],
            "incumbent_key": record["incumbent_key"],
            "promotion_certificate_sha256": record["promotion_certificate_sha256"],
            "files": {
                key: {
                    "before_sha256": state["after_sha256"],
                    "after_sha256": state["before_sha256"],
                }
                for key, state in record["files"].items()
            },
            "snapshot_manifest_sha256": record["snapshot_manifest_sha256"],
            "serving_smoke": smoke,
        }
        rollback_record["sha256"] = _canonical_sha256(rollback_record)
        _validate_record(rollback_record, "interactive_provider_rollback")
        _publish_or_restore(
            paths,
            before_bytes,
            after_bytes,
            publish_order=("model_registry", "pipeline", "external_registry"),
            restore_order=("external_registry", "pipeline", "model_registry"),
        )
        try:
            _append_history(history_path, rollback_record)
        except Exception as exc:
            _publish_or_restore(
                paths,
                after_bytes,
                before_bytes,
                publish_order=("external_registry", "pipeline", "model_registry"),
                restore_order=("model_registry", "pipeline", "external_registry"),
            )
            raise InteractiveProviderTransactionError(
                f"interactive rollback history failed; promoted files restored: {exc}"
            ) from exc
        return rollback_record


__all__ = [
    "DEFAULT_EXTERNAL_REGISTRY",
    "DEFAULT_HISTORY",
    "DEFAULT_MODEL_REGISTRY",
    "DEFAULT_PIPELINE",
    "DEFAULT_SNAPSHOT_ROOT",
    "InteractiveProviderTransactionError",
    "InteractiveSmokeRunner",
    "build_smoke_evidence",
    "load_interactive_promotion",
    "load_smoke_evidence_runner",
    "promote_interactive_provider",
    "rollback_interactive_provider",
]
