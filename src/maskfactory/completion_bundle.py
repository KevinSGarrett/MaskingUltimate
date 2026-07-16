"""Fail-closed final evidence bundle for MaskFactory modernization completion.

The bundle is an index and verifier, never a substitute for the primary live
evidence it links.  Synthetic/pre-result receipts are deliberately ineligible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = PROJECT_ROOT / "qa/governance/completion/modernization_completion_v1.json"
POLICY_SHA256 = "5ec2908d110ab50224098bd1da59edbba085576f2ff87bfe61916a9acfd7af75"


class CompletionBundleError(ValueError):
    """A final completion claim is missing, stale, synthetic, or inconsistent."""


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha(value: Any, field: str) -> str:
    if not _is_sha256(value):
        raise CompletionBundleError(f"{field} is not a lowercase SHA-256")
    return str(value)


def _keys(value: Any, expected: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise CompletionBundleError(f"{field} structure is invalid")
    return value


def _seal(document: Mapping[str, Any], field: str) -> None:
    claimed = _sha(document.get("sha256"), f"{field}.sha256")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if claimed != canonical_sha256(payload):
        raise CompletionBundleError(f"{field} hash mismatch")


def _time(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CompletionBundleError(f"{field} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise CompletionBundleError(f"{field} timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _resolve(root: Path, relative: Any, field: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise CompletionBundleError(f"{field} must be a nonempty relative path")
    base = Path(root).resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise CompletionBundleError(f"{field} escaped its artifact root") from exc
    if not path.is_file():
        raise CompletionBundleError(f"{field} does not exist: {relative}")
    return path


def _validate_rule(rule: Any, field: str) -> None:
    value = _keys(rule, {"operator", "value"}, field)
    operator = value["operator"]
    if operator not in {"eq", "ge", "le"}:
        raise CompletionBundleError(f"{field} operator is invalid")
    if isinstance(value["value"], (dict, list)) or value["value"] is None:
        raise CompletionBundleError(f"{field} comparison value is invalid")


def validate_policy(
    policy: Mapping[str, Any],
    *,
    root: Path = PROJECT_ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    required = {
        "schema_version",
        "policy_id",
        "authority",
        "required_domains",
        "tracker_requirements",
        "governing_source_hashes",
        "sha256",
    }
    _keys(policy, required, "completion policy")
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_id"] != "modernization_completion_v1"
        or policy["authority"]
        != "pre_result_completion_index_only_no_primary_evidence_or_completion_authority"
    ):
        raise CompletionBundleError("completion policy identity is invalid")
    _seal(policy, "completion policy")
    if expected_sha256 is not None and policy["sha256"] != expected_sha256:
        raise CompletionBundleError("completion policy locked hash mismatch")
    domains = policy["required_domains"]
    if not isinstance(domains, Mapping) or not domains:
        raise CompletionBundleError("completion policy has no evidence domains")
    for domain, raw in domains.items():
        requirement = _keys(
            raw,
            {
                "verifier_id",
                "maximum_age_hours",
                "minimum_source_artifacts",
                "measurement_rules",
            },
            f"domain {domain}",
        )
        if (
            not isinstance(domain, str)
            or not domain
            or not isinstance(requirement["verifier_id"], str)
            or not requirement["verifier_id"]
            or isinstance(requirement["maximum_age_hours"], bool)
            or not isinstance(requirement["maximum_age_hours"], int)
            or requirement["maximum_age_hours"] < 1
            or isinstance(requirement["minimum_source_artifacts"], bool)
            or not isinstance(requirement["minimum_source_artifacts"], int)
            or requirement["minimum_source_artifacts"] < 1
            or not isinstance(requirement["measurement_rules"], Mapping)
            or not requirement["measurement_rules"]
        ):
            raise CompletionBundleError(f"domain {domain} requirement is invalid")
        for name, rule in requirement["measurement_rules"].items():
            if not isinstance(name, str) or not name:
                raise CompletionBundleError(f"domain {domain} measurement name is invalid")
            _validate_rule(rule, f"domain {domain}.{name}")
    tracker = _keys(
        policy["tracker_requirements"],
        {
            "excluded_item_ids",
            "allowed_terminal_statuses",
            "required_definition_of_done_ids",
            "required_goal_ids",
            "minimum_item_count",
        },
        "tracker requirements",
    )
    for key in (
        "excluded_item_ids",
        "allowed_terminal_statuses",
        "required_definition_of_done_ids",
        "required_goal_ids",
    ):
        values = tracker[key]
        if (
            not isinstance(values, list)
            or not values
            or len(set(values)) != len(values)
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise CompletionBundleError(f"tracker {key} is invalid")
    if tracker["excluded_item_ids"] != ["MF-P7-07.09"]:
        raise CompletionBundleError("only the completion-bundle item may be tracker-excluded")
    if set(tracker["allowed_terminal_statuses"]) != {"complete", "not_applicable"}:
        raise CompletionBundleError("tracker terminal statuses are unsafe")
    if set(tracker["required_definition_of_done_ids"]) != {f"D{index}" for index in range(1, 12)}:
        raise CompletionBundleError("completion policy must require D1 through D11")
    if set(tracker["required_goal_ids"]) != {f"G{index}" for index in range(1, 10)}:
        raise CompletionBundleError("completion policy must require G1 through G9")
    if (
        isinstance(tracker["minimum_item_count"], bool)
        or not isinstance(tracker["minimum_item_count"], int)
        or tracker["minimum_item_count"] < 755
    ):
        raise CompletionBundleError("completion tracker item floor is invalid")
    sources = policy["governing_source_hashes"]
    if not isinstance(sources, Mapping) or not sources:
        raise CompletionBundleError("completion policy governing sources are absent")
    project = Path(root).resolve()
    for relative, digest in sources.items():
        _sha(digest, f"governing source {relative}")
        path = _resolve(project, relative, f"governing source {relative}")
        if file_sha256(path) != digest:
            raise CompletionBundleError(f"governing source hash drift: {relative}")


def load_policy(path: Path = DEFAULT_POLICY, *, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompletionBundleError("completion policy must be a JSON object")
    validate_policy(value, root=root)
    return value


def _compare(actual: Any, operator: str, expected: Any, field: str) -> None:
    if type(actual) is not type(expected):  # bool must not compare as int
        raise CompletionBundleError(f"{field} type does not match its frozen rule")
    if operator == "eq":
        passed = actual == expected
    elif operator == "ge":
        passed = actual >= expected
    else:
        passed = actual <= expected
    if not passed:
        raise CompletionBundleError(
            f"{field} failed frozen rule: actual={actual!r} {operator} expected={expected!r}"
        )


def _tracker_summary(tracker: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, int]:
    requirements = policy["tracker_requirements"]
    items = tracker.get("items")
    if not isinstance(items, Mapping):
        raise CompletionBundleError("tracker items are absent")
    if len(items) < requirements["minimum_item_count"]:
        raise CompletionBundleError("tracker item count is below the frozen floor")
    excluded = set(requirements["excluded_item_ids"])
    allowed = set(requirements["allowed_terminal_statuses"])
    unresolved = sorted(
        item_id
        for item_id, row in items.items()
        if item_id not in excluded
        and isinstance(row, Mapping)
        and row.get("orphaned") is not True
        and row.get("status") not in allowed
    )
    malformed = sorted(
        item_id
        for item_id, row in items.items()
        if item_id not in excluded and not isinstance(row, Mapping)
    )
    if malformed:
        raise CompletionBundleError("tracker contains malformed items")
    if unresolved:
        preview = ", ".join(unresolved[:8])
        raise CompletionBundleError(f"tracker has unresolved items: {preview}")
    dod = tracker.get("dod")
    goals = tracker.get("goals")
    if not isinstance(dod, Mapping) or not isinstance(goals, Mapping):
        raise CompletionBundleError("tracker DoD or goals are absent")
    missing_dod = [
        key
        for key in requirements["required_definition_of_done_ids"]
        if not isinstance(dod.get(key), Mapping) or dod[key].get("status") != "met"
    ]
    missing_goals = [
        key
        for key in requirements["required_goal_ids"]
        if not isinstance(goals.get(key), Mapping) or goals[key].get("status") != "met"
    ]
    if missing_dod:
        raise CompletionBundleError(
            "Definitions of Done are not all met: " + ", ".join(missing_dod)
        )
    if missing_goals:
        raise CompletionBundleError("measured goals are not all met: " + ", ".join(missing_goals))
    return {
        "tracker_item_count": len(items),
        "unresolved_item_count_excluding_bundle": 0,
        "definitions_of_done_met": len(requirements["required_definition_of_done_ids"]),
        "goals_met": len(requirements["required_goal_ids"]),
    }


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    domain: str,
    requirement: Mapping[str, Any],
    artifact_root: Path,
    created_at: datetime,
) -> None:
    _keys(
        receipt,
        {
            "schema_version",
            "domain",
            "evidence_id",
            "observed_at",
            "evidence_class",
            "result",
            "verifier_id",
            "verifier_version",
            "source_artifacts",
            "measurements",
            "authority",
            "sha256",
        },
        f"receipt {domain}",
    )
    _seal(receipt, f"receipt {domain}")
    observed = _time(receipt["observed_at"], f"receipt {domain}.observed_at")
    age_hours = (created_at - observed).total_seconds() / 3600
    if age_hours < 0 or age_hours > requirement["maximum_age_hours"]:
        raise CompletionBundleError(f"receipt {domain} is future-dated or stale")
    if (
        receipt["schema_version"] != "1.0.0"
        or receipt["domain"] != domain
        or not isinstance(receipt["evidence_id"], str)
        or not receipt["evidence_id"]
        or receipt["evidence_class"] != "real_operation"
        or receipt["result"] != "pass"
        or receipt["verifier_id"] != requirement["verifier_id"]
        or not isinstance(receipt["verifier_version"], str)
        or not receipt["verifier_version"]
        or receipt["authority"] != "primary_domain_evidence"
    ):
        raise CompletionBundleError(f"receipt {domain} identity or authority is invalid")
    artifacts = receipt["source_artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) < requirement["minimum_source_artifacts"]:
        raise CompletionBundleError(f"receipt {domain} lacks source artifacts")
    paths: set[str] = set()
    for row in artifacts:
        artifact = _keys(row, {"path", "sha256"}, f"receipt {domain} artifact")
        if artifact["path"] in paths:
            raise CompletionBundleError(f"receipt {domain} repeats a source artifact")
        paths.add(str(artifact["path"]))
        path = _resolve(artifact_root, artifact["path"], f"receipt {domain} artifact")
        if file_sha256(path) != _sha(artifact["sha256"], f"receipt {domain} artifact hash"):
            raise CompletionBundleError(f"receipt {domain} source artifact hash drift")
    measurements = receipt["measurements"]
    rules = requirement["measurement_rules"]
    if not isinstance(measurements, Mapping) or set(measurements) != set(rules):
        raise CompletionBundleError(f"receipt {domain} measurement coverage is incomplete")
    for name, rule in rules.items():
        _compare(
            measurements[name],
            rule["operator"],
            rule["value"],
            f"receipt {domain}.{name}",
        )
    if domain == "test_suite" and measurements["tests_collected"] != measurements["tests_passed"]:
        raise CompletionBundleError("test suite collected and passed counts differ")


def _validate_input(
    document: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    artifact_root: Path,
    now: datetime | None,
) -> dict[str, int]:
    _keys(
        document,
        {
            "schema_version",
            "bundle_id",
            "created_at",
            "policy_sha256",
            "tracker",
            "evidence_receipts",
            "sha256",
        },
        "completion bundle input",
    )
    _seal(document, "completion bundle input")
    created = _time(document["created_at"], "completion bundle created_at")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if created > current or (current - created).total_seconds() > 3600:
        raise CompletionBundleError("completion bundle must be generated within the current hour")
    if (
        document["schema_version"] != "1.0.0"
        or not isinstance(document["bundle_id"], str)
        or not document["bundle_id"]
        or document["policy_sha256"] != policy["sha256"]
    ):
        raise CompletionBundleError("completion bundle input identity is invalid")
    tracker_ref = _keys(document["tracker"], {"path", "sha256"}, "tracker reference")
    tracker_path = _resolve(artifact_root, tracker_ref["path"], "tracker reference")
    if file_sha256(tracker_path) != _sha(tracker_ref["sha256"], "tracker reference hash"):
        raise CompletionBundleError("tracker reference hash drift")
    tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
    if not isinstance(tracker, dict):
        raise CompletionBundleError("tracker document must be an object")
    summary = _tracker_summary(tracker, policy)
    receipts = document["evidence_receipts"]
    domains = policy["required_domains"]
    if not isinstance(receipts, list) or len(receipts) != len(domains):
        raise CompletionBundleError("completion evidence domain coverage is incomplete")
    by_domain: dict[str, Mapping[str, Any]] = {}
    source_paths: set[str] = set()
    for raw in receipts:
        if not isinstance(raw, Mapping):
            raise CompletionBundleError("completion evidence receipt must be an object")
        domain = raw.get("domain")
        if domain not in domains or domain in by_domain:
            raise CompletionBundleError("completion evidence domain is invalid or duplicated")
        by_domain[str(domain)] = raw
        _validate_receipt(
            raw,
            domain=str(domain),
            requirement=domains[domain],
            artifact_root=artifact_root,
            created_at=created,
        )
        for artifact in raw["source_artifacts"]:
            path = str(artifact["path"])
            if path in source_paths:
                raise CompletionBundleError("one source artifact cannot satisfy multiple domains")
            source_paths.add(path)
    if set(by_domain) != set(domains):
        raise CompletionBundleError("completion evidence domain coverage is incomplete")
    tracker_receipt = by_domain.get("tracker_validation")
    if tracker_receipt is not None and tracker_receipt["measurements"] != summary:
        raise CompletionBundleError("tracker receipt does not match live tracker recomputation")
    return summary


def build_report(
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = PROJECT_ROOT,
    artifact_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_policy = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(current_policy, root=root)
    artifacts = Path(artifact_root or root)
    tracker = _validate_input(document, current_policy, artifact_root=artifacts, now=now)
    domains = sorted(current_policy["required_domains"])
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "bundle_id": document["bundle_id"],
        "created_at": document["created_at"],
        "policy_sha256": current_policy["sha256"],
        "input_sha256": document["sha256"],
        "tracker_sha256": document["tracker"]["sha256"],
        "required_domain_count": len(domains),
        "verified_domains": domains,
        **tracker,
        "result": "pass",
        "authority": "completion_index_verified_primary_evidence_remains_authoritative",
    }
    report["sha256"] = canonical_sha256(report)
    return report


def verify_report(
    report: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = PROJECT_ROOT,
    artifact_root: Path | None = None,
    now: datetime | None = None,
) -> None:
    expected = build_report(
        document,
        policy=policy,
        root=root,
        artifact_root=artifact_root,
        now=now,
    )
    if dict(report) != expected:
        raise CompletionBundleError("completion report does not recompute exactly")


__all__ = [
    "DEFAULT_POLICY",
    "POLICY_SHA256",
    "CompletionBundleError",
    "build_report",
    "canonical_sha256",
    "file_sha256",
    "load_policy",
    "validate_policy",
    "verify_report",
]
