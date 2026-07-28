#!/usr/bin/env python3
"""Add reproducible Plan/Item/tracker authority to the historical stash matrix.

The input matrix records byte relationships and semantic dispositions.  This
tool leaves those decisions unchanged and adds the project-control fields that
make every row independently attributable and reconstructable.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "2.0.0"
DEFAULT_PLAN_REFS = [
    "Plan/29_LOCAL_REPOSITORY_DIRECTORY_AND_TRACKER_CONVERGENCE.md",
    "Plan/LOCAL_AUTHORITY_RECONCILIATION_LEDGER_20260728.md",
    "Plan/Instructions/18_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md",
]
RECOVERY_ITEM = "MF-P6-20.01"
CANONICAL_TREE_ITEM = "MF-P6-20.02"
TEST_BASELINE_ITEM = "MF-P6-20.03"
RUNTIME_CLOSURE_ITEM = "MF-P6-20.04"

CANONICAL_DISPOSITIONS = {
    "ADOPTED_AS_SEMANTIC_PORT_ON_CURRENT_MAIN",
    "ADOPTED_EXACT_FROM_VERIFIED_STASH",
    "ADOPTED_TO_CANONICAL_TOOL_PATH",
    "ALREADY_EXACT_IN_CURRENT_MAIN",
}
ARCHIVED_DISPOSITIONS = {
    "GENERATED_PRECOMMIT_CACHE",
    "HISTORICAL_BYTES_ALREADY_IN_MAIN_HISTORY_SUPERSEDED",
    "HISTORICAL_CONTROL_SNAPSHOT_ARCHIVED_NOT_REPLAYED",
    "HISTORICAL_EVIDENCE_ARCHIVED",
    "HISTORICAL_NON_SOURCE_PAYLOAD_ARCHIVED",
    "HISTORICAL_RUNTIME_ARTIFACT_ARCHIVED",
    "PRESERVED_INCOMPLETE_PROTOTYPE_NOT_ADOPTED",
    "SUPERSEDED_BY_CURRENT_RUNPOD_SHARED_LEASE_POLICY",
    "SUPERSEDED_BY_PROTECTED_CONSUMER_AND_REAL_MAIN",
}

# These are deliberately narrow.  They add functional attribution for the
# reviewed recovery cohort without pretending every archived byte advances a
# product capability.
FUNCTIONAL_ITEM_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        (
            "configs/gold_volume_",
            "tools/assemble_autonomous_verification_corpus.py",
            "tools/repair_corpus_envelope_roots.py",
        ),
        ("MF-P4-11.23", "MF-P4-12.11"),
    ),
    (
        ("tools/build_production_audit_queue.py",),
        ("MF-P4-11.12",),
    ),
    (
        (
            "src/maskfactory/models/benchmark.py",
            "tools/mark_benchmarked_candidate.py",
            "tools/run_measured_champions_path.py",
            "tests/test_measured_champions_path_glue.py",
        ),
        ("MF-P5-06.03", "MF-P5-07.02"),
    ),
    (
        (
            "src/maskfactory/providers/nuclio_sam2.py",
            "tools/repair_package_nuclio_sam2.py",
            "tests/test_nuclio_sam2_clicks.py",
        ),
        ("MF-P0-04.02", "MF-P0-04.03"),
    ),
    (
        (
            "src/maskfactory/schemas/docker_serve_contract_report.schema.json",
            "src/maskfactory/serve/docker_contract.py",
            "tests/test_docker_serve_contract.py",
            "tools/verify_docker_serve_contract.py",
        ),
        ("MF-P6-02.01",),
    ),
    (
        ("tests/test_autonomy_emit_path.py",),
        ("MF-P6-17.04",),
    ),
    (
        ("tests/test_visual_defect_abstention.py",),
        ("MF-P6-21.02",),
    ),
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_tracker_ids(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", {})
    if not isinstance(items, dict):
        raise ValueError("tracker.json items must be an object keyed by Item ID")
    return set(items)


def read_git_blobs(repo: Path, oids: Iterable[str]) -> dict[str, dict[str, Any]]:
    unique = sorted({oid for oid in oids if oid})
    if not unique:
        return {}
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input=("\n".join(unique) + "\n").encode("ascii"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git cat-file failed ({completed.returncode}): {stderr}")

    result: dict[str, dict[str, Any]] = {}
    stream = io.BytesIO(completed.stdout)
    for requested_oid in unique:
        header = stream.readline()
        if not header:
            raise RuntimeError(f"git cat-file ended before {requested_oid}")
        parts = header.rstrip(b"\n").split()
        if len(parts) == 2 and parts[1] == b"missing":
            raise RuntimeError(f"required Git object is missing: {requested_oid}")
        if len(parts) != 3 or parts[1] != b"blob":
            raise RuntimeError(f"expected blob for {requested_oid}, got {header!r}")
        resolved_oid = parts[0].decode("ascii")
        size = int(parts[2])
        payload = stream.read(size)
        separator = stream.read(1)
        if len(payload) != size or separator != b"\n":
            raise RuntimeError(f"short or malformed blob read for {requested_oid}")
        result[requested_oid] = {
            "oid": resolved_oid,
            "size_bytes": size,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return result


def functional_items(path: str) -> list[str]:
    matches: set[str] = set()
    for needles, item_ids in FUNCTIONAL_ITEM_RULES:
        if any(path == needle or path.startswith(needle) for needle in needles):
            matches.update(item_ids)
    return sorted(matches)


def classify_items(row: dict[str, Any]) -> list[str]:
    path = str(row["path"])
    disposition = str(row["disposition"])
    item_ids = {RECOVERY_ITEM}

    if disposition in CANONICAL_DISPOSITIONS:
        item_ids.add(CANONICAL_TREE_ITEM)
        item_ids.update(functional_items(path))
        if path.startswith("tests/"):
            item_ids.add(TEST_BASELINE_ITEM)
        runtime_markers = (
            "/serve/",
            "/providers/",
            "docker_serve",
            "nuclio",
            "runtime",
            "gpu.py",
        )
        if any(marker in path.lower() for marker in runtime_markers):
            item_ids.add(RUNTIME_CLOSURE_ITEM)
    elif disposition == "GENERATED_PRECOMMIT_CACHE":
        item_ids.add(TEST_BASELINE_ITEM)

    return sorted(item_ids)


def canonical_location(row: dict[str, Any]) -> dict[str, Any]:
    path = str(row["path"])
    disposition = str(row["disposition"])
    if disposition in CANONICAL_DISPOSITIONS:
        canonical_path = (
            "tools/Repair-MaskFactoryWslVhd.ps1"
            if disposition == "ADOPTED_TO_CANONICAL_TOOL_PATH"
            else path
        )
        return {
            "state": "PRESENT_OR_SEMANTICALLY_PORTED",
            "git_ref": "main",
            "path": canonical_path,
        }
    if disposition == "HISTORICAL_BYTES_ALREADY_IN_MAIN_HISTORY_SUPERSEDED":
        return {
            "state": "HISTORICAL_ANCESTOR_ONLY_SUPERSEDED",
            "git_ref": "main-history",
            "path": path,
        }
    return {
        "state": "NOT_CANONICAL_PRODUCT_INPUT",
        "git_ref": None,
        "path": None,
    }


def limitations(row: dict[str, Any]) -> list[str]:
    disposition = str(row["disposition"])
    base = [
        "This attribution does not independently satisfy any product/runtime/visual/campaign acceptance gate.",
    ]
    if disposition == "PRESERVED_INCOMPLETE_PROTOTYPE_NOT_ADOPTED":
        base.append(
            "Prototype is incomplete and preserved for remediation; it is not executable authority."
        )
    elif disposition == "HISTORICAL_CONTROL_SNAPSHOT_ARCHIVED_NOT_REPLAYED":
        base.append(
            "Historical control state is evidence only and must never overwrite the live tracker."
        )
    elif disposition in ARCHIVED_DISPOSITIONS:
        base.append(
            "Bytes remain rollback/evidence authority only and are not part of canonical main."
        )
    elif disposition == "ADOPTED_AS_SEMANTIC_PORT_ON_CURRENT_MAIN":
        base.append(
            "Canonical bytes intentionally differ; current main is the reviewed semantic authority."
        )
    return base


def enrich_row(
    row: dict[str, Any],
    blob_metadata: dict[str, dict[str, Any]],
    source_matrix: Path,
    bundle_path: Path,
    bundle_sha256: str,
) -> dict[str, Any]:
    result = dict(row)
    stash_oid = str(row.get("stash_blob_oid") or "")
    main_oid = str(row.get("main_blob_oid") or "")
    item_ids = classify_items(row)
    result.update(
        {
            "owner": "MaskFactory",
            "repository": "KevinSGarrett/MaskingUltimate",
            "plan_refs": list(DEFAULT_PLAN_REFS),
            "item_ids": item_ids,
            "tracker_ids": list(item_ids),
            "evidence_locators": [
                {
                    "kind": "source_semantic_matrix",
                    "path": str(source_matrix),
                },
                {
                    "kind": "verified_incremental_bundle",
                    "path": str(bundle_path),
                    "sha256": bundle_sha256,
                },
                {
                    "kind": "canonical_reconciliation_ledger",
                    "path": "Plan/LOCAL_AUTHORITY_RECONCILIATION_LEDGER_20260728.md",
                },
            ],
            "stash_blob": blob_metadata.get(stash_oid),
            "main_blob": blob_metadata.get(main_oid),
            "canonical_location": canonical_location(row),
            "rollback_location": {
                "bundle_path": str(bundle_path),
                "stash_commit_oid": row["stash_oid"],
                "blob_oid": row.get("stash_blob_oid"),
                "path": row["path"],
            },
            "limitations": limitations(row),
            "completion_effect": {
                "kind": "RECOVERY_ATTRIBUTION_ONLY_NO_NEW_CREDIT",
                "tracker_status_change_allowed": False,
                "reason": (
                    "Row attribution preserves provenance and governs disposition; "
                    "the governing Item verify clauses require separate acceptance evidence."
                ),
            },
        }
    )
    return result


def validate_output(
    rows: list[dict[str, Any]],
    tracker_ids: set[str],
    expected_rows: int,
) -> dict[str, Any]:
    errors: list[str] = []
    if len(rows) != expected_rows:
        errors.append(f"row count {len(rows)} != expected {expected_rows}")
    required = {
        "owner",
        "repository",
        "plan_refs",
        "item_ids",
        "tracker_ids",
        "evidence_locators",
        "stash_blob",
        "canonical_location",
        "rollback_location",
        "limitations",
        "completion_effect",
    }
    unknown_ids: set[str] = set()
    row_keys: set[tuple[Any, ...]] = set()
    duplicate_keys: list[tuple[Any, ...]] = []
    for index, row in enumerate(rows):
        missing = sorted(required - set(row))
        if missing:
            errors.append(f"row {index} missing fields: {', '.join(missing)}")
        if not row.get("plan_refs") or not row.get("item_ids") or not row.get("tracker_ids"):
            errors.append(f"row {index} has an empty authority binding")
        unknown_ids.update(set(row.get("item_ids", [])) - tracker_ids)
        if row.get("item_ids") != row.get("tracker_ids"):
            errors.append(f"row {index} item_ids/tracker_ids differ")
        key = (
            row.get("stash_index"),
            row.get("stash_oid"),
            row.get("source"),
            row.get("path"),
        )
        if key in row_keys:
            duplicate_keys.append(key)
        row_keys.add(key)
        if row.get("stash_blob_oid") and not row.get("stash_blob"):
            errors.append(f"row {index} lacks stash blob metadata")
    if unknown_ids:
        errors.append(f"unknown tracker IDs: {', '.join(sorted(unknown_ids))}")
    if duplicate_keys:
        errors.append(f"duplicate row identities: {len(duplicate_keys)}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "row_count": len(rows),
        "unique_row_identity_count": len(row_keys),
        "rows_with_plan_refs": sum(bool(row.get("plan_refs")) for row in rows),
        "rows_with_item_ids": sum(bool(row.get("item_ids")) for row in rows),
        "rows_with_tracker_ids": sum(bool(row.get("tracker_ids")) for row in rows),
        "rows_with_evidence": sum(bool(row.get("evidence_locators")) for row in rows),
        "rows_with_canonical_location": sum(bool(row.get("canonical_location")) for row in rows),
        "rows_with_rollback_location": sum(bool(row.get("rollback_location")) for row in rows),
        "rows_with_limitations": sum(bool(row.get("limitations")) for row in rows),
        "rows_with_completion_effect": sum(bool(row.get("completion_effect")) for row in rows),
        "item_binding_counts": dict(
            sorted(Counter(item_id for row in rows for item_id in row["item_ids"]).items())
        ),
        "disposition_counts": dict(sorted(Counter(row["disposition"] for row in rows).items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--tracker", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=4008)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    source_matrix = args.input.resolve()
    tracker_path = args.tracker.resolve()
    bundle_path = args.bundle.resolve()
    output_path = args.output.resolve()
    summary_path = args.summary.resolve()

    rows = json.loads(source_matrix.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        raise ValueError("input matrix must be a JSON list")
    known_dispositions = CANONICAL_DISPOSITIONS | ARCHIVED_DISPOSITIONS
    unexpected = sorted({str(row.get("disposition")) for row in rows} - known_dispositions)
    if unexpected:
        raise ValueError(f"unrecognized dispositions: {', '.join(unexpected)}")

    object_ids = [
        oid for row in rows for oid in (row.get("stash_blob_oid"), row.get("main_blob_oid")) if oid
    ]
    blob_metadata = read_git_blobs(repo, object_ids)
    bundle_sha256 = sha256_file(bundle_path)
    enriched = [
        enrich_row(
            row,
            blob_metadata,
            source_matrix,
            bundle_path,
            bundle_sha256,
        )
        for row in rows
    ]
    validation = validate_output(enriched, load_tracker_ids(tracker_path), args.expected_rows)
    if validation["status"] != "PASS":
        raise ValueError("; ".join(validation["errors"]))

    output_document = {
        "schema_version": SCHEMA_VERSION,
        "source_matrix": str(source_matrix),
        "source_matrix_sha256": sha256_file(source_matrix),
        "verified_bundle": str(bundle_path),
        "verified_bundle_sha256": bundle_sha256,
        "authority_policy": {
            "default_plan_refs": DEFAULT_PLAN_REFS,
            "default_recovery_item": RECOVERY_ITEM,
            "canonical_tree_item": CANONICAL_TREE_ITEM,
            "test_baseline_item": TEST_BASELINE_ITEM,
            "runtime_closure_item": RUNTIME_CLOSURE_ITEM,
            "functional_rule_count": len(FUNCTIONAL_ITEM_RULES),
            "completion_credit_policy": "NO_ROW_GRANTS_NEW_COMPLETION_CREDIT",
        },
        "rows": enriched,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_json_bytes(output_document))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_matrix": str(output_path),
        "generated_matrix_sha256": sha256_file(output_path),
        "source_matrix": str(source_matrix),
        "source_matrix_sha256": sha256_file(source_matrix),
        "verified_bundle": str(bundle_path),
        "verified_bundle_sha256": bundle_sha256,
        "validation": validation,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_bytes(canonical_json_bytes(summary))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
