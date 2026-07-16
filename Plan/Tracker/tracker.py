#!/usr/bin/env python3
"""
MaskFactory Project Tracker
===========================
Canonical, machine-readable status tracker for the Ultimate Masking System
build-out: 755 action items across phases P0-P9, plus Definition-of-Done
(D1-D11) and Goals (G1-G9) rollups, plus free-form project metrics.

SOURCE OF TRUTH SPLIT (important — mirrors the project's own "derived vs
hand-authored" philosophy):
  - Item METADATA (id, description, phase, spec reference, hard-blocker /
    conditional / exit-gate flags) is derived from
    C:\\Comfy_UI_Main_Masking\\Plan\\Items\\*.md via `rebuild`. Never hand-edit
    that metadata inside tracker.json — edit the Items/*.md files and rerun
    `rebuild` (it preserves all existing STATE when it does).
  - Item STATE (status, percent_complete, evidence, notes, blocked_reason,
    timestamps) lives only in tracker.json and is mutated ONLY through this
    CLI's `set` / `metrics` / `goal` commands (never hand-edit tracker.json).

See README.md in this folder for the full command reference and the rules
an AI agent (or human) must follow when using this tracker.

Quick start:
  python tracker.py rebuild
  python tracker.py report
  python tracker.py list --status open --phase P0
  python tracker.py show MF-P0-01.01
  python tracker.py set MF-P0-01.01 --status complete --evidence "doctor green, see OPS_LOG"
  python tracker.py set MF-P2-05.02 --status blocked --blocked-reason "waiting on ckpt download"
  python tracker.py next -n 10
  python tracker.py metrics --set human_anchor_train_count=42
  python tracker.py goal G2 --measured "0.87 body / 0.71 fingers" --status met
  python tracker.py validate
"""

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout/stderr regardless of the Windows console's active code
# page. Item text legitimately contains characters like >=, section-sign,
# middle-dot, and em-dash; the default cp1252 console encoding raises
# UnicodeEncodeError on those. All file writes elsewhere in this script
# already pass encoding="utf-8" explicitly -- this only fixes console output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Paths (all relative to this script's location — the tool is relocatable)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent  # ...\Plan\Tracker
PLAN_DIR = ROOT.parent  # ...\Plan
ITEMS_DIR = PLAN_DIR / "Items"
TRACKER_JSON = ROOT / "tracker.json"
CHANGELOG = ROOT / "CHANGELOG.jsonl"
BACKUPS_DIR = ROOT / "backups"
DASHBOARD = ROOT / "DASHBOARD.md"
PHASES_DIR = ROOT / "phases"

# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------
STATUSES = [
    "open",  # not started (default)
    "in_progress",  # actively being worked
    "partially_complete",  # some sub-verification done, not fully passing yet
    "blocked",  # cannot proceed; requires blocked_reason
    "complete",  # verify clause satisfied; requires evidence
    "failed",  # attempted, did not pass verification; needs rework
    "deferred",  # intentionally postponed (not blocked, deprioritized)
    "not_applicable",  # conditional item whose trigger never fired
]
DONE_STATUSES = {"complete", "not_applicable"}

STATUS_GLYPH = {
    "open": "\u2610",  # ☐
    "in_progress": "\U0001f527",  # 🔧
    "partially_complete": "\U0001f7e8",  # 🟨
    "blocked": "\U0001f6ab",  # 🚫
    "complete": "\u2611",  # ☑
    "failed": "\u274c",  # ❌
    "deferred": "\u23f8",  # ⏸
    "not_applicable": "\u2796",  # ➖
}

EXPECTED_ITEM_COUNT = 755

DEFAULT_METRICS = {
    # Historical compatibility metric. Never use as the sole P5/D5 gate.
    "approved_gold_count": 0,
    "human_anchor_train_count": 0,
    "human_anchor_calibration_count": 0,
    "human_anchor_holdout_count": 0,
    "autonomous_certified_gold_count": 0,
    "weighted_pseudo_label_count": 0,
    "machine_candidate_count": 0,
    "certified_training_package_count": 0,
    "effective_training_weight_units": 0.0,
    "zero_touch_fraction": None,
    "routine_human_touch_fraction": None,
    "audited_fraction": None,
    "residual_review_fraction": None,
    "human_touches_per_100_images": None,
    "manual_changed_pixels_per_100k": None,
    "audit_false_accept_rate": None,
    "serious_false_accept_rate": None,
    "target_certified_p5_entry": 200,
    "target_certified_d5": 300,
    "target_certified_g6_stretch": 500,
    "coverage_cells_at_target_pct": 0,
    # DAZ vertical-slice execution counters. These intentionally separate
    # implemented/fixture-tested contracts from live DAZ acceptance evidence.
    "daz_asset_identity_hashes_complete": 0,
    "daz_asset_identity_hashes_total": 0,
    "daz_live_compatibility_graph_status": "unpublished",
    "daz_live_qualified_asset_count": 0,
    "daz_live_smoke_certificate_count": 0,
    "daz_live_assembled_scene_count": 0,
    "daz_live_exact_synthetic_package_count": 0,
    "daz_synthetic_trained_challenger_count": 0,
    "daz_measured_real_image_improvement_status": "not_measured",
    "daz_storage_free_gib": None,
    "daz_storage_new_work_floor_gib": 150.0,
    "daz_storage_new_work_allowed": False,
}

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
PHASE_ORDER = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]
PHASE_META = {
    "P0": {
        "name": "Environment & Foundation",
        "file": "01_ITEMS_P0_ENVIRONMENT.md",
        "entry_gate": None,
    },
    "P1": {
        "name": "Gold Factory MVP",
        "file": "02_ITEMS_P1_GOLD_FACTORY_MVP.md",
        "entry_gate": "P0 core exit plus active-registry governance; provider work requires honest installed states",
    },
    "P2": {
        "name": "Body-Aware Drafting",
        "file": "03_ITEMS_P2_BODY_AWARE_DRAFTING.md",
        "entry_gate": "P1 core exit; v2 drafting additionally needs inactive v2 authority/migration contracts",
    },
    "P3": {
        "name": "Specialist Lanes",
        "file": "04_ITEMS_P3_SPECIALIST_LANES.md",
        "entry_gate": "P2 core exit; modern specialists require governed installed challengers",
    },
    "P4": {
        "name": "VLM QA & Active Learning",
        "file": "05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md",
        "entry_gate": "runs parallel to late P3; certification needs image-disjoint human-anchor calibration evidence",
    },
    "P5": {
        "name": "Custom Model Training",
        "file": "06_ITEMS_P5_TRAINING.md",
        "entry_gate": "certified_training_package_count >= 200 plus image-disjoint human-anchor holdout",
    },
    "P6": {
        "name": "ComfyUI Integration & Serving",
        "file": "07_ITEMS_P6_COMFYUI_SERVING.md",
        "entry_gate": "DoD D6 plus eligible promoted provider roles and rollback evidence",
    },
    "P7": {
        "name": "Scale & Continuous Operation",
        "file": "08_ITEMS_P7_SCALE_OPERATIONS.md",
        "entry_gate": "P6 exit plus current currency/certificate/rollback reviews",
    },
    "P8": {
        "name": "Multi-Person / Multi-Character Masking",
        "file": "10_ITEMS_P8_MULTI_PERSON_MASKING.md",
        "entry_gate": "P7 substantially complete; multi-person risk buckets/certificates remain independently gated",
    },
    "P9": {
        "name": "External Supervision, Reference Intelligence & DAZ Autonomy",
        "file": "20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md",
        "entry_gate": "foundation may proceed; training/promotion still requires qualified sources, leakage isolation, DAZ acceptance, and untouched real human-anchor evidence",
    },
}

