"""Advisory Ollama qwen2.5vl:7b critic/router on tournament MVC winners.

Lane: GOLD FACTORY — scores machine_verified_candidate masks with governed
``qa_router_only`` VLM (may_author_masks=false, may_approve_gold=false).

Hard rules:
  * Never author masks or approve gold.
  * Never demote / rewrite multi-family agreement lifecycle status.
  * Critic scores and RoutingDecision are advisory audit evidence only.
  * When MVC exist, score them; when none, exit with typed zero-run evidence.

Usage:
  python tools/gpu_sequencer.py sequence --consumer ollama-vlm \\
      --json qa/live_verification/gpu_sequence_ollama_critic_router.json
  python tools/run_tournament_ollama_critic_router.py \\
      --output qa/live_verification/tournament_ollama_critic_router_<ts>.json
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

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import read_mask  # noqa: E402
from maskfactory.qa.panels import render_boundary_panel  # noqa: E402
from maskfactory.vlm.client import VlmVerdict  # noqa: E402
from maskfactory.vlm.router import route  # noqa: E402

VLM_CONFIG = REPO_ROOT / "configs" / "vlm.yaml"
CELEBA = Path(r"C:\Comfy_UI_Main\MaskedWarehouse\CelebAMask-HQ\CelebA-HQ-img")

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
    if gov.get("role") != "qa_router_only":
        raise RuntimeError(f"VLM role must be qa_router_only, got {gov.get('role')}")
    if gov.get("may_author_masks") is not False or gov.get("may_approve_gold") is not False:
        raise RuntimeError(f"VLM governance must remain non-authoritative: {gov}")
    if gov.get("may_clear_blocks") is not False:
        raise RuntimeError(f"VLM may_clear_blocks must be false: {gov}")
    if config["models"]["primary_vlm"] != "qwen2.5vl:7b":
        raise RuntimeError(
            f"primary_vlm must be qwen2.5vl:7b, got {config['models']['primary_vlm']}"
        )
    return config


def _post_json(url: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc


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


def _build_source_index(needed_digest12: set[str] | None = None) -> dict[str, str]:
    index: dict[str, str] = {}
    need = set(needed_digest12 or ())
    for sp in (REPO_ROOT / "qa/live_verification").glob("tournament_sample_set_*.json"):
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in doc.get("samples") or []:
            sha = str(row.get("source_sha256") or "")
            path = row.get("source_path_readonly") or row.get("source_path")
            if sha and path and sha[:12] not in index:
                index[sha[:12]] = str(path)
    if CELEBA.is_dir() and (not need or not need.issubset(index)):
        for path in sorted(CELEBA.glob("*.jpg")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            key = digest[:12]
            if key not in index:
                index[key] = str(path)
            if need and need.issubset(index):
                break
            if not need and len(index) >= 512:
                break
    return index


def _discover_mvc(machine_roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in machine_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("autonomy/*.json")):
            if path.name.endswith(".corpus_record.json"):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if doc.get("status") == "machine_verified_candidate":
                found.append(path)
    return found


def _critic_pass_weight(verdict: str, confidence: float) -> float:
    if verdict == "pass":
        return max(0.0, min(1.0, float(confidence)))
    if verdict == "uncertain":
        return 0.5 * max(0.0, min(1.0, float(confidence)))
    return 0.0


def _score_one(
    lifecycle_path: Path,
    *,
    source_index: dict[str, str],
    config: dict[str, Any],
) -> dict[str, Any]:
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    prior_status = lifecycle.get("status")
    image_id = str(lifecycle.get("image_id") or "")
    stage = lifecycle_path.parent.parent
    mask_rel = lifecycle.get("winner_mask_path")
    row: dict[str, Any] = {
        "image_id": image_id,
        "lifecycle_path": str(lifecycle_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "label": lifecycle.get("label"),
        "prior_status": prior_status,
        "lifecycle_status_unchanged": True,
        "multi_family_agreement_preserved": True,
        "may_author_masks": False,
        "may_approve_gold": False,
    }
    if prior_status != "machine_verified_candidate":
        row["outcome"] = "SKIPPED_NOT_MVC"
        row["critic_run"] = False
        return row
    if not isinstance(mask_rel, str) or not mask_rel:
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "missing_winner_mask_path"
        row["critic_run"] = False
        return row

    mask_path = (stage / mask_rel).resolve()
    if not mask_path.is_file():
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "winner_mask_missing_on_disk"
        row["critic_run"] = False
        return row

    mask = (read_mask(mask_path) > 0).astype(bool)
    digest12 = image_id.replace("img_", "")
    source_path = source_index.get(digest12)
    row["source_path_readonly"] = source_path
    if source_path is None or not Path(source_path).is_file():
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "source_image_unresolved"
        row["critic_run"] = False
        return row

    source = Image.open(source_path).convert("RGB")
    if source.size != (mask.shape[1], mask.shape[0]):
        row["outcome"] = "ABSTAIN_BOUNDED"
        row["blocker"] = "source_mask_dimension_mismatch"
        row["critic_run"] = False
        return row

    panel_path = stage / "qa_panels" / "torso_boundary_panel.png"
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    protected = np.zeros(mask.shape, dtype=bool)
    render_boundary_panel(source, mask, protected, panel_path)
    row["panel_path"] = str(panel_path.relative_to(REPO_ROOT)).replace("\\", "/")
    row["panel_sha256"] = sha256_file(panel_path)

    png = panel_path.read_bytes()
    parsed: dict[str, Any] | None = None
    checks: dict[str, bool] = {}
    attempts: list[dict[str, Any]] = []
    started = time.perf_counter()
    for attempt in range(int(config["prompts"]["p_part"]["retry_on_invalid_json"]) + 1):
        response = _call_vlm(config, png, retry=attempt > 0)
        content = response["message"]["content"]
        attempt_rec: dict[str, Any] = {
            "attempt": attempt + 1,
            "model": response.get("model"),
            "eval_count": response.get("eval_count"),
        }
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("response is not a JSON object")
            checks = _validate_p_part(parsed, config)
            attempt_rec["parsed"] = True
            attempt_rec["checks"] = checks
        except (json.JSONDecodeError, ValueError) as exc:
            attempt_rec["parsed"] = False
            attempt_rec["error"] = str(exc)
            parsed = None
        attempts.append(attempt_rec)
        if parsed is not None and checks and all(checks.values()):
            break

    row["vlm_latency_seconds"] = round(time.perf_counter() - started, 3)
    row["vlm_attempts"] = attempts
    row["vlm_governance"] = {
        "role": "qa_router_only",
        "may_author_masks": False,
        "may_approve_gold": False,
        "may_clear_blocks": False,
        "model": config["models"]["primary_vlm"],
    }
    row["critic_run"] = True

    if parsed is None or not all(checks.values()):
        row["outcome"] = "CRITIC_INVALID_RESPONSE"
        row["blocker"] = "vlm_response_invalid"
        row["advisory_critic_pass_weight"] = 0.0
        return row

    verdict = str(parsed["verdict"])
    confidence = float(parsed["confidence"])
    problems = list(parsed.get("problems") or [])
    weight = _critic_pass_weight(verdict, confidence)
    vlm_verdict = VlmVerdict(
        label=str(lifecycle.get("label") or "torso"),
        panel_file=row["panel_path"],
        model=config["models"]["primary_vlm"],
        prompt_version=str(config["prompts"]["p_part"]["version"]),
        verdict=verdict,
        confidence=confidence,
        problems=tuple(problems),
        evidence=str(parsed.get("evidence") or ""),
        correction_instruction=str(parsed.get("correction_instruction") or ""),
        latency_ms=int(row["vlm_latency_seconds"] * 1000),
    )
    # auto_qa=route: VLM is router/critic only — never quick-pass / gold approve.
    decision = route("route", vlm_verdict)
    row["vlm_response"] = parsed
    row["advisory_critic_pass_weight"] = round(weight, 6)
    row["routing_decision"] = {
        "queue": decision.queue,
        "priority": decision.priority,
        "correction_hint": decision.correction_hint,
        "pin_disagreement_heatmap": decision.pin_disagreement_heatmap,
        "may_approve_gold": decision.may_approve_gold,
        "may_clear_block": decision.may_clear_block,
        "may_edit_mask": decision.may_edit_mask,
    }
    row["outcome"] = "CRITIC_SCORED_ADVISORY"
    row["note"] = (
        "Advisory critic/router score only; multi-family agreement lifecycle "
        f"status remains {prior_status!r}; VLM cannot replace agreement or mint gold."
    )

    # Persist advisory sidecar without mutating lifecycle JSON.
    sidecar = lifecycle_path.with_name(lifecycle_path.stem + ".ollama_critic_router.json")
    sidecar_doc = {
        "artifact_type": "tournament_mvc_ollama_critic_router_item",
        "schema_version": "1.0.0",
        "recorded_at": _now(),
        "image_id": image_id,
        "lifecycle_path": row["lifecycle_path"],
        "lifecycle_status_unchanged": True,
        "multi_family_agreement_preserved": True,
        "prior_status": prior_status,
        "outcome": row["outcome"],
        "advisory_critic_pass_weight": row["advisory_critic_pass_weight"],
        "vlm_response": parsed,
        "routing_decision": row["routing_decision"],
        "panel_sha256": row["panel_sha256"],
        "governance": row["vlm_governance"],
        "authoritative_human_gold": False,
        "autonomous_certified_gold": False,
        "may_author_masks": False,
        "may_approve_gold": False,
    }
    sidecar.write_text(json.dumps(sidecar_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    row["critic_sidecar"] = str(sidecar.relative_to(REPO_ROOT)).replace("\\", "/")

    # Integrity: re-read lifecycle and prove status untouched.
    after = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    if after.get("status") != prior_status:
        raise RuntimeError(
            f"CRITIC MUST NOT mutate lifecycle status: {lifecycle_path} "
            f"{prior_status!r} -> {after.get('status')!r}"
        )
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
    parser.add_argument("--limit", type=int, default=0, help="Max MVC to score (0=all).")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.machine_root:
        roots = [(REPO_ROOT / p if not p.is_absolute() else p).resolve() for p in args.machine_root]
    else:
        runs = REPO_ROOT / "runs"
        roots = sorted(p for p in runs.iterdir() if p.is_dir() and "tournament" in p.name.lower())

    config = _read_vlm_config()
    mvc_paths = _discover_mvc(roots)
    needed = {p.parent.parent.name.replace("img_", "") for p in mvc_paths}
    source_index = _build_source_index(needed)

    if args.limit and len(mvc_paths) > args.limit:
        mvc_paths = mvc_paths[: args.limit]

    rows: list[dict[str, Any]] = []
    for path in mvc_paths:
        rows.append(_score_one(path, source_index=source_index, config=config))

    outcomes = Counter(r.get("outcome") for r in rows)
    critic_runs = sum(1 for r in rows if r.get("critic_run"))
    scored = sum(1 for r in rows if r.get("outcome") == "CRITIC_SCORED_ADVISORY")
    evidence: dict[str, Any] = {
        "artifact_type": "tournament_ollama_critic_router",
        "schema_version": "1.0.0",
        "recorded_at": _now(),
        "lane": "GOLD_FACTORY_ollama_critic_router_tournament_mvc",
        "authority": [
            "configs/vlm.yaml governance (role=qa_router_only, may_author_masks=false, may_approve_gold=false)",
            "src/maskfactory/vlm/router.py RoutingDecision (may_approve_gold hardcoded false)",
            "tools/gpu_sequencer.py ollama-vlm consumer",
        ],
        "honesty_rules": [
            "VLM is advisory critic/router only",
            "Never authors masks",
            "Never approves gold",
            "Never replaces multi-family agreement / never mutates MVC lifecycle status",
            "Source/DAZ/warehouse masks are never gold",
        ],
        "machine_roots": [str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in roots],
        "mvc_discovered": len(mvc_paths) if not args.limit else len(rows),
        "mvc_scored_attempted": len(rows),
        "critic_runs": critic_runs,
        "critic_scored_advisory": scored,
        "outcomes": dict(outcomes),
        "lifecycle_mutations": 0,
        "multi_family_agreement_replaced": False,
        "autonomous_certified_gold": 0,
        "vlm_model": config["models"]["primary_vlm"],
        "governance": {
            "role": "qa_router_only",
            "may_author_masks": False,
            "may_approve_gold": False,
            "may_clear_blocks": False,
        },
        "rows": rows,
        "blocker": None,
    }
    if len(rows) == 0:
        evidence["blocker"] = "zero_machine_verified_candidate_in_scoped_runs"
    elif critic_runs == 0:
        evidence["blocker"] = "mvc_present_but_no_critic_runs_completed"

    out = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    evidence["self_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(out.relative_to(REPO_ROOT)).replace("\\", "/"),
                "critic_runs": critic_runs,
                "critic_scored_advisory": scored,
                "mvc_attempted": len(rows),
                "outcomes": dict(outcomes),
                "blocker": evidence["blocker"],
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if critic_runs > 0 or len(rows) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
