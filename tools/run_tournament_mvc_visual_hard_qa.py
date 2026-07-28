"""Visual/hard QA on tournament ``machine_verified_candidate`` winners only.

Lane: GOLD FACTORY visual/hard QA — NOT draft-corpus seals.

For each MVC lifecycle under ``runs/**/autonomy/*.json``:
  1. Geometric hard veto (format, fg fraction, components, hash bind)
  2. STRICT self-hosted VLM gate (high-end ``llava:13b`` primary +
     ``qwen2.5vl:7b`` ensemble; may_author_masks=false, may_approve_gold=false,
     may_clear_blocks=false) on a source/mask/overlay/contour/heat panel
  3. ``visual_defect_policy`` structural abstain mapping
  4. Demote failures to ``residual_human_queue`` and drop corpus envelopes
  5. Keep only hard+STRICT-VLM pass rows as honest MVC toward autonomous gold

``--skip-vlm`` is VISUAL_CRITIC_BLOCKED under strict_visual_gate (never a promotion).
Never labels warehouse/DAZ/source masks as gold. Never claims VISUAL_QA_PASS_BOUNDED
from residual structural defects. qwen alone is never a rubber stamp.

Usage:
  python tools/gpu_sequencer.py sequence --consumer ollama-vlm \\
      --json qa/live_verification/gpu_sequence_ollama_mvc_visual.json
  python tools/run_tournament_mvc_visual_hard_qa.py \\
      --machine-root runs/autonomous_gold_tournament_20260720_cbackup \\
      --limit 24 \\
      --output qa/live_verification/tournament_mvc_visual_hard_qa_<ts>.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.visual_defect_policy import (  # noqa: E402
    BLOCKED_VISUAL_PASS_CLAIM,
    HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
    STRUCTURAL_ABSTAIN_DEFECT_CLASSES,
    is_structural_abstain_class,
)
from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import read_mask  # noqa: E402
from maskfactory.qa.panels import render_boundary_panel  # noqa: E402
from maskfactory.validation import validate_document  # noqa: E402
from maskfactory.vlm.strict_gate import (  # noqa: E402
    load_strict_gate_config,
    run_strict_visual_review,
)

VLM_CONFIG = REPO_ROOT / "configs" / "vlm.yaml"
_CELEBA_CANDIDATES = [
    Path("/workspace/assets/MaskedWarehouse/CelebAMask-HQ/CelebA-HQ-img"),
    Path(r"C:\Comfy_UI_Main\MaskedWarehouse\CelebAMask-HQ\CelebA-HQ-img"),
]
CELEBA = next((c for c in _CELEBA_CANDIDATES if c.is_dir()), _CELEBA_CANDIDATES[0])
PIPELINE_FP = "multiprovider-local-cuda-tournament-20260720-v1"
MIN_FG = 0.01
MAX_FG = 0.98
MAX_COMPONENTS = 1
# Hand tournament keeps up to 2 components (two visible hands); do not hard-veto that.
MAX_COMPONENTS_BY_LABEL = {
    "hand": 2,
    "hands": 2,
    "clothing": 4,
}

PROBLEM_TO_DEFECT = {
    "includes_clothing_as_skin": "garment_bias",
    "missing_visible_area": "underfill",
    "includes_neighbor_part": "exclusivity_bleed",
    "includes_background": "exclusivity_bleed",
    "boundary_too_loose": "exclusivity_bleed",
    "boundary_too_tight": "underfill",
    # wrong_part is label mismatch, not garment-as-skin; keep structural via exclusivity.
    "wrong_part": "exclusivity_bleed",
    "mask_on_hidden_area": "underfill",
    "occlusion_error": "underfill",
    "finger_merge": "exclusivity_bleed",
    "hair_edge_bad": "exclusivity_bleed",
    "wrong_side": "exclusivity_bleed",
    "other": "exclusivity_bleed",
}

TORSO_PROMPT = (
    "You are auditing a TORSO (chest+abdomen silhouette) segmentation mask. "
    "Panel tiles L->R: source crop, mask, overlay, contour, protected-overlap heat. "
    "Governed role: qa_router_only; you may NOT author masks or approve gold. "
    "Answer STRICT JSON only: "
    "{verdict: pass|fail|uncertain, confidence: 0-1, "
    "problems: [subset of [wrong_part, wrong_side, boundary_too_loose, "
    "boundary_too_tight, includes_clothing_as_skin, includes_background, "
    "includes_neighbor_part, missing_visible_area, mask_on_hidden_area, "
    "finger_merge, hair_edge_bad, occlusion_error, other]], "
    "evidence: '<<=25 words pointing at panel location>', "
    "correction_instruction: '<=30 words imperative for the annotator>'}"
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_vlm_config() -> dict[str, Any]:
    config = yaml.safe_load(VLM_CONFIG.read_text(encoding="utf-8"))
    gov = config["governance"]
    if gov.get("may_author_masks") is not False or gov.get("may_approve_gold") is not False:
        raise RuntimeError(f"VLM governance must remain non-authoritative: {gov}")
    if gov.get("may_clear_blocks") is not False:
        raise RuntimeError(f"VLM may_clear_blocks must be false: {gov}")
    # Enforce STRICT gate config (high-end primary + ensemble). Legacy S11 primary_vlm
    # may remain qwen2.5vl:7b for calibrated fingerprints; autonomy review must not.
    strict = load_strict_gate_config(REPO_ROOT)
    config["_strict_gate"] = {
        "primary_vlm": strict.primary_vlm,
        "secondary_ensemble_vlm": strict.secondary_ensemble_vlm,
        "allow_skip_vlm": strict.allow_skip_vlm,
        "require_ensemble_for_pass": strict.require_ensemble_for_pass,
    }
    return config


def _post_json(url: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    last_exc: BaseException | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as exc:
            last_exc = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"Ollama unreachable after retries: {last_exc}") from last_exc


def _word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])


def _validate_p_part(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    prompt_config = config["prompts"]["p_part"]
    required = set(prompt_config["required_keys"])
    allowed_verdicts = set(prompt_config["allowed_verdicts"])
    allowed_problems = set(prompt_config["allowed_problems"])
    return {
        "exact_required_keys": set(payload) == required,
        "verdict_allowed": payload.get("verdict") in allowed_verdicts,
        "confidence_number_0_1": isinstance(payload.get("confidence"), int | float)
        and 0 <= float(payload["confidence"]) <= 1,
        "problems_list_allowed": isinstance(payload.get("problems"), list)
        and all(p in allowed_problems for p in payload["problems"]),
        "evidence_string_25_words": isinstance(payload.get("evidence"), str)
        and _word_count(payload["evidence"]) <= 25,
        "correction_instruction_string_30_words": isinstance(
            payload.get("correction_instruction"), str
        )
        and _word_count(payload["correction_instruction"]) <= 30,
    }


def _call_vlm(config: dict[str, Any], image_png: bytes, *, retry: bool = False) -> dict[str, Any]:
    prompt = TORSO_PROMPT
    if retry:
        prompt += "\nReturn JSON only. Do not include Markdown or explanation."
    payload = {
        "model": config["models"]["primary_vlm"],
        "format": "json",
        "stream": False,
        "options": dict(config["runtime"].get("generation_options") or {"temperature": 0}),
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_png).decode("ascii")],
            }
        ],
    }
    base = config["runtime"]["base_url"].rstrip("/")
    return _post_json(f"{base}/api/chat", payload)


def _normalize_source_path(path: str | None) -> str | None:
    if not path:
        return path
    raw = str(path)
    mapping = {
        r"F:\Reference_Images": "/workspace/assets/Reference_Images",
        "F:/Reference_Images": "/workspace/assets/Reference_Images",
        r"C:\Comfy_UI_Main\MaskedWarehouse": "/workspace/assets/MaskedWarehouse",
        "C:/Comfy_UI_Main/MaskedWarehouse": "/workspace/assets/MaskedWarehouse",
    }
    for old, new in mapping.items():
        if raw.startswith(old):
            return new + raw[len(old) :].replace(chr(92), "/")
    return raw


def _index_from_tournament_meta(machine_roots: list[Path] | None = None) -> dict[str, str]:
    """Prefer stage-local *tournament_meta.json source_path (hand/clothing lanes)."""
    index: dict[str, str] = {}
    roots = machine_roots or [REPO_ROOT / "runs"]
    for root in roots:
        if not root.is_dir():
            continue
        for meta in root.rglob("*_tournament_meta.json"):
            try:
                doc = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            path = doc.get("source_path") or doc.get("source_path_readonly")
            if not path:
                continue
            image_id = meta.parent.name  # …/hand_tournament/img_<12hex>/
            if image_id.startswith("img_") and len(image_id) >= 16:
                key = image_id[4:16]
                index[key] = _normalize_source_path(str(path)) or str(path)
            sha = str(doc.get("source_sha256") or "")
            if sha:
                index.setdefault(sha[:12], _normalize_source_path(str(path)) or str(path))
    return index


def _build_source_index(
    needed_digest12: set[str] | None = None,
    *,
    machine_roots: list[Path] | None = None,
) -> dict[str, str]:
    """Map img_<12hex> -> absolute source path via meta + sample sets + CelebA scan."""
    index: dict[str, str] = {}
    need = set(needed_digest12 or ())
    # Fast path for hand/clothing tournament stages (authoritative per-image meta).
    index.update(_index_from_tournament_meta(machine_roots))
    if need and need.issubset(index):
        return index
    live = REPO_ROOT / "qa" / "live_verification"
    sample_globs = (
        "tournament_sample_set_*.json",
        "gold_volume_*.json",
        "*_feed_*.json",
    )
    for pattern in sample_globs:
        for sp in sorted(live.glob(pattern)):
            try:
                doc = json.loads(sp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = doc.get("samples") or doc.get("ordered_samples") or []
            if isinstance(doc.get("by_image_id"), dict):
                rows = list(rows) + list(doc["by_image_id"].values())
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sha = str(row.get("source_sha256") or "")
                path = row.get("source_path_readonly") or row.get("source_path") or row.get("path")
                image_id = str(row.get("image_id") or "")
                keys: list[str] = []
                if sha:
                    keys.append(sha[:12])
                if image_id.startswith("img_") and len(image_id) >= 16:
                    keys.append(image_id[4:16])
                if path:
                    for key in keys:
                        if key and key not in index:
                            index[key] = _normalize_source_path(str(path)) or str(path)
    if need and need.issubset(index):
        return index
    if CELEBA.is_dir() and (not need or not need.issubset(index)):
        for path in sorted(CELEBA.glob("*.jpg")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            key = digest[:12]
            if key not in index:
                index[key] = _normalize_source_path(str(path)) or str(path)
            if need and need.issubset(index):
                break
            if not need and len(index) >= 4096:
                break
    return index


def _discover_mvc(machine_roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in machine_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("autonomy/*.json")):
            if path.name.endswith(
                (".corpus_record.json", ".visual_hard_qa.json", ".strict_vlm_gate.json")
            ):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if doc.get("status") != "machine_verified_candidate":
                continue
            label = str(doc.get("label") or path.stem)
            already = False
            for side_name in (f"{label}.visual_hard_qa.json", f"{label}.strict_vlm_gate.json"):
                side = path.with_name(side_name)
                if not side.is_file():
                    continue
                try:
                    review = json.loads(side.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                outcome = review.get("outcome") or (review.get("result") or {}).get("outcome")
                if outcome in {
                    "VISUAL_HARD_QA_PASS_BOUNDED",
                    "STRICT_VISUAL_QA_PASS_BOUNDED",
                }:
                    already = True
                    break
            if already:
                continue
            found.append(path)
    return found


def _component_count(mask: np.ndarray) -> int:
    labeled, count = ndimage.label(np.asarray(mask).astype(bool))
    del labeled
    return int(count)


def _hard_veto(mask: np.ndarray, lifecycle: dict[str, Any], mask_path: Path) -> list[str]:
    vetoes: list[str] = []
    if mask.ndim != 2:
        vetoes.append("invalid_mask_format")
        return vetoes
    if not mask.any():
        vetoes.append("empty_mask")
    fg = float(mask.mean())
    if not (MIN_FG < fg < MAX_FG):
        vetoes.append("fg_fraction_out_of_bounds")
    label = str(lifecycle.get("label") or "torso").lower()
    max_comps = int(MAX_COMPONENTS_BY_LABEL.get(label, MAX_COMPONENTS))
    if _component_count(mask) > max_comps:
        vetoes.append("component_overflow")
    expected = lifecycle.get("winner_mask_sha256")
    if isinstance(expected, str) and len(expected) == 64:
        if sha256_file(mask_path) != expected:
            vetoes.append("winner_mask_sha256_mismatch")
    else:
        vetoes.append("missing_winner_mask_sha256")
    return vetoes


def _defect_classes_from_problems(problems: list[str]) -> list[str]:
    classes: set[str] = set()
    known = set(PROBLEM_TO_DEFECT)
    for p in problems or []:
        if isinstance(p, dict):
            p = (
                p.get("id")
                or p.get("problem")
                or p.get("name")
                or p.get("type")
                or p.get("code")
                or "other"
            )
        key = str(p or "").strip()
        if not key:
            continue
        # Free-form VLM sentences must NOT auto-map to garment_bias (false structural abstain).
        if key not in known:
            lower = key.lower()
            if any(x in lower for x in ("background", "spill", "leak", "neighbor")):
                key = "includes_background"
            elif any(x in lower for x in ("empty", "blank", "missing", "underfill")):
                key = "missing_visible_area"
            elif any(x in lower for x in ("wrong_part", "wrong part", "face", "torso")):
                key = "wrong_part"
            elif "boundar" in lower or "loose" in lower:
                key = "boundary_too_loose"
            elif key == "other" or lower == "other":
                key = "other"
            else:
                # Unknown free-form: skip inventing garment_bias.
                continue
        classes.add(PROBLEM_TO_DEFECT[key])
    return sorted(classes)


def _demote_lifecycle(
    lifecycle_path: Path, lifecycle: dict[str, Any], reason: str
) -> dict[str, Any]:
    updated = dict(lifecycle)
    # Drop non-schema sidechannel keys before validate (repair metadata lives in meta JSON).
    for _k in list(updated):
        if _k in {"rectish_repair"} or str(_k).startswith("restored_"):
            updated.pop(_k, None)
    updated["status"] = "residual_human_queue"
    updated["truth_tier"] = "machine_candidate"
    updated["training_loss_weight"] = 0.0
    updated["serve_eligible"] = False
    updated["pseudo_train_eligible"] = False
    updated["authoritative_human_gold"] = False
    updated["certificate_valid"] = False
    updated["certificate_reason"] = "visual_hard_qa_demoted"
    updated["reason"] = reason
    updated["human_audit_required"] = True
    issues = validate_document(updated, "autonomy_lifecycle")
    if issues:
        raise RuntimeError(f"demoted lifecycle invalid: {issues}")
    tmp = lifecycle_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(lifecycle_path)
    envelope = lifecycle_path.with_name(lifecycle_path.stem + ".corpus_record.json")
    if envelope.is_file():
        envelope.unlink()
    return updated


def _review_one(
    lifecycle_path: Path,
    *,
    source_index: dict[str, str],
    config: dict[str, Any],
    apply_demote: bool,
    skip_vlm: bool,
) -> dict[str, Any]:
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    image_id = str(lifecycle.get("image_id") or "")
    stage = lifecycle_path.parent.parent
    mask_rel = lifecycle.get("winner_mask_path")
    row: dict[str, Any] = {
        "image_id": image_id,
        "lifecycle_path": str(lifecycle_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "label": lifecycle.get("label"),
        "prior_status": lifecycle.get("status"),
    }
    prior_label = str(lifecycle.get("label") or "torso")
    prior_review = lifecycle_path.with_name(f"{prior_label}.visual_hard_qa.json")
    if prior_review.is_file():
        try:
            prior = json.loads(prior_review.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
        if prior.get("outcome") == "VISUAL_HARD_QA_PASS_BOUNDED":
            row["outcome"] = "VISUAL_HARD_QA_PASS_BOUNDED"
            row["retained_as"] = "machine_verified_candidate"
            row["skipped_existing_pass_sidecar"] = True
            row["review_sidecar"] = str(prior_review.relative_to(REPO_ROOT)).replace("\\", "/")
            return row
    # Also honor strict_vlm_gate sidecar pass without re-running.
    prior_strict = lifecycle_path.with_name(f"{prior_label}.strict_vlm_gate.json")
    if prior_strict.is_file():
        try:
            prior = json.loads(prior_strict.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
        if prior.get("outcome") in {
            "VISUAL_HARD_QA_PASS_BOUNDED",
            "STRICT_VISUAL_QA_PASS_BOUNDED",
        }:
            row["outcome"] = prior.get("outcome")
            row["retained_as"] = "machine_verified_candidate"
            row["skipped_existing_pass_sidecar"] = True
            row["review_sidecar"] = str(prior_strict.relative_to(REPO_ROOT)).replace("\\", "/")
            return row
    if not isinstance(mask_rel, str) or not mask_rel:
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "missing_winner_mask_path"
        if apply_demote:
            _demote_lifecycle(lifecycle_path, lifecycle, "visual_hard_qa: missing winner mask path")
            row["demoted"] = True
        return row

    mask_path = (stage / mask_rel).resolve()
    if not mask_path.is_file():
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "winner_mask_missing_on_disk"
        if apply_demote:
            _demote_lifecycle(lifecycle_path, lifecycle, "visual_hard_qa: winner mask missing")
            row["demoted"] = True
        return row

    mask = (read_mask(mask_path) > 0).astype(bool)
    hard = _hard_veto(mask, lifecycle, mask_path)
    row["hard_vetoes"] = hard
    row["fg_fraction"] = round(float(mask.mean()), 6)
    row["component_count"] = _component_count(mask)

    digest12 = image_id.replace("img_", "")
    source_path = _normalize_source_path(source_index.get(digest12))
    # Stage-local tournament meta is authoritative for hand/clothing emits.
    if source_path is None or not Path(source_path).is_file():
        for meta_name in (
            "hand_tournament_meta.json",
            "clothing_tournament_meta.json",
            "tournament_meta.json",
        ):
            meta_path = stage / meta_name
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            cand = _normalize_source_path(
                str(meta.get("source_path") or meta.get("source_path_readonly") or "")
            )
            if cand and Path(cand).is_file():
                source_path = cand
                source_index[digest12] = cand
                row["source_from_tournament_meta"] = True
                break
    row["source_path_readonly"] = source_path
    if source_path is None or not Path(source_path).is_file():
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "source_image_unresolved"
        # Index gaps are infrastructure, not mask defects — keep MVC for retry once
        # source paths are wired; do not demote tournament winners for missing index.
        row["demoted"] = False
        row["note"] = (
            "Source unresolved; VLM critic skipped; lifecycle left as "
            "machine_verified_candidate for retry (not a visual defect demote)."
        )
        return row

    source = Image.open(source_path).convert("RGB")
    if source.size != (mask.shape[1], mask.shape[0]):
        # Tournament emits working-long-side masks; resize source for panel when
        # aspect ratio matches. True shape sabotage still hard-vetoes.
        sw, sh = source.size
        mh, mw = int(mask.shape[0]), int(mask.shape[1])
        aspect_ok = abs((sw / max(sh, 1)) - (mw / max(mh, 1))) <= 0.02
        if aspect_ok and min(sw, sh) > 0:
            source = source.resize((mw, mh), Image.Resampling.BILINEAR)
            row["source_resized_to_mask_for_panel"] = True
        else:
            hard.append("source_mask_dimension_mismatch")
            row["hard_vetoes"] = hard

    if hard:
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["visual_tier"] = HIGHEST_VISUAL_TIER_WITH_RESIDUALS
        row["claims_forbidden"] = [BLOCKED_VISUAL_PASS_CLAIM, "gold", "autonomous_certified_gold"]
        if apply_demote:
            _demote_lifecycle(
                lifecycle_path,
                lifecycle,
                "visual_hard_qa hard veto: " + ",".join(hard),
            )
            row["demoted"] = True
        return row

    label_for_panel = str(lifecycle.get("label") or "torso")
    panel_path = stage / "qa_panels" / f"{label_for_panel}_boundary_panel.png"
    protected = np.zeros(mask.shape, dtype=bool)
    # Hands sit near torso — use tighter bbox zoom so VLM is not distracted by body crop.
    zoom = 1.35 if label_for_panel.lower() in {"hand", "hands"} else 2.0
    render_boundary_panel(source, mask, protected, panel_path, zoom_multiplier=zoom)
    row["panel_zoom_multiplier"] = zoom
    row["panel_path"] = str(panel_path.relative_to(REPO_ROOT)).replace("\\", "/")
    row["panel_sha256"] = sha256_file(panel_path)

    if skip_vlm:
        # STRICT gate: skip is never a promotion path.
        strict_skip = run_strict_visual_review(
            repo_root=REPO_ROOT,
            panel_png=panel_path,
            label=str(lifecycle.get("label") or "torso"),
            skip_vlm=True,
        )
        row["outcome"] = "VISUAL_CRITIC_BLOCKED"
        row["vlm_skipped"] = True
        row["blocker"] = strict_skip.blocker or "skip_vlm_forbidden_under_strict_gate"
        row["strict_gate"] = strict_skip.to_dict()
        row["claims_forbidden"] = [
            BLOCKED_VISUAL_PASS_CLAIM,
            "gold",
            "autonomous_certified_gold",
            "blind_approve",
        ]
        return row

    strict = run_strict_visual_review(
        repo_root=REPO_ROOT,
        panel_png=panel_path,
        label=str(lifecycle.get("label") or "torso"),
        context=str(lifecycle.get("instance_context") or "solo"),
    )
    row["vlm_latency_seconds"] = (strict.evidence_log or {}).get("latency_seconds")
    row["vlm_governance"] = {
        "role": "qa_router_only",
        "may_author_masks": False,
        "may_approve_gold": False,
        "may_clear_blocks": False,
        "model": strict.model_id,
        "ensemble_model": strict.ensemble_model_id,
        "prompt_sha256": strict.prompt_sha256,
        "panel_sha256": strict.panel_sha256,
    }
    row["strict_gate"] = strict.to_dict()
    row["vlm_response"] = strict.response
    row["vlm_ensemble_response"] = strict.ensemble_response

    if strict.outcome == "VISUAL_CRITIC_BLOCKED":
        row["outcome"] = "VISUAL_CRITIC_BLOCKED"
        row["blocker"] = strict.blocker or "strict_vlm_unavailable"
        row["visual_tier"] = HIGHEST_VISUAL_TIER_WITH_RESIDUALS
        row["claims_forbidden"] = [
            BLOCKED_VISUAL_PASS_CLAIM,
            "gold",
            "autonomous_certified_gold",
        ]
        # Do not demote tournament MVC on transport/config block — retry when VRAM/Ollama ready.
        row["demoted"] = False
        return row

    parsed = strict.response or {}
    verdict = strict.verdict or "uncertain"
    confidence = float(strict.confidence or 0.0)
    problems = list(parsed.get("problems") or [])
    defect_classes = _defect_classes_from_problems(problems)
    structural = [c for c in defect_classes if is_structural_abstain_class(c)]
    row["defect_classes"] = defect_classes
    row["structural_abstain_classes"] = structural

    if (
        strict.outcome != "STRICT_VISUAL_QA_PASS_BOUNDED"
        or verdict == "fail"
        or structural
        or (verdict == "uncertain" and confidence < 0.85)
    ):
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["visual_tier"] = HIGHEST_VISUAL_TIER_WITH_RESIDUALS
        row["claims_forbidden"] = [BLOCKED_VISUAL_PASS_CLAIM, "gold", "autonomous_certified_gold"]
        row["blocker"] = strict.blocker or "strict_vlm_abstain"
        row["policy"] = {
            "structural_abstain_defect_classes": sorted(STRUCTURAL_ABSTAIN_DEFECT_CLASSES),
            "blocked_visual_pass_claim": BLOCKED_VISUAL_PASS_CLAIM,
        }
        if apply_demote:
            reason = (
                f"visual_hard_qa STRICT VLM abstain verdict={verdict} "
                f"confidence={confidence} defects={','.join(defect_classes) or 'none'} "
                f"blocker={strict.blocker}"
            )
            _demote_lifecycle(lifecycle_path, lifecycle, reason)
            row["demoted"] = True
        return row

    if verdict == "pass" and confidence >= 0.7 and not problems:
        row["outcome"] = "VISUAL_HARD_QA_PASS_BOUNDED"
        row["retained_as"] = "machine_verified_candidate"
        row["visual_tier"] = "VISUAL_HARD_QA_PASS_BOUNDED"
        row["claims_forbidden"] = ["gold", "autonomous_certified_gold", "source_warehouse_gold"]
        row["note"] = (
            "Hard veto + STRICT high-end VLM gate (llava primary + qwen ensemble) passed; "
            "remains machine_verified_candidate toward autonomous_certified_gold — not gold yet."
        )
        review_path = lifecycle_path.with_name(
            f"{lifecycle.get('label') or 'torso'}.visual_hard_qa.json"
        )
        review_path.write_text(
            json.dumps(
                {
                    "artifact_type": "tournament_mvc_visual_hard_qa_item",
                    "schema_version": "1.1.0",
                    "recorded_at": _now(),
                    "image_id": image_id,
                    "outcome": row["outcome"],
                    "strict_gate": strict.to_dict(),
                    "vlm_response": parsed,
                    "panel_sha256": row["panel_sha256"],
                    "governance": row["vlm_governance"],
                    "authoritative_human_gold": False,
                    "autonomous_certified_gold": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        row["review_sidecar"] = str(review_path.relative_to(REPO_ROOT)).replace("\\", "/")
        return row

    row["outcome"] = "ABSTAIN_BOUNDED"
    row["visual_tier"] = HIGHEST_VISUAL_TIER_WITH_RESIDUALS
    row["blocker"] = "vlm_pass_with_residual_problems_or_low_confidence"
    if apply_demote:
        _demote_lifecycle(
            lifecycle_path,
            lifecycle,
            "visual_hard_qa: VLM pass residual problems or low confidence",
        )
        row["demoted"] = True
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--machine-root",
        action="append",
        type=Path,
        default=None,
        help="Tournament run root(s). Repeatable. Default: discover under runs/.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max MVC to review (0=all).")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--apply-demote",
        action="store_true",
        help="Demote failing MVC to residual_human_queue and drop corpus envelopes.",
    )
    parser.add_argument(
        "--skip-vlm",
        action="store_true",
        help="Forbidden under strict_visual_gate: records VISUAL_CRITIC_BLOCKED (never a pass).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not demote even if --apply-demote (alias: ignore demote writes).",
    )
    args = parser.parse_args()

    if args.machine_root:
        roots = [(REPO_ROOT / p if not p.is_absolute() else p).resolve() for p in args.machine_root]
    else:
        runs = REPO_ROOT / "runs"
        roots = sorted(
            p
            for p in runs.iterdir()
            if p.is_dir()
            and (
                "tournament" in p.name.lower()
                or "emit_prove" in p.name.lower()
                or p.name.lower().startswith("autonomous_gold_")
            )
        )

    config = _read_vlm_config()
    mvc_paths = _discover_mvc(roots)
    needed = set()
    for path in mvc_paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        image_id = str(doc.get("image_id") or "")
        if image_id.startswith("img_") and len(image_id) >= 16:
            needed.add(image_id[4:16])
    source_index = _build_source_index(needed, machine_roots=roots)
    if args.limit and len(mvc_paths) > args.limit:
        mvc_paths = mvc_paths[: args.limit]

    apply_demote = bool(args.apply_demote) and not bool(args.dry_run)
    rows: list[dict[str, Any]] = []
    for path in mvc_paths:
        try:
            rows.append(
                _review_one(
                    path,
                    source_index=source_index,
                    config=config,
                    apply_demote=apply_demote,
                    skip_vlm=bool(args.skip_vlm),
                )
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed per item, continue burst
            rows.append(
                {
                    "lifecycle_path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "outcome": "ABSTAIN_BOUNDED",
                    "blocker": f"review_exception:{type(exc).__name__}",
                    "error": str(exc)[:500],
                    "demoted": False,
                }
            )

    outcomes = Counter(r.get("outcome") for r in rows)
    retained = sum(1 for r in rows if r.get("retained_as") == "machine_verified_candidate")
    demoted = sum(1 for r in rows if r.get("demoted"))
    evidence: dict[str, Any] = {
        "artifact_type": "tournament_mvc_visual_hard_qa",
        "schema_version": "1.1.0",
        "recorded_at": _now(),
        "lane": "GOLD_FACTORY_visual_hard_qa_tournament_mvc_only",
        "authority": [
            "configs/vlm.yaml#strict_visual_gate (high-end primary + qwen ensemble)",
            "configs/vlm.yaml governance (may_author_masks=false, may_approve_gold=false)",
            "src/maskfactory/vlm/strict_gate.py",
            "src/maskfactory/autonomy/visual_defect_policy.py",
            "tools/gpu_sequencer.py ollama-vlm consumer",
        ],
        "honesty_rules": [
            "NOT a draft-corpus VISUAL_QA_REVIEWED_WITH_DEFECTS seal",
            "Source/DAZ/warehouse masks are never gold",
            f"{BLOCKED_VISUAL_PASS_CLAIM} forbidden when structural residuals remain",
            "autonomous_certified_gold only via admission certificate path after retained MVC",
            "qwen2.5vl:7b alone is never a rubber-stamp critic",
            "--skip-vlm yields VISUAL_CRITIC_BLOCKED, never promotion",
        ],
        "machine_roots": [str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in roots],
        "pipeline_fingerprint_filter_note": PIPELINE_FP,
        "mvc_reviewed": len(rows),
        "outcomes": dict(outcomes),
        "retained_machine_verified_candidate": retained,
        "demoted_to_residual": demoted,
        "autonomous_certified_gold": 0,
        "vlm_model": (config.get("_strict_gate") or {}).get("primary_vlm"),
        "vlm_ensemble_model": (config.get("_strict_gate") or {}).get("secondary_ensemble_vlm"),
        "s11_calibrated_primary_vlm": config["models"]["primary_vlm"],
        "vlm_skipped": bool(args.skip_vlm),
        "apply_demote": apply_demote,
        "rows": rows,
        "blocker": None,
        "next_agent_step": (
            "Re-run assemble_autonomous_verification_corpus + build_autonomous_gold_admission "
            "--corpus on retained MVC; Wilson gates still apply — do not fabricate gold."
            if retained
            else "No MVC survived visual/hard QA; repair tournament emit/agreement or "
            "re-segment structural defects — do not seal draft-corpus visual review."
        ),
    }
    if retained == 0 and len(rows) == 0:
        evidence["blocker"] = "zero_machine_verified_candidate_in_scoped_runs"
    elif retained == 0:
        evidence["blocker"] = "all_mvc_abstained_or_hard_vetoed_by_visual_qa"

    raw = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    evidence["self_sha256"] = digest
    out = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    # rewrite with digest
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(out.relative_to(REPO_ROOT)).replace("\\", "/"),
                "mvc_reviewed": len(rows),
                "retained_mvc": retained,
                "demoted": demoted,
                "outcomes": dict(outcomes),
                "blocker": evidence["blocker"],
                "self_sha256": digest,
            },
            sort_keys=True,
        )
    )
    return 0 if retained > 0 or len(rows) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