# Hard blockers called out explicitly in Plan/Items/00_ITEMS_MASTER_INDEX.md \u00a73.
# An item is a hard blocker if its id equals one of these, or starts with
# "<prefix>." (i.e. is a sub-item of a blocker cluster).
HARD_BLOCKER_PREFIXES = [
    "MF-P0-07",  # doctor green
    "MF-P1-03",  # ontology.yaml CI assert
    "MF-P1-07",  # format-QC BLOCK enforcement
    "MF-P4-05",  # VLM calibration gate
    "MF-P5-02.02",  # flip / swap_partner CI test
    "MF-P5-05.04",  # D7 gate (finger mIoU)
    "MF-P5-07.02",  # D6 gate (champion beats draft pipeline)
    "MF-P8-05.01",  # QC-035 instance silhouette exclusivity (doc 17)
    "MF-P8-05.02",  # QC-036 cross-instance bleed (doc 17)
    "MF-P8-07",  # multi-person dataset split-integrity CI test (doc 17 \u00a78)
    "MF-P9-11.01",  # DAZ dataset builder authority/share enforcement
    "MF-P9-11.02",  # independent DAZ launcher authority/share enforcement
    "MF-P9-13.02",  # external labels remain train-only weighted pseudo labels
    "MF-P9-14.07",  # benchmark/reference leakage isolation
    "MF-P9-15.02",  # zero bleed/swap/format target
]

# Conditional items — may legitimately resolve to not_applicable if their
# trigger never fires (Items/00 master index rule #6).
CONDITIONAL_IDS = {
    "MF-P5-08.01",
    "MF-P5-08.02",
    "MF-P7-01.04",
    "MF-P7-03.05",
}

# ---------------------------------------------------------------------------
# Definition of Done — doc 00 §4 (D1-D11). Status is AUTO-COMPUTED at report
# time from the status of each entry's driving item(s) — never set directly.
# If a computed status looks wrong, the fix is to adjust `driven_by` here,
# not to hand-edit a status value anywhere.
# ---------------------------------------------------------------------------
DOD = {
    "D1": {
        "text": "A new image can be processed with one CLI command to every indexed PART "
        "draft in the active production ontology; the expanded project requires gated v2 activation.",
        "driven_by": ["MF-P2-08.04", "MF-P7-06.06"],
    },
    "D2": {
        "text": "Human-anchor and certificate-covered autonomous finalization flows preserve "
        "explicit truth authority and produce immutable QA-passing packages; residual/audit CVAT "
        "routing remains reversible.",
        "driven_by": ["MF-P1-07.05", "MF-P1-08.04", "MF-P1-13.07", "MF-P1-13.08"],
    },
    "D3": {
        "text": "Auto-QA battery (34 checks) runs on every package and blocks bad "
        "gold automatically.",
        "driven_by": [
            "MF-P1-07.01",
            "MF-P1-07.02",
            "MF-P1-07.03",
            "MF-P2-07.03",
            "MF-P2-07.04",
            "MF-P3-06.08",
            "MF-P4-09.01",
        ],
    },
    "D4": {
        "text": "Local/cloud QA, autonomous repair, selective certification, residual routing, "
        "mixed auditing, and revocation pass frozen human-anchor gates.",
        "driven_by": ["MF-P4-EXIT", "MF-P4-10.09", "MF-P4-11.15"],
    },
    "D5": {
        "text": "\u2265300 certified packages exist with tier-separated authority, full manifests, "
        "active certificates where required, hashes, and coverage matrix \u226580% cell coverage.",
        "driven_by": ["MF-P5-10.05", "MF-P7-01.01", "MF-P7-01.02"],
    },
    "D6": {
        "text": "Custom fine-tuned body-part model beats the SAM2+priors draft "
        "pipeline on the frozen test holdout for mean per-part IoU and "
        "boundary F-score, per the leaderboard.",
        "driven_by": ["MF-P5-07.02", "MF-P5-10.09", "MF-P5-10.11"],
    },
    "D7": {
        "text": "Hand/finger specialist model achieves finger-class mean IoU "
        "\u2265 0.70 on hand-crop holdout.",
        "driven_by": ["MF-P5-05.04"],
    },
    "D8": {
        "text": "ComfyUI node pack loads gold/predicted masks and produces derived "
        "inpaint masks inside a workflow.",
        "driven_by": ["MF-P6-03.03", "MF-P6-06.08", "MF-P6-EXIT"],
    },
    "D9": {
        "text": "Full environment is reproducible from env\\ lockfiles + "
        "models\\model_registry.json on a clean machine.",
        "driven_by": [
            "MF-P0-02.08",
            "MF-P0-02.09",
            "MF-P0-06.01",
            "MF-P0-16.12",
            "MF-P0-17.04",
            "MF-P0-EXIT",
        ],
    },
    "D10": {
        "text": "Runbook operations (backup, retrain, failure mining) each executed "
        "successfully at least once.",
        "driven_by": ["MF-P7-03.06", "MF-P7-07.09"],
    },
    "D11": {
        "text": "A photo containing 2 to max_instances_per_image people produces "
        "correctly-instanced, non-cross-bleeding, QA-passing gold packages for "
        "every promoted person, with interperson contact/occlusion correctly "
        "and reciprocally handled (doc 17).",
        "driven_by": ["MF-P8-10.05", "MF-P8-11.07", "MF-P8-11.08", "MF-P8-EXIT"],
    },
}

