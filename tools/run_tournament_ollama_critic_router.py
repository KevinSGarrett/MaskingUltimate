#!/usr/bin/env python3
"""Tournament Ollama STRICT visual critic router (self-hosted, fail-closed).

Lane: advisory + mandatory gate evidence for MVC residual / promotion paths.
Does NOT author masks, approve gold, or clear hard QC BLOCK.

High-end primary (llava:13b) + qwen2.5vl:7b ensemble per configs/vlm.yaml
strict_visual_gate. --skip-vlm is VISUAL_CRITIC_BLOCKED (never a pass).

Usage:
  python tools/run_tournament_ollama_critic_router.py \\
      --machine-root runs/hand_tournament_full120 \\
      --label hand --limit 4 \\
      --output qa/live_verification/tournament_ollama_critic_router_<ts>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import read_mask  # noqa: E402
from maskfactory.qa.panels import render_boundary_panel  # noqa: E402
from maskfactory.vlm.strict_gate import (  # noqa: E402
    StrictVlmGateError,
    load_strict_gate_config,
    run_strict_visual_review,
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _discover_mvc(roots: list[Path], label: str | None) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        for path in sorted(root.rglob("autonomy/*.json")):
            if path.name.endswith(".corpus_record.json"):
                continue
            if path.name.endswith(".visual_hard_qa.json"):
                continue
            if path.name.endswith(".strict_vlm_gate.json"):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if doc.get("status") != "machine_verified_candidate":
                continue
            if label and str(doc.get("label") or "") != label:
                continue
            paths.append(path)
    return paths


def _resolve_source(lifecycle: dict[str, Any], stage: Path) -> Path | None:
    for key in ("source_path", "source_image_path", "image_path"):
        rel = lifecycle.get(key)
        if isinstance(rel, str) and rel:
            cand = Path(rel)
            if not cand.is_absolute():
                cand = (stage / rel).resolve()
            if cand.is_file():
                return cand
    # common tournament layout
    for pattern in ("_input/*.png", "_input/*.jpg", "source.*", "input.*"):
        hits = list(stage.glob(pattern))
        if hits:
            return hits[0]
    return None


def _review_one(
    lifecycle_path: Path,
    *,
    apply_sidecar: bool,
    skip_vlm: bool,
    force_disable_critic: bool,
) -> dict[str, Any]:
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    stage = lifecycle_path.parent.parent
    image_id = str(lifecycle.get("image_id") or "")
    label = str(lifecycle.get("label") or "unknown")
    row: dict[str, Any] = {
        "image_id": image_id,
        "label": label,
        "lifecycle_path": str(lifecycle_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "prior_status": lifecycle.get("status"),
    }
    mask_rel = lifecycle.get("winner_mask_path")
    if not isinstance(mask_rel, str) or not mask_rel:
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "missing_winner_mask_path"
        return row
    mask_path = (stage / mask_rel).resolve()
    if not mask_path.is_file():
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "winner_mask_missing"
        return row
    source = _resolve_source(lifecycle, stage)
    if source is None or not source.is_file():
        row["outcome"] = "VISUAL_CRITIC_BLOCKED"
        row["blocker"] = "source_unresolved_panels_required"
        row["note"] = "Panels require source+mask+overlay; cannot blind-approve."
        return row

    mask = (read_mask(mask_path) > 0).astype(bool)
    src_img = Image.open(source).convert("RGB")
    if src_img.size != (mask.shape[1], mask.shape[0]):
        src_img = src_img.resize((mask.shape[1], mask.shape[0]), Image.Resampling.BILINEAR)
        row["source_resized_to_mask_for_panel"] = True
    panel_path = stage / "qa_panels" / f"{label}_strict_gate_panel.png"
    render_boundary_panel(src_img, mask, np.zeros(mask.shape, dtype=bool), panel_path)
    row["panel_path"] = str(panel_path.relative_to(REPO_ROOT)).replace("\\", "/")
    row["panel_sha256"] = sha256_file(panel_path)

    result = run_strict_visual_review(
        repo_root=REPO_ROOT,
        panel_png=panel_path,
        label=label,
        context=str(lifecycle.get("instance_context") or lifecycle.get("context") or "solo"),
        skip_vlm=skip_vlm,
        force_disable_critic=force_disable_critic,
    )
    row.update(result.to_dict())
    if apply_sidecar:
        sidecar = lifecycle_path.with_name(f"{label}.strict_vlm_gate.json")
        sidecar.write_text(
            json.dumps(
                {
                    "artifact_type": "tournament_strict_vlm_gate_item",
                    "schema_version": "1.0.0",
                    "recorded_at": _now(),
                    "image_id": image_id,
                    "label": label,
                    "result": result.to_dict(),
                    "authoritative_human_gold": False,
                    "autonomous_certified_gold": False,
                    "may_approve_gold": False,
                    "may_clear_blocks": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        row["sidecar"] = str(sidecar.relative_to(REPO_ROOT)).replace("\\", "/")
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-root", action="append", type=Path, required=True)
    parser.add_argument("--label", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--write-sidecars",
        action="store_true",
        help="Persist per-item *.strict_vlm_gate.json next to lifecycle.",
    )
    parser.add_argument(
        "--skip-vlm",
        action="store_true",
        help="Must fail-closed as VISUAL_CRITIC_BLOCKED under strict gate.",
    )
    parser.add_argument(
        "--force-disable-critic",
        action="store_true",
        help="Prove fail-closed when critic explicitly disabled.",
    )
    args = parser.parse_args()

    try:
        cfg = load_strict_gate_config(REPO_ROOT)
        cfg_status = {
            "enabled": cfg.enabled,
            "primary_vlm": cfg.primary_vlm,
            "secondary_ensemble_vlm": cfg.secondary_ensemble_vlm,
            "allow_skip_vlm": cfg.allow_skip_vlm,
            "require_ensemble_for_pass": cfg.require_ensemble_for_pass,
        }
    except StrictVlmGateError as exc:
        evidence = {
            "artifact_type": "tournament_ollama_critic_router",
            "schema_version": "1.0.0",
            "recorded_at": _now(),
            "outcome": "VISUAL_CRITIC_BLOCKED",
            "blocker": str(exc),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(evidence, indent=2))
        return 2

    roots = [(REPO_ROOT / p if not p.is_absolute() else p).resolve() for p in args.machine_root]
    paths = _discover_mvc(roots, args.label)
    if args.limit and len(paths) > args.limit:
        paths = paths[: args.limit]

    rows = [
        _review_one(
            path,
            apply_sidecar=bool(args.write_sidecars),
            skip_vlm=bool(args.skip_vlm),
            force_disable_critic=bool(args.force_disable_critic),
        )
        for path in paths
    ]
    outcomes = Counter(r.get("outcome") for r in rows)
    evidence: dict[str, Any] = {
        "artifact_type": "tournament_ollama_critic_router",
        "schema_version": "1.0.0",
        "recorded_at": _now(),
        "lane": "STRICT_self_hosted_high_end_vlm_critic",
        "config": cfg_status,
        "authority": [
            "configs/vlm.yaml#strict_visual_gate",
            "src/maskfactory/vlm/strict_gate.py",
            "Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md § SELF-HOSTED STRICT VLM GATE",
        ],
        "governance": {
            "role": "qa_router_only",
            "may_author_masks": False,
            "may_approve_gold": False,
            "may_clear_blocks": False,
            "cloud_llm_forbidden_for_mf_vlm_qa": True,
        },
        "machine_roots": [str(r) for r in roots],
        "reviewed_n": len(rows),
        "outcomes": dict(outcomes),
        "rows": rows,
        "honesty": [
            "Not gold; not CAA mint authority by itself",
            "VLM FAIL/uncertain/blocked never promotes",
            "Hard QC BLOCK cannot be cleared by this router",
        ],
    }
    text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    latest = args.output.parent / "tournament_ollama_critic_router_latest.json"
    latest.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "outcomes": dict(outcomes)}, indent=2))
    if any(o in {"VISUAL_CRITIC_BLOCKED"} for o in outcomes) and args.force_disable_critic:
        return 0  # expected blocked
    if outcomes.get("STRICT_VISUAL_QA_PASS_BOUNDED", 0) == 0 and rows and not args.skip_vlm:
        # Not a hard process failure — honest abstain/block is valid.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
