"""Independent same-state replay proof for every semantic DAZ render output."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from ..passes import evaluate_render_pass_execution


class SameStateReplayError(ValueError):
    """A replay policy, run identity, execution, file set, or report is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_same_state_replay_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_same_state_replay_policy(document)
    return document


def validate_same_state_replay_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "eligible_profiles",
        "authority_fields",
        "independence",
        "semantic_replay",
        "scene_freeze",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise SameStateReplayError("replay_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise SameStateReplayError("replay_policy_identity_invalid", str(policy))
    if policy["eligible_profiles"] != [
        "engineering_minimal",
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise SameStateReplayError("replay_policy_profiles_invalid", str(policy))
    if policy["authority_fields"] != [
        "resolved_recipe_sha256",
        "asset_snapshot_sha256",
        "runtime_snapshot_sha256",
        "script_sha256",
        "mapping_set_sha256",
        "render_profile_sha256",
        "renderer_sha256",
        "driver_fingerprint_sha256",
    ]:
        raise SameStateReplayError("replay_policy_authorities_invalid", str(policy))
    if policy["independence"] != {
        "distinct_run_ids_required": True,
        "distinct_process_ids_required": True,
        "exact_authority_match_required": True,
    }:
        raise SameStateReplayError("replay_policy_independence_invalid", str(policy))
    if policy["semantic_replay"] != {
        "role_source": "render_pass_plan_semantic_true",
        "exact_sha256_required": True,
        "exact_byte_count_required": True,
        "actual_files_independently_hashed": True,
        "directory_outputs_use_canonical_tree_hash": True,
        "rgb_outside_semantic_exactness_claim": True,
    }:
        raise SameStateReplayError("replay_policy_semantics_invalid", str(policy))
    if policy["scene_freeze"] != {
        "both_executions_must_pass_render_pass_validator": True,
        "exact_scene_state_all_points_required": True,
        "exact_plan_lineage_required": True,
    }:
        raise SameStateReplayError("replay_policy_freeze_invalid", str(policy))
    if policy["publication"] != {"immutable": True, "idempotent": True}:
        raise SameStateReplayError("replay_policy_publication_invalid", str(policy))


def evaluate_same_state_replay(
    plan: Mapping[str, Any],
    original_execution: Mapping[str, Any],
    replay_execution: Mapping[str, Any],
    original_run: Mapping[str, Any],
    replay_run: Mapping[str, Any],
    *,
    original_paths: Mapping[str, Path],
    replay_paths: Mapping[str, Path],
    pass_policy: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently hash both output sets and prove exact semantic replay."""

    validate_same_state_replay_policy(policy)
    require_valid_document(plan, "daz_render_pass_plan")
    _verify_hashed_document(plan, "plan_id", "plan_sha256", "dcrp")
    if plan["profile"] not in policy["eligible_profiles"]:
        raise SameStateReplayError("replay_profile_ineligible", plan["profile"])
    expected_roles = [output["role"] for output in plan["outputs"]]
    semantic_roles = [output["role"] for output in plan["outputs"] if output["semantic"]]
    if not semantic_roles:
        raise SameStateReplayError("replay_semantic_roles_empty", plan["profile"])
    if set(original_paths) != set(expected_roles) or set(replay_paths) != set(expected_roles):
        raise SameStateReplayError(
            "replay_path_role_set_invalid",
            str((sorted(original_paths), sorted(replay_paths), expected_roles)),
        )
    original_run = _validate_run(original_run, policy)
    replay_run = _validate_run(replay_run, policy)
    findings: list[dict[str, str]] = []
    original_validation = evaluate_render_pass_execution(plan, original_execution, pass_policy)
    replay_validation = evaluate_render_pass_execution(plan, replay_execution, pass_policy)
    if not original_validation["summary"]["passed"]:
        _finding(
            findings,
            "REPLAY_ORIGINAL_EXECUTION_INVALID",
            "/original_execution",
            ",".join(original_validation["summary"]["failure_codes"]),
        )
    if not replay_validation["summary"]["passed"]:
        _finding(
            findings,
            "REPLAY_EXECUTION_INVALID",
            "/replay_execution",
            ",".join(replay_validation["summary"]["failure_codes"]),
        )
    runs_independent = True
    if original_run["run_id"] == replay_run["run_id"]:
        runs_independent = False
        _finding(findings, "REPLAY_RUN_ID_NOT_DISTINCT", "/runs/run_id", original_run["run_id"])
    if original_run["process_id"] == replay_run["process_id"]:
        runs_independent = False
        _finding(
            findings,
            "REPLAY_PROCESS_ID_NOT_DISTINCT",
            "/runs/process_id",
            str(original_run["process_id"]),
        )
    authorities_identical = True
    for field in policy["authority_fields"]:
        if original_run[field] != replay_run[field]:
            authorities_identical = False
            _finding(
                findings,
                "REPLAY_AUTHORITY_MISMATCH",
                f"/runs/{field}",
                f"{original_run[field]}:{replay_run[field]}",
            )
    original_by_role = {row["role"]: row for row in original_execution["passes"]}
    replay_by_role = {row["role"]: row for row in replay_execution["passes"]}
    semantic_records = []
    rgb_records = []
    for role in expected_roles:
        original_digest, original_bytes, original_kind = _path_digest(original_paths[role])
        replay_digest, replay_bytes, replay_kind = _path_digest(replay_paths[role])
        if original_kind != replay_kind:
            raise SameStateReplayError(
                "replay_output_kind_mismatch", f"{role}:{original_kind}:{replay_kind}"
            )
        original_record = original_by_role[role]
        replay_record = replay_by_role[role]
        record = {
            "role": role,
            "kind": original_kind,
            "original_sha256": original_digest,
            "replay_sha256": replay_digest,
            "original_bytes": original_bytes,
            "replay_bytes": replay_bytes,
            "hash_identical": original_digest == replay_digest,
            "bytes_identical": original_bytes == replay_bytes,
            "original_execution_hash_matches": original_record["file_sha256"] == original_digest,
            "replay_execution_hash_matches": replay_record["file_sha256"] == replay_digest,
            "original_execution_bytes_match": original_record["bytes"] == original_bytes,
            "replay_execution_bytes_match": replay_record["bytes"] == replay_bytes,
        }
        for run_name, field, code in (
            ("original", "original_execution_hash_matches", "REPLAY_ORIGINAL_HASH_UNTRUSTED"),
            ("replay", "replay_execution_hash_matches", "REPLAY_HASH_UNTRUSTED"),
            ("original", "original_execution_bytes_match", "REPLAY_ORIGINAL_BYTES_UNTRUSTED"),
            ("replay", "replay_execution_bytes_match", "REPLAY_BYTES_UNTRUSTED"),
        ):
            if not record[field]:
                _finding(findings, code, f"/{run_name}/{role}", field)
        if role in semantic_roles:
            if not record["hash_identical"]:
                _finding(
                    findings,
                    "REPLAY_SEMANTIC_HASH_DRIFT",
                    f"/semantic/{role}",
                    f"{original_digest}:{replay_digest}",
                )
            if not record["bytes_identical"]:
                _finding(
                    findings,
                    "REPLAY_SEMANTIC_BYTE_COUNT_DRIFT",
                    f"/semantic/{role}",
                    f"{original_bytes}:{replay_bytes}",
                )
            semantic_records.append(record)
        else:
            rgb_records.append(record)
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    semantic_exact = all(
        record["hash_identical"]
        and record["bytes_identical"]
        and record["original_execution_hash_matches"]
        and record["replay_execution_hash_matches"]
        and record["original_execution_bytes_match"]
        and record["replay_execution_bytes_match"]
        for record in semantic_records
    )
    scene_state_unchanged = (
        original_validation["summary"]["scene_state_unchanged"]
        and replay_validation["summary"]["scene_state_unchanged"]
        and original_validation["summary"]["passed"]
        and replay_validation["summary"]["passed"]
    )
    content = {
        "scene_id": plan["scene_id"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "scene_state_sha256": plan["scene_state_sha256"],
        "profile": plan["profile"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "original_run_id": original_run["run_id"],
        "replay_run_id": replay_run["run_id"],
        "original_process_id": original_run["process_id"],
        "replay_process_id": replay_run["process_id"],
        "authority_sha256s": {field: original_run[field] for field in policy["authority_fields"]},
        "original_execution_sha256": _canonical_sha(original_execution),
        "replay_execution_sha256": _canonical_sha(replay_execution),
        "semantic_roles": semantic_roles,
        "semantic_records": semantic_records,
        "rgb_records": rgb_records,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "semantic_role_count": len(semantic_roles),
            "semantic_hashes_byte_identical": semantic_exact,
            "actual_files_independently_hashed": True,
            "scene_state_unchanged": scene_state_unchanged,
            "runs_independent": runs_independent,
            "authorities_identical": authorities_identical,
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dssr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_same_state_replay_report")
    return report


def publish_same_state_replay_report(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(report, "daz_same_state_replay_report")
    _verify_hashed_document(report, "report_id", "report_sha256", "dssr")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise SameStateReplayError("replay_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _validate_run(run: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"run_id", "process_id", *policy["authority_fields"]}
    if (
        not isinstance(run, Mapping)
        or set(run) != expected
        or not isinstance(run["run_id"], str)
        or not run["run_id"]
        or isinstance(run["process_id"], bool)
        or not isinstance(run["process_id"], int)
        or run["process_id"] <= 0
        or any(not _sha256(run[field]) for field in policy["authority_fields"])
    ):
        raise SameStateReplayError("replay_run_manifest_invalid", str(run))
    return dict(run)


def _path_digest(path: Path) -> tuple[str, int, str]:
    path = Path(path)
    if path.is_file():
        payload = path.read_bytes()
        if not payload:
            raise SameStateReplayError("replay_output_empty", str(path))
        return hashlib.sha256(payload).hexdigest(), len(payload), "file"
    if path.is_dir():
        records = []
        total = 0
        for child in sorted(path.rglob("*")):
            if child.is_file():
                payload = child.read_bytes()
                if not payload:
                    raise SameStateReplayError("replay_output_empty", str(child))
                total += len(payload)
                records.append(
                    {
                        "path": child.relative_to(path).as_posix(),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "bytes": len(payload),
                    }
                )
        if not records:
            raise SameStateReplayError("replay_output_empty", str(path))
        return _canonical_sha(records), total, "directory_tree"
    raise SameStateReplayError("replay_output_missing", str(path))


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document.get(hash_field) != digest or document.get(id_field) != f"{prefix}_{digest[:24]}":
        raise SameStateReplayError("replay_document_hash_invalid", str(document.get(id_field)))


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SameStateReplayError("replay_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