# ---------------------------------------------------------------------------
# Measurable Goals — doc 01 §3 (G1-G9). These are continuous/measured metrics
# that cannot be inferred from checklist completion alone; record them with
# `tracker.py goal <Gid> --measured "..." --status {pending,met,not_met}`.
# ---------------------------------------------------------------------------
GOALS = {
    "G1": {
        "text": "Human labor: touches/100 images, audited/residual fractions, changed pixels/100k; review minutes secondary",
        "target": "zero-touch \u22650.95, routine human touch \u22640.05, manual pixel edit fraction \u22640.01",
        "driven_by": ["MF-P3-07.03", "MF-P5-07.03", "MF-P7-07.05", "MF-P7-07.08", "MF-P9-15.03"],
    },
    "G2": {
        "text": "Draft quality (mean per-part IoU against image-disjoint human-anchor truth)",
        "target": "\u22650.85 body, \u22650.70 fingers/toes",
        "driven_by": ["MF-P2-08.03", "MF-P5-07.03", "MF-P9-15.01"],
    },
    "G3": {
        "text": "Boundary quality (boundary F-score @2px tolerance)",
        "target": "\u22650.80 body, \u22650.65 fingers/hair",
        "driven_by": ["MF-P5-07.03", "MF-P9-15.01"],
    },
    "G4": {
        "text": "Format integrity (human-anchor and autonomous-certified packages passing all checks)",
        "target": "100% (hard gate)",
        "driven_by": ["MF-P1-07.05"],
    },
    "G5": {
        "text": "Left/right correctness (L/R swaps in certified and human-anchor audits)",
        "target": "0 (hard gate via QC-014 + review)",
        "driven_by": ["MF-P2-07.03", "MF-P3-05.03"],
    },
    "G6": {
        "text": "Dataset scale (certified packages, truth tiers reported separately)",
        "target": "300 certified minimum, 500 target; pseudo-labels excluded",
        "driven_by": ["MF-P7-01.01", "MF-P7-01.03"],
    },
    "G7": {
        "text": "Custom model role win with every hard/high-risk bucket non-inferior",
        "target": "Primary win/labor reduction on frozen human-anchor holdout with no hard-bucket regression",
        "driven_by": ["MF-P5-07.02", "MF-P5-10.09", "MF-P5-10.11"],
    },
    "G8": {
        "text": "Reproducibility (rebuild env + rerun pipeline -> byte-identical maps)",
        "target": "Yes (seeded)",
        "driven_by": ["MF-P2-06.07", "MF-P5-01.04"],
    },
    "G9": {
        "text": "Multi-person correctness (cross-instance bleed in certified/human-anchor audits, doc 17)",
        "target": "0 (hard gate via QC-035/036, selective audit, and revocation)",
        "driven_by": ["MF-P8-05.01", "MF-P8-05.02", "MF-P8-10.05", "MF-P8-11.07"],
    },
}

# ---------------------------------------------------------------------------
# Parsing Plan\Items\*.md into item metadata
# ---------------------------------------------------------------------------
CLUSTER_RE = re.compile(
    r"^## (?:(?P<id>MF-[A-Za-z0-9.\-]+) \u2014 (?P<title>.+?)\s*\(spec:\s*(?P<spec>[^)]+)\)"
    r"|(?P<exit>P\d+ Exit Gate))\s*$"
)
ITEM_RE = re.compile(r"^- \[[ xX]\] (?P<id>MF-[A-Za-z0-9.\-]+)\s+(?P<desc>.+?)\s*$")


def is_hard_blocker(item_id):
    return any(item_id == p or item_id.startswith(p + ".") for p in HARD_BLOCKER_PREFIXES)


def parse_items_files():
    """Parse Plan\\Items\\0N_ITEMS_P*.md files into a dict of id -> metadata.
    The master index (00_ITEMS_MASTER_INDEX.md) is prose/tables and is
    skipped automatically (its filename doesn't match the phase pattern)."""
    items = {}
    for fname in sorted(ITEMS_DIR.glob("*_ITEMS_*.md")):
        phase_match = re.search(r"_ITEMS_(P\d+)_", fname.name)
        if not phase_match:
            continue
        phase = phase_match.group(1)
        cluster_id = cluster_title = cluster_spec = None
        text = fname.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            cm = CLUSTER_RE.match(stripped)
            if cm:
                if cm.group("exit"):
                    cluster_id, cluster_title, cluster_spec = "EXIT", "Phase Exit Gate", None
                else:
                    cluster_id = cm.group("id")
                    cluster_title = cm.group("title")
                    cluster_spec = cm.group("spec")
                continue
            im = ITEM_RE.match(stripped)
            if im:
                item_id = im.group("id")
                if item_id in items:
                    raise ValueError(f"Duplicate id {item_id} found again in {fname.name}:{lineno}")
                items[item_id] = {
                    "id": item_id,
                    "phase": phase,
                    "cluster_id": cluster_id,
                    "cluster_title": cluster_title,
                    "spec_ref": cluster_spec,
                    "description": im.group("desc"),
                    "source_file": fname.name,
                    "source_line": lineno,
                    "is_exit_gate": cluster_id == "EXIT",
                    "hard_blocker": is_hard_blocker(item_id)
                    or "HARD BLOCKER" in im.group("desc").upper(),
                    "conditional": item_id in CONDITIONAL_IDS,
                }
    return items


