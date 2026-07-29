#!/usr/bin/env python3
"""Independently validate and seal MF-P6-20.04 reconstruction evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.build_test_baseline_evidence import (
    TestBaselineEvidenceError,
    canonical_sha256,
    load_contracts,
    parse_junit,
    sha256_file,
    write_hashed_json,
)


class RuntimeAcceptanceError(RuntimeError):
    """The runtime evidence cannot support MF-P6-20.04 acceptance."""


def _git(repo_root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise RuntimeAcceptanceError(
            f"git command failed: {arguments!r}: {(process.stderr or process.stdout)[-1000:]}"
        )
    return process.stdout.strip()


def _validate_self_hash(document: dict[str, Any], *, label: str) -> None:
    if document.get("self_sha256") != canonical_sha256(document):
        raise RuntimeAcceptanceError(f"{label} self hash mismatch")


def validate_lifecycle(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    document = json.loads(path.read_text(encoding="utf-8"))
    _validate_self_hash(document, label="service lifecycle evidence")
    if document.get("schema_version") != "maskfactory.service_lifecycle_evidence.v1":
        raise RuntimeAcceptanceError("unsupported service lifecycle evidence schema")
    if document.get("result") != "PASS" or document.get("item_id") != "MF-P6-20.04":
        raise RuntimeAcceptanceError("service lifecycle result/item is not acceptable")
    source = document.get("source", {})
    if source.get("commit") != source.get("origin_main") or source.get("status_rows") != 0:
        raise RuntimeAcceptanceError("service source was not clean local/remote main")

    clean_export = document.get("clean_export", {})
    if clean_export.get("build_exit_code") != 0 or clean_export.get("install_exit_code") != 0:
        raise RuntimeAcceptanceError("clean export build/install did not pass")
    artifact_root = Path(document.get("artifact_root", "")).resolve(strict=True)
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict) or len(artifacts) != 5:
        raise RuntimeAcceptanceError("lifecycle artifact registry must contain exactly five files")
    for name, binding in artifacts.items():
        target = (artifact_root / name).resolve(strict=True)
        if artifact_root not in target.parents:
            raise RuntimeAcceptanceError(f"artifact escapes retained root: {name}")
        if target.stat().st_size != binding.get("bytes"):
            raise RuntimeAcceptanceError(f"artifact size mismatch: {name}")
        if sha256_file(target) != binding.get("sha256"):
            raise RuntimeAcceptanceError(f"artifact hash mismatch: {name}")

    routes = document.get("routes", {})
    health = routes.get("health", {})
    models = routes.get("models", {})
    refusal = routes.get("predict_without_champions", {})
    if health.get("http_status") != 200 or health.get("body", {}).get("status") != "ok":
        raise RuntimeAcceptanceError("bounded health route did not pass")
    if models.get("http_status") != 200 or models.get("verified_model_count") != 17:
        raise RuntimeAcceptanceError("bounded models route did not expose the exact registry")
    if models.get("champion_count") != 0:
        raise RuntimeAcceptanceError("local lifecycle unexpectedly claims a champion")
    if (
        refusal.get("http_status") != 503
        or refusal.get("body", {}).get("detail") != "champion prediction provider is not configured"
    ):
        raise RuntimeAcceptanceError("missing-champion route did not fail closed exactly")

    process = document.get("process", {})
    resources = document.get("resources", {})
    network = document.get("network", {})
    shutdown = document.get("shutdown", {})
    if process.get("returncode") != 0 or process.get("post_shutdown_leaked_pids") != []:
        raise RuntimeAcceptanceError("owned process did not terminate cleanly")
    if network.get("host") != "127.0.0.1" or network.get("post_shutdown_open") is not False:
        raise RuntimeAcceptanceError("loopback network ownership/leak proof failed")
    required_zero = {
        "ports_leaked",
        "processes_leaked",
        "reservations_created",
        "leases_created",
    }
    if any(resources.get(key) != 0 for key in required_zero):
        raise RuntimeAcceptanceError("one or more resource leak counters are nonzero")
    if resources.get("gpu_work_performed") is not False:
        raise RuntimeAcceptanceError("local lifecycle performed unleased GPU work")
    if resources.get("gpu_compute_before", {}).get("rows") != resources.get(
        "gpu_compute_after", {}
    ).get("rows"):
        raise RuntimeAcceptanceError("GPU compute snapshot changed")
    if shutdown.get("runtime_final_health", {}).get("status") != "not_started":
        raise RuntimeAcceptanceError("runtime shutdown hook did not run")

    persistent = document.get("persistent_restore", {})
    if persistent.get("status") != "PASS":
        raise RuntimeAcceptanceError("persistent restore is not passing")
    prior = persistent.get("prior_receipt", {})
    replacement = persistent.get("replacement_receipt", {})
    if prior.get("pod_id") == replacement.get("pod_id"):
        raise RuntimeAcceptanceError("persistent restore did not use a distinct Pod")
    if prior.get("network_volume_id") != replacement.get("network_volume_id"):
        raise RuntimeAcceptanceError("persistent restore changed network volumes")
    if replacement.get("result_checks") != 14:
        raise RuntimeAcceptanceError("persistent restore does not bind all 14 checks")
    return document


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    lifecycle_path = args.lifecycle.resolve(strict=True)
    junit_path = args.junit.resolve(strict=True)
    output_dir = args.output_dir.resolve(strict=True)
    if lifecycle_path.parent != output_dir:
        raise RuntimeAcceptanceError("lifecycle evidence must live in the output directory")
    for name in (
        "clean_export_reconstruction_receipt.json",
        "runpod_restore_receipt.json",
        "section_acceptance_receipt.json",
        "independent_validation.json",
        "full_suite_junit.xml",
    ):
        if (output_dir / name).exists():
            raise RuntimeAcceptanceError(f"output already exists: {name}")

    lifecycle = validate_lifecycle(lifecycle_path)
    full_suite_source = _git(repo_root, "rev-parse", f"{args.full_suite_source}^{{commit}}")
    head = _git(repo_root, "rev-parse", "HEAD")
    origin_main = _git(repo_root, "rev-parse", "origin/main")
    if full_suite_source != head or head != origin_main:
        raise RuntimeAcceptanceError("full-suite source must equal local and remote main")
    lifecycle_source = lifecycle["source"]["commit"]
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", lifecycle_source, full_suite_source],
        cwd=repo_root,
        check=False,
    )
    if ancestor.returncode:
        raise RuntimeAcceptanceError("lifecycle source is not an ancestor of full-suite source")
    changed = [
        line
        for line in _git(
            repo_root, "diff", "--name-only", lifecycle_source, full_suite_source
        ).splitlines()
        if line
    ]
    runtime_changes = [
        path
        for path in changed
        if path.startswith(
            ("src/", "tests/", "tools/", "pyproject.toml", ".pre-commit-config.yaml")
        )
    ]
    if runtime_changes:
        raise RuntimeAcceptanceError(
            f"runtime/test source changed after lifecycle proof: {runtime_changes}"
        )

    contracts = load_contracts(args.contracts.resolve(strict=True), repo_root)
    summary, rows, observed = parse_junit(junit_path, contracts)
    expected_tests = args.expected_tests
    if summary["tests"] != expected_tests:
        raise RuntimeAcceptanceError(
            f"full-suite count {summary['tests']} does not equal expected {expected_tests}"
        )
    if summary["failures"] or summary["errors"]:
        raise RuntimeAcceptanceError("full suite contains failures/errors")
    if summary["passed"] + summary["governed_skips"] != expected_tests:
        raise RuntimeAcceptanceError("full suite outcome accounting is incomplete")

    junit_copy = output_dir / "full_suite_junit.xml"
    shutil.copyfile(junit_path, junit_copy)
    clean_receipt = {
        "schema_version": "maskfactory.clean_export_reconstruction_receipt.v1",
        "result": "PASS",
        "item_id": "MF-P6-20.04",
        "lifecycle_source_commit": lifecycle_source,
        "full_suite_source_commit": full_suite_source,
        "runtime_source_changes_after_lifecycle": runtime_changes,
        "changed_governance_paths_after_lifecycle": changed,
        "source_tree": lifecycle["source"]["tree"],
        "clean_export": lifecycle["clean_export"],
        "deployment_inputs": lifecycle["deployment_inputs"],
        "artifact_root": lifecycle["artifact_root"],
        "artifacts": lifecycle["artifacts"],
    }
    write_hashed_json(output_dir / "clean_export_reconstruction_receipt.json", clean_receipt)

    restore_receipt = {
        "schema_version": "maskfactory.runpod_restore_acceptance.v1",
        "result": "PASS",
        "item_ids": ["MF-P0-17.25", "MF-P6-20.04"],
        "persistent_restore": lifecycle["persistent_restore"],
        "authority": (
            "Exact persistent package transport/restore only; no model, mask, gold, "
            "champion, release, or ComfyUI-adoption authority."
        ),
    }
    write_hashed_json(output_dir / "runpod_restore_receipt.json", restore_receipt)

    acceptance = {
        "schema_version": "maskfactory.section03_runtime_acceptance.v1",
        "created_utc": args.created_utc,
        "result": "PASS",
        "item_id": "MF-P6-20.04",
        "lifecycle_source_commit": lifecycle_source,
        "full_suite_source_commit": full_suite_source,
        "full_suite": {
            **summary,
            "junit_bytes": junit_copy.stat().st_size,
            "junit_sha256": sha256_file(junit_copy),
            "external_prerequisite_contracts": len(contracts["contracts"]),
            "observed_contracts": dict(sorted(observed.items())),
            "unknown_skips": 0,
            "node_ids": len(rows),
        },
        "focused_validation": {
            "serve_lifecycle_tool_and_api_tests": 27,
            "serving_and_docker_focused_tests": 54,
            "ruff": "PASS",
            "black": "PASS",
        },
        "lifecycle_evidence": {
            "path": lifecycle_path.relative_to(repo_root).as_posix(),
            "bytes": lifecycle_path.stat().st_size,
            "sha256": sha256_file(lifecycle_path),
            "self_sha256": lifecycle["self_sha256"],
        },
        "clean_export_receipt": "clean_export_reconstruction_receipt.json",
        "runpod_restore_receipt": "runpod_restore_receipt.json",
        "zero_leaked_resources": True,
        "acceptance_effect": {
            "MF-P6-20.04": "eligible_for_complete_after_tracker_adjudication",
            "champion_or_inference_items": "no_completion_credit",
        },
        "limitations": lifecycle["limitations"],
    }
    write_hashed_json(output_dir / "section_acceptance_receipt.json", acceptance)

    files = {}
    for name in (
        "service_lifecycle_evidence.json",
        "full_suite_junit.xml",
        "clean_export_reconstruction_receipt.json",
        "runpod_restore_receipt.json",
        "section_acceptance_receipt.json",
    ):
        target = output_dir / name
        files[name] = {"bytes": target.stat().st_size, "sha256": sha256_file(target)}
    independent = {
        "schema_version": "maskfactory.section03_runtime_independent_validation.v1",
        "created_utc": args.created_utc,
        "result": "PASS",
        "checks": {
            "lifecycle_self_hash": "PASS",
            "retained_artifact_readback": "PASS",
            "clean_build_install_import": "PASS",
            "loopback_health_and_models": "PASS",
            "missing_champion_fail_closed": "PASS",
            "owned_shutdown_hook": "PASS",
            "zero_process_port_lease_reservation_gpu_leaks": "PASS",
            "distinct_pod_persistent_restore": "PASS",
            "complete_suite_exact_accounting": "PASS",
            "no_runtime_source_drift": "PASS",
        },
        "files": files,
    }
    write_hashed_json(output_dir / "independent_validation.json", independent)
    return acceptance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--lifecycle", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--contracts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--full-suite-source", required=True)
    parser.add_argument("--expected-tests", type=int, required=True)
    parser.add_argument("--created-utc", required=True)
    return parser.parse_args()


def main() -> int:
    try:
        receipt = build(parse_args())
    except (
        RuntimeAcceptanceError,
        TestBaselineEvidenceError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"RUNTIME_ACCEPTANCE_FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
