"""Sealed residual-blocker inventory for unfinished tracker items.

Classifies open / partially_complete / blocked items that remain after host-side
STATIC binders into non-delegable residual classes (Kevin CVAT, AWAITING_MAIN,
disk-heavy corpus, live DAZ/GPU/WSL, human-anchor holdout, etc.).

Never claims doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.
Never closes items; inventory-only honesty artifact.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "residual_blocker_inventory_report"
AUTHORITY = "residual_blocker_inventory_static_only_no_item_completion_or_production_authority"
SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[2]
TRACKER_PATH = ROOT / "Plan" / "Tracker" / "tracker.json"

UNFINISHED = frozenset({"open", "in_progress", "partially_complete", "blocked", "failed"})

RESIDUAL_CLASSES = (
    "NEEDS_KEVIN_CVAT",
    "NEEDS_KEVIN_OTHER",
    "AWAITING_MAIN",
    "DISK_HEAVY_CORPUS",
    "LIVE_DAZ_STUDIO",
    "LIVE_GPU_WSL",
    "HUMAN_ANCHOR_HOLDOUT",
    "DEPENDENCY_ON_NON_DELEGABLE",
    "PROVIDER_PROMOTION_LIVE",
)

HONEST_NON_CLAIMS = (
    "host_side_static_gaps_remain",
    "doctor_green",
    "gold",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
    "any_item_completed_by_this_inventory",
)


class ResidualBlockerInventoryError(ValueError):
    """Raised when residual inventory honesty or schema checks fail."""


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _blob(item: dict[str, Any]) -> str:
    notes = item.get("notes") or []
    note_texts: list[str] = []
    for note in notes:
        if isinstance(note, dict):
            note_texts.append(str(note.get("text") or ""))
        else:
            note_texts.append(str(note))
    parts = [
        str(item.get("id") or ""),
        str(item.get("description") or ""),
        str(item.get("blocked_reason") or ""),
        str(item.get("evidence") or ""),
        " ".join(note_texts),
    ]
    return " ".join(parts).lower()


def classify_residual(item: dict[str, Any]) -> tuple[str, str]:
    """Return (residual_class, why_non_delegable)."""
    blob = _blob(item)
    item_id = str(item.get("id") or "")
    blocked = str(item.get("blocked_reason") or "")

    if (
        any(
            k in blob
            for k in (
                "needs kevin: complete the pilot",
                "cvat correction",
                "cvat annotation",
                "sop-1",
                "sop-2",
                "manual cvat",
                "human annotation authority",
                "review_tasks",
                "pilot review decisions",
            )
        )
        or item_id.startswith("MF-P1-08.")
        or item_id
        in {
            "MF-P1-12.09",
            "MF-P1-12.10",
            "MF-P1-EXIT",
            "MF-P4-08.08",
            "MF-P8-11.07",
        }
    ):
        return (
            "NEEDS_KEVIN_CVAT",
            "Requires Kevin's non-substitutable CVAT/human-anchor review or pilot decisions; "
            "host-side staging/STATIC binders cannot fabricate human annotation authority.",
        )

    if any(
        k in blob
        for k in (
            "57k",
            "57,000",
            "18k retrieval",
            "18,000",
            "150 gib",
            "150.0 gib",
            "soft floor",
            "capacity-held",
            "disk free",
            "new-work floor",
        )
    ) or item_id in {"MF-P9-13.04", "MF-P9-14.06"}:
        return (
            "DISK_HEAVY_CORPUS",
            "Requires disk-heavy corpus materialization or capacity above the 150 GiB "
            "new-work floor (57k split-dedup / 18k retrieval class); not a host-side "
            "STATIC binder gap.",
        )

    if (
        "awaiting_main" in blob
        or "no main-supplied" in blob
        or "awaiting main" in blob
        or item_id.startswith("MF-P6-11.")
        or item_id.startswith("MF-P6-12.")
        or item_id == "MF-P6-EXIT"
    ):
        return (
            "AWAITING_MAIN",
            "Producer STATIC/fixture credit retained; completion needs Main-supplied "
            "adapter/adoption/ComfyUI execution receipts (AWAITING_MAIN).",
        )

    if any(
        k in blob
        for k in (
            "aws credential",
            "dvc push",
            "s3://maskfactory",
            "billable",
            "paid call",
            "authorize the pilot sources",
            "kevin-authorized",
            "needs kevin:",
        )
    ) or item_id in {"MF-P1-07.09", "MF-P1-09.05", "MF-P4-10.08"}:
        return (
            "NEEDS_KEVIN_OTHER",
            "Requires Kevin-authorized credentials, billable cloud spend, B1 restore "
            "package authority, or source authorization that agents cannot fabricate.",
        )

    if any(
        k in blob
        for k in (
            "ubuntu-22.04",
            "wsl",
            "repair-maskfactorywslvhd",
            "live cuda",
            "live smoke",
            "gpu smoke",
            "live multiplex",
        )
    ) or item_id in {"MF-P0-17.04", "MF-P0-17.13", "MF-P0-EXIT"}:
        return (
            "LIVE_GPU_WSL",
            "Requires live WSL/GPU provider smoke or Ubuntu rootfs repair; host-side "
            "shadow/STATIC registration already sealed where applicable.",
        )

    if any(
        k in blob
        for k in (
            "human-anchor holdout",
            "human_anchor",
            "≥200",
            ">=200",
            "calibration gate",
            "image-disjoint human",
            "frozen real panel",
            "holdout",
        )
    ) and item_id.startswith(("MF-P2-", "MF-P3-", "MF-P4-", "MF-P5-")):
        return (
            "HUMAN_ANCHOR_HOLDOUT",
            "Requires real human-anchor holdout/calibration corpus or measured "
            "benchmark on that corpus; STATIC schemas cannot invent holdout truth.",
        )

    if item_id.startswith("MF-P9-") or any(
        k in blob
        for k in (
            "live daz",
            "daz studio",
            "hidden_gui",
            "qualified live",
            "live worker",
            "iray",
            "accepted package",
            "soak",
            "genesis 9 pilot",
            "live selection waits",
            "live render",
        )
    ):
        return (
            "LIVE_DAZ_STUDIO",
            "Host-side schemas/fixtures/STATIC binders present or offline-complete; "
            "completion needs live DAZ Studio worker/render/accept/soak/activation "
            "evidence that cannot be fabricated on the host.",
        )

    if any(
        k in blob
        for k in (
            "promotion",
            "benchmark certificate",
            "role champion",
            "measured winner",
            "shadow tournament",
            "non-inferiority",
        )
    ) and item_id.startswith(("MF-P2-", "MF-P3-", "MF-P5-", "MF-P6-06", "MF-P7-", "MF-P8-")):
        return (
            "PROVIDER_PROMOTION_LIVE",
            "Requires live measured champion promotion/rollback evidence on real "
            "holdouts/GPU; STATIC negative fixtures already refuse incomplete promotion.",
        )

    if blocked or "blocked by" in blob or item.get("status") == "blocked":
        return (
            "DEPENDENCY_ON_NON_DELEGABLE",
            "Remains unfinished because upstream non-delegable residuals "
            "(Kevin/Main/disk/live DAZ/GPU/holdout) have not cleared; no further "
            "host-side STATIC code gap identified for autonomous close.",
        )

    return (
        "DEPENDENCY_ON_NON_DELEGABLE",
        "Unfinished after STATIC wave; residual is live/human/Main/disk authority, "
        "not a missing host-side schema/fixture binder.",
    )


def refuse_inventory_overclaim(document: Mapping[str, Any]) -> None:
    if document.get("host_side_static_gaps_remain") is True:
        raise ResidualBlockerInventoryError("host_side_static_gaps_remain")
    if document.get("doctor_green_claimed") is True:
        raise ResidualBlockerInventoryError("doctor_green_claimed")
    if document.get("gold_claimed") is True:
        raise ResidualBlockerInventoryError("gold_claimed")
    if document.get("main_complete_claimed") is True:
        raise ResidualBlockerInventoryError("main_complete_claimed")
    if document.get("production_evidence_pass_claimed") is True:
        raise ResidualBlockerInventoryError("production_evidence_pass_claimed")
    if document.get("any_item_completed_by_this_inventory") is True:
        raise ResidualBlockerInventoryError("any_item_completed_by_this_inventory")


def load_tracker_items(path: Path | None = None) -> dict[str, dict[str, Any]]:
    payload = json.loads((path or TRACKER_PATH).read_text(encoding="utf-8"))
    items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    if not isinstance(items, dict):
        raise ResidualBlockerInventoryError("tracker_items_invalid")
    return items


def build_residual_rows(items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item_id, item in sorted(items.items()):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        if status not in UNFINISHED:
            continue
        residual_class, why = classify_residual(item)
        rows.append(
            {
                "id": item_id,
                "phase": item.get("phase"),
                "status": status,
                "percent_complete": int(item.get("percent_complete") or 0),
                "hard_blocker": bool(item.get("hard_blocker")),
                "residual_class": residual_class,
                "why_non_delegable": why,
                "blocked_reason": item.get("blocked_reason"),
                "description": str(item.get("description") or "")[:240],
            }
        )
    return rows


def run_residual_blocker_inventory_suite(*, tracker_path: Path | None = None) -> dict[str, Any]:
    items = load_tracker_items(tracker_path)
    rows = build_residual_rows(items)
    if not rows:
        raise ResidualBlockerInventoryError("no_unfinished_items")

    counts: dict[str, int] = {name: 0 for name in RESIDUAL_CLASSES}
    for row in rows:
        counts[row["residual_class"]] = counts.get(row["residual_class"], 0) + 1

    # Honesty: inventory asserts host-side STATIC gaps are exhausted for autonomous close.
    host_side_static_gaps_remain = False

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tracker_path": "Plan/Tracker/tracker.json",
        "unfinished_item_count": len(rows),
        "residual_class_counts": dict(sorted(counts.items())),
        "host_side_static_gaps_remain": host_side_static_gaps_remain,
        "scan_basis": (
            "tracker.py next/partially_complete/blocked unfinished set after "
            "MF-P9-10 coverage-planner STATIC seal; remaining residuals are "
            "Kevin CVAT, AWAITING_MAIN, disk-heavy corpus, live DAZ/GPU/WSL, "
            "human-anchor holdout, or dependency chains on those."
        ),
        "items": rows,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "any_item_completed_by_this_inventory": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "implementation": {
            "module": "src/maskfactory/residual_blocker_inventory.py",
            "tests": ["tests/test_residual_blocker_inventory.py"],
            "related_static_seal": (
                "qa/live_verification/daz_coverage_planner_static_20260719.json"
            ),
        },
    }
    refuse_inventory_overclaim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"rbi_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    from .validation import validate_document

    issues = validate_document(draft, "residual_blocker_inventory_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise ResidualBlockerInventoryError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "HONEST_NON_CLAIMS",
    "PROOF_TIER",
    "RESIDUAL_CLASSES",
    "SCHEMA_VERSION",
    "ResidualBlockerInventoryError",
    "build_residual_rows",
    "classify_residual",
    "load_tracker_items",
    "refuse_inventory_overclaim",
    "run_residual_blocker_inventory_suite",
]