# ---------------------------------------------------------------------------
# tracker.json state I/O
# ---------------------------------------------------------------------------
def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state(now):
    return {
        "status": "open",
        "percent_complete": 0,
        "notes": [],
        "evidence": None,
        "blocked_reason": None,
        "created_at": now,
        "updated_at": now,
        "orphaned": False,
    }


def load_tracker():
    if TRACKER_JSON.exists():
        return json.loads(TRACKER_JSON.read_text(encoding="utf-8"))
    return None


def load_tracker_or_exit():
    data = load_tracker()
    if data is None:
        sys.exit("tracker.json not found. Run first: python tracker.py rebuild")
    return data


def save_tracker(data):
    ROOT.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    if TRACKER_JSON.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(TRACKER_JSON, BACKUPS_DIR / f"tracker_{ts}.json")
    tmp = TRACKER_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # Windows can transiently hold a lock on the destination (AV scan, indexer,
    # another process/session reading tracker.json at the same moment) right as
    # we try to replace it. Retry with backoff rather than treating a
    # split-second race as a hard failure -- this file may be shared with
    # another concurrently-running session.
    last_err = None
    for attempt in range(6):
        try:
            tmp.replace(TRACKER_JSON)
            last_err = None
            break
        except PermissionError as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    if last_err is not None:
        # os.replace() over an existing file can be denied *indefinitely* (not
        # just transiently) when another process holds a persistent
        # share-delete handle on tracker.json -- e.g. a sibling session's
        # Electron/node service that opened the file and leaked the handle.
        # Windows still permits a plain rename of that held file to a fresh
        # name, so fall back to rename-aside: move the held current file to an
        # orphan name (the stale handle follows it there) and move the freshly
        # written temp into the now-free tracker.json name. The live file
        # becomes a brand-new, unheld object; subsequent saves work normally.
        try:
            if TRACKER_JSON.exists():
                orphan = TRACKER_JSON.with_suffix(".json.orphan")
                i = 0
                while orphan.exists():
                    i += 1
                    orphan = TRACKER_JSON.with_suffix(f".json.orphan{i}")
                TRACKER_JSON.rename(orphan)
                tmp.rename(TRACKER_JSON)
                try:
                    orphan.unlink()
                except OSError:
                    pass  # orphan may still be held; harmless leftover
            else:
                tmp.rename(TRACKER_JSON)
            last_err = None
        except OSError as e2:
            last_err = e2
    if last_err is not None:
        raise last_err


def append_changelog(entry):
    CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
    with CHANGELOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def tail_changelog(n):
    if not CHANGELOG.exists():
        return []
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Commands: rebuild, show, set
# ---------------------------------------------------------------------------
def cmd_rebuild(args):
    now = iso_now()
    parsed = parse_items_files()
    existing = load_tracker()
    old_items = existing["items"] if existing else {}

    new_items = {}
    added, removed, kept = [], [], []
    state_keys = [
        "status",
        "percent_complete",
        "notes",
        "evidence",
        "blocked_reason",
        "created_at",
        "updated_at",
    ]

    for iid, meta in parsed.items():
        if iid in old_items:
            state = {k: old_items[iid].get(k) for k in state_keys}
            if state.get("status") is None:
                state = default_state(now)
            kept.append(iid)
        else:
            state = default_state(now)
            added.append(iid)
        rec = {**meta, **state, "orphaned": False}
        new_items[iid] = rec

    for iid in old_items:
        if iid not in parsed:
            rec = dict(old_items[iid])
            rec["orphaned"] = True
            new_items[iid] = rec
            removed.append(iid)

    data = {
        "meta": {
            "schema_version": "1.0.0",
            "generated_at": now,
            "generator": "tracker.py rebuild",
            "total_items": len(parsed),
            "total_tracked_including_orphaned": len(new_items),
        },
        "phase_meta": PHASE_META,
        "hard_blocker_prefixes": HARD_BLOCKER_PREFIXES,
        "metrics": {
            **DEFAULT_METRICS,
            **{
                key: value
                for key, value in (existing or {}).get("metrics", {}).items()
                if key
                not in {
                    "target_gold_p5_entry",
                    "target_gold_d5",
                    "target_gold_g6_stretch",
                    "effective_training_truth_count",
                }
            },
        },
        "dod": (existing or {}).get("dod") or {k: {} for k in DOD},
        "goals": (existing or {}).get("goals")
        or {k: {"status": "pending", "measured": None, "updated_at": None} for k in GOALS},
        "items": new_items,
    }
    save_tracker(data)
    print(
        f"Rebuilt tracker: {len(parsed)} items parsed "
        f"({len(added)} new, {len(kept)} kept, {len(removed)} orphaned)."
    )
    if added:
        print("  New ids:", ", ".join(added))
    if removed:
        print("  Orphaned (state preserved, no longer in source):", ", ".join(removed))


def cmd_show(args):
    data = load_tracker_or_exit()
    it = data["items"].get(args.id)
    if not it:
        sys.exit(f"Unknown item id: {args.id}")
    print(json.dumps(it, indent=2, ensure_ascii=False))


