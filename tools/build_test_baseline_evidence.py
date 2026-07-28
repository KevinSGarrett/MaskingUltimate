#!/usr/bin/env python3
"""Build fail-closed MF-P6-20.03 test and prerequisite evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


class TestBaselineEvidenceError(RuntimeError):
    """Raised when the test baseline cannot support an acceptance claim."""


def canonical_sha256(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_contracts(path: Path, repo_root: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "maskfactory.test_external_prerequisite_contracts.v1":
        raise TestBaselineEvidenceError("unsupported prerequisite contract schema")
    if canonical_sha256(document) != document.get("self_sha256"):
        raise TestBaselineEvidenceError("prerequisite contract self hash mismatch")

    contracts = document.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise TestBaselineEvidenceError("prerequisite contracts are missing")
    reasons = [row.get("skip_reason") for row in contracts]
    ids = [row.get("contract_id") for row in contracts]
    if any(not isinstance(value, str) or not value for value in reasons + ids):
        raise TestBaselineEvidenceError("contract id/reason must be non-empty strings")
    if len(reasons) != len(set(reasons)) or len(ids) != len(set(ids)):
        raise TestBaselineEvidenceError("contract ids and skip reasons must be unique")

    pinned = document.get("byte_pinned_formatter_exclusions")
    if not isinstance(pinned, list) or not pinned:
        raise TestBaselineEvidenceError("byte-pinned formatter exclusions are missing")
    for row in pinned:
        relative = row.get("path")
        expected = row.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise TestBaselineEvidenceError("malformed byte-pinned exclusion")
        target = (repo_root / relative).resolve(strict=True)
        try:
            target.relative_to(repo_root)
        except ValueError as exc:
            raise TestBaselineEvidenceError(f"pinned path escapes repository: {relative}") from exc
        if sha256_file(target) != expected:
            raise TestBaselineEvidenceError(f"byte-pinned exclusion drift: {relative}")
    return document


def parse_junit(
    path: Path, contract_document: dict[str, Any]
) -> tuple[dict[str, int], list[dict[str, Any]], Counter[str]]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    rows: list[dict[str, Any]] = []
    observed: Counter[str] = Counter()
    known = {row["skip_reason"]: row for row in contract_document["contracts"]}
    seen: set[str] = set()

    for case in cases:
        nodeid = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        if nodeid in seen:
            raise TestBaselineEvidenceError(f"duplicate JUnit node id: {nodeid}")
        seen.add(nodeid)
        failures = case.findall("failure")
        errors = case.findall("error")
        skips = case.findall("skipped")
        outcome_nodes = len(failures) + len(errors) + len(skips)
        if outcome_nodes > 1:
            raise TestBaselineEvidenceError(f"ambiguous JUnit outcome: {nodeid}")
        row: dict[str, Any] = {
            "nodeid": nodeid,
            "duration_seconds": case.attrib.get("time"),
        }
        if failures:
            row["outcome"] = "failure"
            row["message"] = failures[0].attrib.get("message", "")
        elif errors:
            row["outcome"] = "error"
            row["message"] = errors[0].attrib.get("message", "")
        elif skips:
            reason = skips[0].attrib.get("message", "").strip()
            if reason not in known:
                raise TestBaselineEvidenceError(f"ungoverned skip reason for {nodeid}: {reason!r}")
            contract = known[reason]
            observed[contract["contract_id"]] += 1
            row.update(
                {
                    "outcome": "governed_skip",
                    "skip_reason": reason,
                    "contract_id": contract["contract_id"],
                    "absence_semantics": "skip_not_pass",
                }
            )
        else:
            row["outcome"] = "pass"
        rows.append(row)

    counts = Counter(row["outcome"] for row in rows)
    summary = {
        "tests": len(rows),
        "passed": counts["pass"],
        "governed_skips": counts["governed_skip"],
        "failures": counts["failure"],
        "errors": counts["error"],
    }
    if summary["failures"] or summary["errors"]:
        raise TestBaselineEvidenceError(f"JUnit contains failures/errors: {summary}")
    for contract in contract_document["contracts"]:
        minimum = contract.get("minimum_observed", 0)
        if not isinstance(minimum, int) or minimum < 0:
            raise TestBaselineEvidenceError("minimum_observed must be a non-negative integer")
        if observed[contract["contract_id"]] < minimum:
            raise TestBaselineEvidenceError(
                f"contract observation below minimum: {contract['contract_id']}"
            )
    return summary, rows, observed


def run_gate(argv: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "output": completed.stdout.strip(),
    }


def write_hashed_json(path: Path, document: dict[str, Any]) -> None:
    document["self_sha256"] = canonical_sha256(document)
    path.write_text(
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    junit_source = args.junit.resolve(strict=True)
    contracts_path = args.contracts.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise TestBaselineEvidenceError(f"output already exists: {output_dir}")
    if (
        args.source_commit
        != subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    ):
        raise TestBaselineEvidenceError("source commit does not match HEAD")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root, text=True).strip():
        raise TestBaselineEvidenceError("repository must be clean before evidence generation")

    contracts = load_contracts(contracts_path, repo_root)
    summary, test_rows, observed = parse_junit(junit_source, contracts)
    lint_gates = [
        run_gate([sys.executable, "-B", "-m", "ruff", "check", "src", "tests", "tools"], repo_root),
        run_gate(
            [sys.executable, "-B", "-m", "black", "--check", "src", "tests", "tools"],
            repo_root,
        ),
    ]
    if any(row["returncode"] != 0 for row in lint_gates):
        raise TestBaselineEvidenceError("static baseline gate failed")

    output_dir.mkdir(parents=True)
    junit_copy = output_dir / "full_suite_junit.xml"
    shutil.copyfile(junit_source, junit_copy)

    inventory = {
        "schema_version": "maskfactory.test_inventory.v1",
        "generated_at_utc": args.generated_at_utc,
        "source_commit": args.source_commit,
        "junit_sha256": sha256_file(junit_copy),
        "summary": summary,
        "tests": test_rows,
    }
    write_hashed_json(output_dir / "test_inventory.json", inventory)

    resolved_contracts = {
        "schema_version": "maskfactory.external_asset_contracts.evidence.v1",
        "generated_at_utc": args.generated_at_utc,
        "source_contract_path": contracts_path.relative_to(repo_root).as_posix(),
        "source_contract_sha256": sha256_file(contracts_path),
        "absence_semantics": "skip_not_pass",
        "unknown_skip_semantics": "fail_closed",
        "contracts": [
            {
                **row,
                "observed_test_count": observed[row["contract_id"]],
            }
            for row in contracts["contracts"]
        ],
    }
    write_hashed_json(output_dir / "external_asset_contracts.json", resolved_contracts)

    static_baseline = {
        "schema_version": "maskfactory.static_baseline.v1",
        "generated_at_utc": args.generated_at_utc,
        "source_commit": args.source_commit,
        "gates": lint_gates,
        "byte_pinned_formatter_exclusions": contracts["byte_pinned_formatter_exclusions"],
        "result": "PASS",
    }
    write_hashed_json(output_dir / "static_baseline.json", static_baseline)

    artifacts = {}
    for name in (
        "full_suite_junit.xml",
        "test_inventory.json",
        "external_asset_contracts.json",
        "static_baseline.json",
    ):
        target = output_dir / name
        artifacts[name] = {"bytes": target.stat().st_size, "sha256": sha256_file(target)}
    receipt = {
        "schema_version": "maskfactory.mf_p6_20_03_acceptance_receipt.v1",
        "generated_at_utc": args.generated_at_utc,
        "item_id": "MF-P6-20.03",
        "source_commit": args.source_commit,
        "summary": summary,
        "unexplained_outcomes": 0,
        "static_gates": {"ruff": "PASS", "black": "PASS"},
        "external_prerequisite_contract_count": len(contracts["contracts"]),
        "artifacts": artifacts,
        "acceptance": "PASS",
        "completion_effect": {
            "MF-P6-20.03": "eligible_for_complete_after_independent_receipt_validation",
            "MF-P6-20.04": "no_completion_credit",
        },
    }
    write_hashed_json(output_dir / "section_03_test_baseline_receipt.json", receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--contracts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        result = build(parse_args())
    except TestBaselineEvidenceError as exc:
        print(f"TEST_BASELINE_EVIDENCE_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, sort_keys=True, indent=2))
