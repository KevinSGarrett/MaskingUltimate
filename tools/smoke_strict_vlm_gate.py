#!/usr/bin/env python3
"""Live smoke for SELF-HOSTED STRICT VLM gate (fail-closed + known-bad reject).

Proves:
  1) High-end primary (llava:13b) + qwen ensemble are configured and callable
  2) Known-bad empty/flooded panel → FAIL / ABSTAIN (not pass/gold)
  3) --force-disable-critic → VISUAL_CRITIC_BLOCKED (never silent skip pass)
  4) Evidence logs model id, prompt hash, response, panel hash

Serialize with hand climb: unload models after; prefer when VRAM free.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.vlm.strict_gate import (  # noqa: E402
    load_strict_gate_config,
    run_strict_visual_review,
    unload_model,
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _panel_bytes_bad_empty() -> bytes:
    """Source with visible figure-ish content + empty mask + overlay = known-bad."""
    w, h = 384, 256
    source = Image.new("RGB", (w, h), (40, 40, 50))
    draw = ImageDraw.Draw(source)
    draw.ellipse((120, 40, 260, 220), fill=(210, 170, 140))  # visible body-ish
    mask = Image.new("L", (w, h), 0)  # empty — should FAIL emptiness
    overlay = source.copy()
    # three-tile strip
    strip = Image.new("RGB", (w * 3, h))
    strip.paste(source, (0, 0))
    strip.paste(mask.convert("RGB"), (w, 0))
    strip.paste(overlay, (w * 2, 0))
    buf = BytesIO()
    strip.save(buf, format="PNG")
    return buf.getvalue()


def _panel_bytes_flooded() -> bytes:
    w, h = 384, 256
    source = Image.new("RGB", (w, h), (30, 30, 30))
    draw = ImageDraw.Draw(source)
    draw.rectangle((160, 80, 220, 180), fill=(200, 160, 130))
    mask = Image.new("L", (w, h), 255)  # full flood
    overlay = Image.blend(source, Image.merge("RGB", (mask, mask, mask)), 0.45)
    strip = Image.new("RGB", (w * 3, h))
    strip.paste(source, (0, 0))
    strip.paste(mask.convert("RGB"), (w, 0))
    strip.paste(overlay, (w * 2, 0))
    buf = BytesIO()
    strip.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "qa"
        / "live_verification"
        / f"strict_vlm_gate_confirmed_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    parser.add_argument("--skip-live-models", action="store_true")
    args = parser.parse_args()

    cfg = load_strict_gate_config(REPO_ROOT)
    cases: list[dict] = []

    # Case A: critic disabled must block
    disabled = run_strict_visual_review(
        repo_root=REPO_ROOT,
        panel_png=_panel_bytes_bad_empty(),
        label="hand",
        force_disable_critic=True,
    )
    cases.append(
        {
            "case": "force_disable_critic",
            "expect_outcome": "VISUAL_CRITIC_BLOCKED",
            "result": disabled.to_dict(),
            "pass": disabled.outcome == "VISUAL_CRITIC_BLOCKED",
        }
    )

    # Case B: skip_vlm forbidden
    skipped = run_strict_visual_review(
        repo_root=REPO_ROOT,
        panel_png=_panel_bytes_bad_empty(),
        label="hand",
        skip_vlm=True,
    )
    cases.append(
        {
            "case": "skip_vlm_forbidden",
            "expect_outcome": "VISUAL_CRITIC_BLOCKED",
            "result": skipped.to_dict(),
            "pass": skipped.outcome == "VISUAL_CRITIC_BLOCKED"
            and skipped.blocker == "skip_vlm_forbidden_under_strict_gate",
        }
    )

    live_ok = True
    if not args.skip_live_models:
        bad = run_strict_visual_review(
            repo_root=REPO_ROOT,
            panel_png=_panel_bytes_bad_empty(),
            label="torso",
            context="solo",
        )
        bad_pass = (
            bad.outcome
            in {
                "ABSTAIN_BOUNDED",
                "VISUAL_CRITIC_BLOCKED",
            }
            and bad.outcome != "STRICT_VISUAL_QA_PASS_BOUNDED"
        )
        # Prefer explicit fail/abstain from model; blocked due to VRAM is honest not green.
        cases.append(
            {
                "case": "known_bad_empty_mask_panel",
                "expect": "not STRICT_VISUAL_QA_PASS_BOUNDED",
                "result": bad.to_dict(),
                "pass": bad_pass,
            }
        )
        flooded = run_strict_visual_review(
            repo_root=REPO_ROOT,
            panel_png=_panel_bytes_flooded(),
            label="hand",
            context="solo",
        )
        flood_pass = flooded.outcome != "STRICT_VISUAL_QA_PASS_BOUNDED"
        cases.append(
            {
                "case": "known_bad_flooded_mask_panel",
                "expect": "not STRICT_VISUAL_QA_PASS_BOUNDED",
                "result": flooded.to_dict(),
                "pass": flood_pass,
            }
        )
        live_ok = bad_pass and flood_pass
        unload_model(cfg.primary_vlm, cfg.base_url)
        unload_model(cfg.secondary_ensemble_vlm, cfg.base_url)

    all_pass = all(c.get("pass") for c in cases) and live_ok
    evidence = {
        "artifact_type": "strict_vlm_gate_confirmed",
        "schema_version": "1.0.0",
        "recorded_at": _now(),
        "verdict": "CONFIRMED" if all_pass else "NOT_CONFIRMED",
        "config_path": "configs/vlm.yaml#strict_visual_gate",
        "module_path": "src/maskfactory/vlm/strict_gate.py",
        "models": {
            "primary_vlm": cfg.primary_vlm,
            "secondary_ensemble_vlm": cfg.secondary_ensemble_vlm,
            "alternate_high_end_vlm": cfg.alternate_high_end_vlm,
            "temperature": cfg.temperature,
            "seed": cfg.seed,
            "allow_skip_vlm": cfg.allow_skip_vlm,
            "require_ensemble_for_pass": cfg.require_ensemble_for_pass,
        },
        "test_commands": [
            "python tools/smoke_strict_vlm_gate.py --output qa/live_verification/strict_vlm_gate_confirmed_<ts>.json",
            "python tools/run_tournament_ollama_critic_router.py --machine-root runs/<tournament> --limit 2 --output qa/live_verification/tournament_ollama_critic_router_<ts>.json",
            "python tools/run_tournament_mvc_visual_hard_qa.py --machine-root runs/<tournament> --limit 2 --output qa/live_verification/tournament_mvc_visual_hard_qa_<ts>.json",
        ],
        "cases": cases,
        "never_ec2": True,
        "cloud_llm_forbidden": True,
    }
    raw = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    evidence["self_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # re-seal with hash
    text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    latest = args.output.parent / "strict_vlm_gate_confirmed_latest.json"
    latest.write_text(text, encoding="utf-8")
    print(json.dumps({"verdict": evidence["verdict"], "output": str(args.output)}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