def cmd_set(args):
    data = load_tracker_or_exit()
    if args.id not in data["items"]:
        sys.exit(f"Unknown item id: {args.id}. Use `tracker.py list` to find valid ids.")
    rec = data["items"][args.id]

    if not any(
        [args.status, args.note, args.evidence, args.percent is not None, args.blocked_reason]
    ):
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        print(
            "\n(no changes specified -- showing current record; pass --status / "
            "--note / --evidence / --percent / --blocked-reason to update it)"
        )
        return

    old_status = rec["status"]
    now = iso_now()

    if args.status:
        if args.status not in STATUSES:
            sys.exit(f"Invalid status '{args.status}'. Must be one of: {', '.join(STATUSES)}")
        if args.status == "complete" and not args.evidence and not rec.get("evidence"):
            sys.exit(
                "Refusing to mark complete without --evidence "
                "(what proves the item's verify clause passed?)."
            )
        if args.status == "blocked" and not args.blocked_reason and not rec.get("blocked_reason"):
            sys.exit("Refusing to mark blocked without --blocked-reason.")
        rec["status"] = args.status
        if args.status != "blocked":
            rec["blocked_reason"] = None
        if args.status in ("complete", "not_applicable"):
            rec["percent_complete"] = 100
        elif args.status == "open":
            rec["percent_complete"] = 0

    if args.percent is not None:
        if not (0 <= args.percent <= 100):
            sys.exit("--percent must be between 0 and 100")
        rec["percent_complete"] = args.percent

    if args.evidence:
        rec["evidence"] = args.evidence
    if args.blocked_reason:
        rec["blocked_reason"] = args.blocked_reason
        if rec["status"] != "blocked":
            print(f"Note: --blocked-reason set but status is '{rec['status']}', not 'blocked'.")
    if args.note:
        rec.setdefault("notes", []).append({"ts": now, "actor": args.actor, "text": args.note})

    rec["updated_at"] = now
    save_tracker(data)
    append_changelog(
        {
            "ts": now,
            "id": args.id,
            "actor": args.actor,
            "old_status": old_status,
            "new_status": rec["status"],
            "percent_complete": rec["percent_complete"],
            "note": args.note,
            "evidence": args.evidence,
            "blocked_reason": args.blocked_reason,
        }
    )
    pct = f" ({rec['percent_complete']}%)" if rec["percent_complete"] else ""
    print(f"{args.id}: {old_status} -> {rec['status']}{pct}")


# ---------------------------------------------------------------------------
# Commands: list, next, metrics, goal, validate
# ---------------------------------------------------------------------------
def cmd_list(args):
    data = load_tracker_or_exit()
    rows = []
    wanted_statuses = None
    if args.status:
        wanted_statuses = {s.strip() for s in args.status.split(",")}
    for it in data["items"].values():
        if args.phase and it["phase"] != args.phase:
            continue
        if wanted_statuses and it["status"] not in wanted_statuses:
            continue
        if args.hard_blockers and not it["hard_blocker"]:
            continue
        if args.conditional and not it["conditional"]:
            continue
        if args.blocked and it["status"] != "blocked":
            continue
        if args.search:
            needle = args.search.lower()
            if needle not in it["description"].lower() and needle not in it["id"].lower():
                continue
        rows.append(it)
    rows.sort(key=lambda r: (r["phase"], r["source_line"]))
    if not rows:
        print("No matching items.")
        return
    for it in rows:
        glyph = STATUS_GLYPH.get(it["status"], "?")
        pct = f"/{it['percent_complete']}%" if it["percent_complete"] not in (0, 100) else ""
        hb = " (HARD BLOCKER)" if it["hard_blocker"] else ""
        extra = ""
        if it["status"] == "blocked" and it.get("blocked_reason"):
            extra = f"  [BLOCKED: {it['blocked_reason']}]"
        desc = it["description"]
        if len(desc) > 100:
            desc = desc[:97] + "..."
        print(f"{glyph} {it['id']:<16} [{it['status']}{pct}] {desc}{hb}{extra}")
    print(f"\n{len(rows)} item(s).")


def suggest_next(data, n, phase=None):
    items = [it for it in data["items"].values() if not it["orphaned"]]
    items.sort(
        key=lambda r: (
            PHASE_ORDER.index(r["phase"]) if r["phase"] in PHASE_ORDER else 99,
            r["source_line"],
        )
    )
    cands = [
        it
        for it in items
        if it["status"] in ("open", "in_progress", "partially_complete", "failed")
    ]
    if phase:
        cands = [it for it in cands if it["phase"] == phase]
    return cands[:n]


def cmd_next(args):
    data = load_tracker_or_exit()
    cands = suggest_next(data, args.count, args.phase)
    if not cands:
        print("Nothing actionable found (everything complete/blocked/n-a in scope?).")
        return
    for it in cands:
        glyph = STATUS_GLYPH.get(it["status"], "?")
        hb = " (HARD BLOCKER)" if it["hard_blocker"] else ""
        print(f"{glyph} {it['id']:<16} [{it['phase']}] {it['description']}{hb}")


def cmd_metrics(args):
    data = load_tracker_or_exit()
    changed = False
    if args.set:
        for kv in args.set:
            if "=" not in kv:
                sys.exit(f"--set expects key=value, got: {kv}")
            k, v = kv.split("=", 1)
            raw = v.strip()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            if isinstance(value, (dict, list)):
                sys.exit("metric values must be scalar JSON values or strings")
            data["metrics"][k.strip()] = value
            changed = True
    if changed:
        try:
            data["metrics"]["certified_training_package_count"] = int(
                data["metrics"]["human_anchor_train_count"]
            ) + int(data["metrics"]["autonomous_certified_gold_count"])
        except (KeyError, TypeError, ValueError):
            sys.exit(
                "human_anchor_train_count and autonomous_certified_gold_count "
                "must be integer-compatible"
            )
        save_tracker(data)
        append_changelog({"ts": iso_now(), "metrics_update": data["metrics"]})
    if args.show or not args.set:
        print(json.dumps(data["metrics"], indent=2))


def cmd_goal(args):
    data = load_tracker_or_exit()
    if args.gid not in data["goals"]:
        sys.exit(f"Unknown goal id '{args.gid}'. Valid: {', '.join(sorted(data['goals']))}")
    g = data["goals"][args.gid]
    now = iso_now()
    if args.measured is not None:
        g["measured"] = args.measured
    if args.status:
        if args.status not in ("pending", "met", "not_met"):
            sys.exit("--status must be one of: pending, met, not_met")
        g["status"] = args.status
    g["updated_at"] = now
    save_tracker(data)
    append_changelog(
        {"ts": now, "goal": args.gid, "measured": args.measured, "status": args.status}
    )
    print(f"{args.gid}: status={g.get('status')} measured={g.get('measured')}")


