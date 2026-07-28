"""Build the immutable planning-packet preservation manifest.

The manifest records every dirty or untracked file in the isolated MaskFactory
bridge worktree before it is committed. It is preservation evidence only: it
does not publish a MaskFactory runtime release or grant artifact authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    ROOT / "Plan" / "Instructions" / "10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json"
)
OUTPUT_RELATIVE = OUTPUT.relative_to(ROOT).as_posix()


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="surrogateescape").strip()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _status_entries() -> list[dict[str, Any]]:
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    records = raw.decode("utf-8", errors="surrogateescape").split("\0")
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise RuntimeError(f"unexpected git status record: {record!r}")
        status = record[:2]
        relative = record[3:].replace("\\", "/")
        original_relative: str | None = None
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise RuntimeError(f"rename/copy record lacks its source: {record!r}")
            original_relative = records[index].replace("\\", "/")
            index += 1
        if relative == OUTPUT_RELATIVE:
            continue
        absolute = (ROOT / relative).resolve()
        try:
            absolute.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise RuntimeError(f"status path escaped repository: {relative!r}") from exc
        if absolute.is_dir():
            raise RuntimeError(f"status record unexpectedly names a directory: {relative!r}")
        exists = absolute.is_file()
        entry: dict[str, Any] = {
            "path": relative,
            "git_status": status,
            "tracked_before_packet": status != "??",
            "exists": exists,
            "size_bytes": absolute.stat().st_size if exists else None,
            "sha256": _sha256_bytes(absolute.read_bytes()) if exists else None,
        }
        if original_relative is not None:
            entry["original_path"] = original_relative
        entries.append(entry)
    entries.sort(key=lambda value: value["path"].casefold())
    if len({entry["path"].casefold() for entry in entries}) != len(entries):
        raise RuntimeError("preservation packet contains duplicate/case-aliased paths")
    return entries


def build_manifest(*, freeze_state: str, generated_at: str | None = None) -> dict[str, Any]:
    entries = _status_entries()
    feature_branch = _git("branch", "--show-current") or "codex/mask-autonomy-bridge-plan"
    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "manifest_id": "maskfactory_autonomous_core_bridge_planning_preservation_v1",
        "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "planning_preservation_only_no_runtime_release_or_artifact_authority",
        "runtime_completion_claimed": False,
        "producer_contract_freeze_state": freeze_state,
        "manifest_path": OUTPUT_RELATIVE,
        "self_inventory_policy": "manifest_self_excluded_from_entries_and_bound_by_manifest_sha256",
        "producer": {
            "task_id": "019f4cfc-60c3-7500-8626-261dcf70db5d",
            "authoritative_root": "C:/Comfy_UI_Main_Masking",
            "isolated_worktree": "C:/w/mask-autonomy-bridge-plan",
            "feature_branch": "codex/mask-autonomy-bridge-plan",
            "intended_pr_base": "codex/autonomous-gold-modernization",
        },
        "consumer": {
            "task_id": "019f422f-88b1-7382-872b-21de2089e983",
            "authoritative_root": "C:/Comfy_UI_Main",
            "isolated_worktree": "C:/w/main-maskfactory-bridge-plan",
            "feature_branch": "codex/w64-maskfactory-bridge-plan",
            "intended_pr_base": "main",
        },
        "release_adoption_order": [
            "freeze_and_validate_producer_contract_packet",
            "commit_and_publish_maskfactory_planning_pr_without_merging",
            "bind_main_mapping_to_exact_producer_commit_and_schema_hashes",
            "commit_and_publish_main_planning_pr_without_merging",
            "maskfactory_runtime_implementation_publishes_clean_signed_release",
            "main_verifies_and_records_adoption_before_runtime_use",
        ],
        "model_library_activation": {
            "state": "deferred_waiting_for_complete_model_download",
            "record_count": 7282,
            "activation_requires": [
                "user_confirms_downloads_complete",
                "main_task_records_inventory_acknowledgement",
            ],
            "blocking_for_core_bridge_planning": False,
        },
        "preservation_rules": [
            "do_not_delete_clean_overwrite_or_absorb_as_incidental_dirty_work",
            "do_not_consume_dirty_worktree_bytes_as_release_authority",
            "do_not_mutate_the_other_projects_tracker_or_gold_truth",
            "do_not_claim_runtime_completion_from_this_planning_packet",
        ],
        "source_state": {
            "repository_root": ROOT.as_posix(),
            "feature_head": _git("rev-parse", "HEAD"),
            "feature_branch": feature_branch,
            "intended_base_head_observed": _git(
                "rev-parse", "origin/codex/autonomous-gold-modernization"
            ),
            "entry_count": len(entries),
            "entries_sha256": _canonical_sha256(entries),
            "entries": entries,
        },
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--freeze-state",
        choices=("pending", "frozen_for_review"),
        default=None,
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    existing: dict[str, Any] | None = None
    if args.check and OUTPUT.is_file():
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SystemExit("planning preservation manifest is not an object")
        existing = value
    freeze_state = args.freeze_state or (
        str(existing["producer_contract_freeze_state"]) if existing is not None else "pending"
    )
    generated_at = str(existing["generated_at"]) if existing is not None else None
    document = build_manifest(freeze_state=freeze_state, generated_at=generated_at)
    rendered = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("planning preservation manifest is stale")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(OUTPUT)
    print(
        json.dumps(
            {
                "entry_count": document["source_state"]["entry_count"],
                "freeze_state": document["producer_contract_freeze_state"],
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