def cmd_validate(args):
    data = load_tracker_or_exit()
    problems, warnings = [], []
    items = data["items"]
    total = sum(1 for it in items.values() if not it["orphaned"])
    if total != EXPECTED_ITEM_COUNT:
        warnings.append(
            f"Expected {EXPECTED_ITEM_COUNT} non-orphaned items, found {total}. "
            f"Fine if Items/*.md were intentionally edited and `rebuild` was rerun."
        )
    metrics = data.get("metrics", {})
    missing_metrics = sorted(set(DEFAULT_METRICS).difference(metrics))
    if missing_metrics:
        problems.append("missing required metrics: " + ", ".join(missing_metrics))
    try:
        expected_certified_count = int(metrics["human_anchor_train_count"]) + int(
            metrics["autonomous_certified_gold_count"]
        )
        actual_certified_count = int(metrics["certified_training_package_count"])
        if actual_certified_count != expected_certified_count:
            problems.append(
                "certified_training_package_count must equal "
                "human_anchor_train_count + autonomous_certified_gold_count "
                f"({actual_certified_count} != {expected_certified_count})"
            )
    except (KeyError, TypeError, ValueError):
        problems.append("certified training count metrics must be integer-compatible")
    ids_seen = set()
    for iid, it in items.items():
        if iid in ids_seen:
            problems.append(f"{iid}: duplicate key in tracker.json")
        ids_seen.add(iid)
        if it["status"] not in STATUSES:
            problems.append(f"{iid}: invalid status '{it['status']}'")
        if it["status"] == "complete" and not it.get("evidence"):
            warnings.append(f"{iid}: marked complete without evidence recorded")
        if it["status"] == "blocked" and not it.get("blocked_reason"):
            warnings.append(f"{iid}: marked blocked without a reason recorded")
        if it["orphaned"]:
            warnings.append(f"{iid}: orphaned (no longer present in source Items/*.md)")
    hard_open = [
        iid for iid, it in items.items() if it["hard_blocker"] and it["status"] not in DONE_STATUSES
    ]
    print(f"Total tracked items (non-orphaned): {total}")
    print(f"Hard-blocker items not yet resolved: {len(hard_open)}")
    if problems:
        print(f"\nFAIL -- {len(problems)} structural problem(s):")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nNo structural problems found.")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
    sys.exit(1 if problems else 0)


# ---------------------------------------------------------------------------
# Reporting: DASHBOARD.md + phases/*.md (auto-generated from tracker.json)
# ---------------------------------------------------------------------------
def compute_dod_status(data, did):
    items = data["items"]
    statuses = []
    for iid in DOD[did]["driven_by"]:
        it = items.get(iid)
        statuses.append("missing" if it is None else it["status"])
    if all(s in DONE_STATUSES for s in statuses):
        return "complete"
    if any(s == "missing" for s in statuses):
        return "error(missing item id)"
    if any(s == "blocked" for s in statuses):
        return "blocked"
    return "open"


def phase_stats(data, phase):
    items = [it for it in data["items"].values() if it["phase"] == phase and not it["orphaned"]]
    total = len(items)
    done = sum(1 for it in items if it["status"] in DONE_STATUSES)
    blocked = sum(1 for it in items if it["status"] == "blocked")
    in_progress = sum(1 for it in items if it["status"] in ("in_progress", "partially_complete"))
    failed = sum(1 for it in items if it["status"] == "failed")
    deferred = sum(1 for it in items if it["status"] == "deferred")
    open_ = sum(1 for it in items if it["status"] == "open")
    pct = round(100 * done / total, 1) if total else 0.0
    return dict(
        total=total,
        done=done,
        blocked=blocked,
        in_progress=in_progress,
        failed=failed,
        deferred=deferred,
        open=open_,
        pct=pct,
    )


def bar(pct, width=20):
    filled = int(round(width * pct / 100))
    return "#" * filled + "-" * (width - filled)


def daz_vertical_slice_rows(data):
    """Return dashboard rows that keep implementation, execution, and acceptance distinct."""

    metrics = data.get("metrics", {})
    complete = int(metrics.get("daz_asset_identity_hashes_complete") or 0)
    total = int(metrics.get("daz_asset_identity_hashes_total") or 0)
    execution_pct = round(100 * complete / total, 1) if total else 0.0
    graph_status = str(metrics.get("daz_live_compatibility_graph_status") or "unpublished")
    qualified = int(metrics.get("daz_live_qualified_asset_count") or 0)
    certificates = int(metrics.get("daz_live_smoke_certificate_count") or 0)
    scenes = int(metrics.get("daz_live_assembled_scene_count") or 0)
    packages = int(metrics.get("daz_live_exact_synthetic_package_count") or 0)
    challengers = int(metrics.get("daz_synthetic_trained_challenger_count") or 0)
    improvement = str(
        metrics.get("daz_measured_real_image_improvement_status") or "not_measured"
    )
    free_gib = metrics.get("daz_storage_free_gib")
    floor_gib = metrics.get("daz_storage_new_work_floor_gib")
    new_work = bool(metrics.get("daz_storage_new_work_allowed"))
    free_text = "unknown" if free_gib is None else f"{float(free_gib):.3f} GiB"
    floor_text = "unknown" if floor_gib is None else f"{float(floor_gib):.1f} GiB"
    return [
        (
            "Asset identity",
            "resumable hashing and duplicate/shadow logic implemented",
            f"{complete:,}/{total:,} hashes ({execution_pct:.1f}%)",
            "incomplete" if complete < total else "complete snapshot required",
        ),
        (
            "Compatibility graph",
            "graph validation and deterministic publication implemented",
            graph_status,
            "no live graph authority" if graph_status != "published" else "published",
        ),
        (
            "Asset qualification",
            "smoke/certificate/revocation contracts fixture-tested",
            f"{qualified:,} qualified assets / {certificates:,} live certificates",
            "no live qualified authority" if not qualified or not certificates else "live authority present",
        ),
        (
            "Scene assembly",
            "recipe, formation, geometry preflight, resolved state, and pass freeze implemented",
            f"{scenes:,} live assembled scenes",
            "DAZ readback/replay evidence required" if not scenes else "live scenes present",
        ),
        (
            "Exact synthetic packages",
            "render/package contracts may be implemented independently",
            f"{packages:,} verified live packages",
            "no accepted synthetic mask package" if not packages else "verified packages present",
        ),
        (
            "Training impact",
            "training leakage/authority gates implemented",
            f"{challengers:,} synthetic-trained challengers",
            f"real-image improvement: {improvement}",
        ),
        (
            "Storage gate",
            "capacity guard implemented",
            f"{free_text} free; new-work floor {floor_text}",
            "new work allowed" if new_work else "new acquisition/major hashing/render work paused",
        ),
    ]


def render_dashboard(data):
    now = iso_now()
    all_items = [it for it in data["items"].values() if not it["orphaned"]]
    total_all = len(all_items)
    done_all = sum(1 for it in all_items if it["status"] in DONE_STATUSES)
    pct_all = round(100 * done_all / total_all, 1) if total_all else 0.0

    L = []
    L.append("# MaskFactory Project Tracker -- Dashboard")
    L.append("")
    L.append(
        "**AUTO-GENERATED by `tracker.py report` -- do not hand-edit.** "
        "Regenerate after any `set` / `metrics` / `goal` call."
    )
    L.append("")
    L.append(f"Generated: {now}")
    L.append("")
    L.append(f"## Overall Progress: {done_all}/{total_all} items ({pct_all}%)")
    L.append("")
    L.append(f"`[{bar(pct_all, 40)}]`")
    L.append("")
    L.append("| Phase | Name | Progress | Done | Blocked | In-Prog | Failed | Open | Entry Gate |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for phase in PHASE_ORDER:
        st = phase_stats(data, phase)
        meta = PHASE_META[phase]
        L.append(
            f"| {phase} | {meta['name']} | `[{bar(st['pct'])}]` {st['pct']}% | "
            f"{st['done']}/{st['total']} | {st['blocked']} | {st['in_progress']} | "
            f"{st['failed']} | {st['open']} | {meta['entry_gate'] or '(none)'} |"
        )
    L.append("")
    L.append(
        "Full item-by-item detail with live status, evidence, and notes: "
        "see `phases/<PHASE>.md`."
    )
    L.append("")

    L.append("## Live DAZ Vertical Slice")
    L.append("")
    L.append(
        "Tracker item percentages combine implementation work and live execution. "
        "This table separates **implementation readiness**, **live execution**, and "
        "**acceptance evidence** so fixture success cannot be mistaken for an operational result."
    )
    L.append("")
    L.append("| Layer | Implementation Readiness | Live Execution | Acceptance Evidence |")
    L.append("|---|---|---|---|")
    for layer, implementation, execution, acceptance in daz_vertical_slice_rows(data):
        L.append(f"| {layer} | {implementation} | {execution} | {acceptance} |")
    L.append("")
    L.append(
        "**Active priority:** complete the first live verified DAZ engineering package "
        "(`qualified real assets -> assembled Genesis 9 scene -> pristine RGB and annotation "
        "passes -> exact masks -> package verification`) before adding further downstream "
        "horizontal abstractions. Fixture-only evidence must remain partial."
    )
    L.append("")

    L.append("## Hard Blockers (cannot be skipped or overridden)")
    L.append("")
    hb_items = sorted(
        [it for it in all_items if it["hard_blocker"]],
        key=lambda r: (PHASE_ORDER.index(r["phase"]), r["source_line"]),
    )
    for it in hb_items:
        L.append(
            f"- {STATUS_GLYPH[it['status']]} `{it['id']}` [{it['status']}] {it['description']}"
        )
    L.append("")

    L.append("## Currently Blocked Items")
    L.append("")
    blocked_items = [it for it in all_items if it["status"] == "blocked"]
    if not blocked_items:
        L.append("_None currently blocked._")
    else:
        for it in sorted(blocked_items, key=lambda r: (r["phase"], r["source_line"])):
            reason = it.get("blocked_reason") or "_(no reason recorded)_"
            L.append(f"- `{it['id']}` ({it['phase']}): {it['description']}")
            L.append(f"    - **Reason:** {reason}")
    L.append("")

    L.append("## Definition of Done (doc 00 §4)")
    L.append("")
    L.append("| ID | Criterion | Status | Driven By |")
    L.append("|---|---|---|---|")
    for did in sorted(DOD, key=lambda d: int(d[1:])):
        status = compute_dod_status(data, did)
        L.append(
            f"| {did} | {DOD[did]['text']} | {status} | " f"{', '.join(DOD[did]['driven_by'])} |"
        )
    L.append("")

    L.append("## Measurable Goals (doc 01 §3)")
    L.append("")
    L.append("| ID | Goal | Target | Status | Measured |")
    L.append("|---|---|---|---|---|")
    for gid in sorted(GOALS, key=lambda g: int(g[1:])):
        g = data["goals"].get(gid, {})
        L.append(
            f"| {gid} | {GOALS[gid]['text']} | {GOALS[gid]['target']} | "
            f"{g.get('status', 'pending')} | {g.get('measured') or '(not measured)'} |"
        )
    L.append("")

    L.append("## Tracked Metrics")
    L.append("")
    for k, v in data["metrics"].items():
        L.append(f"- `{k}` = {v}")
    L.append("")

    L.append("## Recent Activity (last 15 changes)")
    L.append("")
    recent = tail_changelog(15)
    if not recent:
        L.append("_No changes recorded yet._")
    else:
        for e in reversed(recent):
            label = e.get("id") or (f"goal:{e['goal']}" if "goal" in e else "metrics")
            L.append(
                (
                    f"- `{e.get('ts', '?')}` **{label}** "
                    f"{e.get('old_status', '')} -> {e.get('new_status', '')} -- "
                    f"{e.get('note') or e.get('evidence') or e.get('blocked_reason') or ''}"
                ).rstrip()
            )
    L.append("")

    L.append("## Suggested Next Actions")
    L.append("")
    for it in suggest_next(data, 10):
        hb = " (HARD BLOCKER)" if it["hard_blocker"] else ""
        L.append(f"- `{it['id']}` ({it['phase']}): {it['description']}{hb}")
    L.append("")

    L.append("## For AI Agents")
    L.append("")
    L.append("Full command reference: `README.md` in this folder. Quick reference:")
    L.append("```")
    L.append("python tracker.py list --status open --phase P0")
    L.append('python tracker.py set MF-P0-01.01 --status complete --evidence "..."')
    L.append('python tracker.py set MF-P2-05.02 --status blocked --blocked-reason "..."')
    L.append("python tracker.py next -n 10")
    L.append("python tracker.py report")
    L.append("```")
    DASHBOARD.write_text("\n".join(L), encoding="utf-8")


def render_phase_file(data, phase):
    meta = PHASE_META[phase]
    st = phase_stats(data, phase)
    L = []
    L.append(f"# Phase {phase}: {meta['name']} -- Live Status")
    L.append("")
    L.append("**AUTO-GENERATED by `tracker.py report` from tracker.json -- do not hand-edit.**")
    L.append(
        f"Source checklist: `Plan/Items/{meta['file']}` | Entry gate: {meta['entry_gate'] or 'none'}"
    )
    L.append("")
    L.append(
        f"**Progress: {st['done']}/{st['total']} ({st['pct']}%)** -- "
        f"blocked {st['blocked']} | in progress {st['in_progress']} | "
        f"failed {st['failed']} | deferred {st['deferred']} | open {st['open']}"
    )
    L.append("")
    items = sorted(
        [it for it in data["items"].values() if it["phase"] == phase and not it["orphaned"]],
        key=lambda r: r["source_line"],
    )
    last_cluster = None
    for it in items:
        if it["cluster_id"] != last_cluster:
            last_cluster = it["cluster_id"]
            if it["is_exit_gate"]:
                L.append("\n### Phase Exit Gate\n")
            else:
                L.append(
                    f"\n### {it['cluster_id']} \u2014 {it['cluster_title']} "
                    f"(spec: {it['spec_ref']})\n"
                )
        glyph = STATUS_GLYPH.get(it["status"], "?")
        hb = " **[HARD BLOCKER]**" if it["hard_blocker"] else ""
        cond = " _(conditional)_" if it["conditional"] else ""
        pct = f" -- {it['percent_complete']}%" if it["percent_complete"] not in (0, 100) else ""
        L.append(f"- {glyph} **{it['id']}**{pct}{hb}{cond} -- {it['description']}")
        if it["status"] == "blocked" and it.get("blocked_reason"):
            L.append(f"    - Blocked: {it['blocked_reason']}")
        if it.get("evidence"):
            L.append(f"    - Evidence: {it['evidence']}")
        for note in (it.get("notes") or [])[-3:]:
            L.append(f"    - Note ({note['ts']}, {note['actor']}): {note['text']}")
    (PHASES_DIR / f"{phase}.md").write_text("\n".join(L), encoding="utf-8")


def cmd_report(args):
    data = load_tracker_or_exit()
    PHASES_DIR.mkdir(parents=True, exist_ok=True)
    render_dashboard(data)
    for phase in PHASE_ORDER:
        render_phase_file(data, phase)
    print(f"Report generated: {DASHBOARD}")
    print(f"Phase files ({len(PHASE_ORDER)}) in: {PHASES_DIR}")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="tracker.py",
        description="MaskFactory project tracker -- 609 build items + DoD/Goals rollups.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "rebuild", help="(Re)parse Plan/Items/*.md into tracker.json, preserving state"
    )
    sp.set_defaults(func=cmd_rebuild)

    sp = sub.add_parser("show", help="Show the full JSON record for one item id")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("set", help="Update an item's status / progress / evidence / notes")
    sp.add_argument("id")
    sp.add_argument("--status", choices=STATUSES)
    sp.add_argument("--note", help="Free-text note, appended to the item's note history")
    sp.add_argument(
        "--evidence", help="What proves the verify clause passed (required for complete)"
    )
    sp.add_argument("--percent", type=int, help="0-100 progress override")
    sp.add_argument("--blocked-reason", help="Why the item is blocked (required for blocked)")
    sp.add_argument("--actor", default="ai_agent", help="Who made this change (default: ai_agent)")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("list", help="List / filter items")
    sp.add_argument("--phase", choices=PHASE_ORDER)
    sp.add_argument("--status", help="comma-separated list of statuses, e.g. open,blocked")
    sp.add_argument("--hard-blockers", action="store_true", dest="hard_blockers")
    sp.add_argument("--conditional", action="store_true")
    sp.add_argument("--blocked", action="store_true")
    sp.add_argument("--search", help="case-insensitive substring match on id or description")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("next", help="Suggest next actionable items, in phase/document order")
    sp.add_argument("-n", "--count", type=int, default=10)
    sp.add_argument("--phase", choices=PHASE_ORDER)
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser("metrics", help="View / update free-form tracked metrics")
    sp.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="repeatable, e.g. --set approved_gold_count=42",
    )
    sp.add_argument("--show", action="store_true")
    sp.set_defaults(func=cmd_metrics)

    sp = sub.add_parser("goal", help="Record a measured value / status for a G1-G9 goal")
    sp.add_argument("gid", help="e.g. G2")
    sp.add_argument("--measured", help="free text, e.g. '0.87 body / 0.71 fingers'")
    sp.add_argument("--status", choices=["pending", "met", "not_met"])
    sp.set_defaults(func=cmd_goal)

    sp = sub.add_parser("validate", help="Run consistency checks against tracker.json")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("report", help="Regenerate DASHBOARD.md and phases/*.md from tracker.json")
    sp.set_defaults(func=cmd_report)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
