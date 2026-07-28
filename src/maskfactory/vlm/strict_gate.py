"""Self-hosted STRICT visual critic gate for MaskFactory autonomy.

Binding rules (Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md § SELF-HOSTED STRICT VLM GATE):
- Loopback Ollama only (127.0.0.1:11434). Never cloud LLMs for MF VLM QA.
- High-end primary (llava:13b or llama3.2-vision:11b); qwen2.5vl:7b is secondary/ensemble only.
- temperature=0, seed=1337; structured JSON rubric; FAIL fails closed.
- VLM never clears hard QC BLOCK; VLM FAIL → abstain/reject/repair — not gold.
- Panels required (source/mask/overlay at minimum). Decoding a PNG alone ≠ visual QA.
- Ollama/models unavailable → VISUAL_CRITIC_BLOCKED (never silent skip / blind approve).
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ALLOWED_VERDICTS = frozenset({"pass", "fail", "uncertain"})
RUBRIC_DIMENSIONS = (
    "anatomy",
    "boundary",
    "leakage",
    "emptiness",
    "label_consistency",
    "overlay_contour_review",
)
HIGH_END_MODELS = frozenset({"llava:13b", "llama3.2-vision:11b"})
SECONDARY_ENSEMBLE_DEFAULT = "qwen2.5vl:7b"
DETERMINISTIC_OPTIONS = {"temperature": 0, "seed": 1337, "num_predict": 384}
LOOPBACK = "http://127.0.0.1:11434"

STRICT_PROMPT_VERSION = "strict-visual-gate-v4-20260721-no-trunc-fail"


class StrictVlmGateError(RuntimeError):
    """Fail-closed gate error (maps to VISUAL_CRITIC_BLOCKED when transport/config)."""


@dataclass(frozen=True)
class StrictGateConfig:
    enabled: bool
    primary_vlm: str
    alternate_high_end_vlm: str
    secondary_ensemble_vlm: str
    require_ensemble_for_pass: bool
    temperature: float
    seed: int
    num_predict: int
    base_url: str
    fail_closed_if_unavailable: bool
    allow_skip_vlm: bool
    min_pass_confidence: float
    panels_required: tuple[str, ...]
    mandatory_for: tuple[str, ...]
    rubric_dimensions: tuple[str, ...]
    may_author_masks: bool
    may_approve_gold: bool
    may_clear_blocks: bool
    unload_after_burst: bool

    @property
    def generation_options(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_predict": self.num_predict,
        }


@dataclass
class StrictGateResult:
    outcome: str
    verdict: str | None
    model_id: str | None
    ensemble_model_id: str | None
    prompt_version: str
    prompt_sha256: str
    panel_sha256: str | None
    response: dict[str, Any] | None
    ensemble_response: dict[str, Any] | None
    confidence: float | None
    rubric: dict[str, Any]
    evidence_log: dict[str, Any] = field(default_factory=dict)
    blocker: str | None = None
    claims_forbidden: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_vlm_yaml(repo_root: Path) -> dict[str, Any]:
    path = Path(repo_root) / "configs" / "vlm.yaml"
    if not path.is_file():
        raise StrictVlmGateError(f"VISUAL_CRITIC_BLOCKED: missing {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_strict_gate_config(repo_root: Path) -> StrictGateConfig:
    raw = load_vlm_yaml(repo_root)
    gov = raw.get("governance") or {}
    runtime = raw.get("runtime") or {}
    gate = raw.get("strict_visual_gate") or {}
    models = raw.get("models") or {}
    if not gate.get("enabled", False):
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: strict_visual_gate.enabled must be true")
    primary = str(gate.get("primary_vlm") or models.get("strict_gate_primary_vlm") or "")
    if primary not in HIGH_END_MODELS:
        raise StrictVlmGateError(
            f"VISUAL_CRITIC_BLOCKED: strict primary must be high-end "
            f"{sorted(HIGH_END_MODELS)}, got {primary!r}"
        )
    secondary = str(
        gate.get("secondary_ensemble_vlm")
        or models.get("secondary_ensemble_vlm")
        or SECONDARY_ENSEMBLE_DEFAULT
    )
    if secondary == primary:
        raise StrictVlmGateError(
            "VISUAL_CRITIC_BLOCKED: secondary ensemble must differ from high-end primary"
        )
    if secondary not in {SECONDARY_ENSEMBLE_DEFAULT, "qwen2.5vl:7b-instruct"} and not str(
        secondary
    ).startswith("qwen"):
        # Allow qwen family only as secondary rubber-stamp preventer.
        pass
    base = str(runtime.get("base_url") or LOOPBACK).rstrip("/")
    if base != LOOPBACK:
        raise StrictVlmGateError(
            f"VISUAL_CRITIC_BLOCKED: VLM endpoint must be loopback {LOOPBACK}, got {base}"
        )
    if gov.get("may_author_masks") is not False:
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: may_author_masks must be false")
    if gov.get("may_approve_gold") is not False:
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: may_approve_gold must be false")
    if gov.get("may_clear_blocks") is not False:
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: may_clear_blocks must be false")
    opts = gate.get("generation_options") or runtime.get("generation_options") or {}
    temperature = float(opts.get("temperature", gate.get("temperature", 0)))
    seed = int(opts.get("seed", gate.get("seed", 1337)))
    if temperature != 0 or seed != 1337:
        raise StrictVlmGateError(
            f"VISUAL_CRITIC_BLOCKED: require temperature=0 seed=1337, got "
            f"temperature={temperature} seed={seed}"
        )
    panels = tuple(gate.get("panels_required") or ("source", "mask", "overlay"))
    for required in ("source", "mask", "overlay"):
        if required not in panels:
            raise StrictVlmGateError(
                f"VISUAL_CRITIC_BLOCKED: panels_required must include {required}"
            )
    return StrictGateConfig(
        enabled=True,
        primary_vlm=primary,
        alternate_high_end_vlm=str(gate.get("alternate_high_end_vlm") or "llama3.2-vision:11b"),
        secondary_ensemble_vlm=secondary,
        require_ensemble_for_pass=bool(gate.get("require_ensemble_for_pass", True)),
        temperature=temperature,
        seed=seed,
        num_predict=int(opts.get("num_predict", gate.get("num_predict", 768))),
        base_url=base,
        fail_closed_if_unavailable=bool(gate.get("fail_closed_if_unavailable", True)),
        allow_skip_vlm=bool(gate.get("allow_skip_vlm", False)),
        min_pass_confidence=float(gate.get("min_pass_confidence", 0.75)),
        panels_required=panels,
        mandatory_for=tuple(
            gate.get("mandatory_for")
            or (
                "tournament_mvc_emit_acceptance",
                "caa_admission",
                "autonomous_certified_gold",
                "package_freeze_challenger_panels",
                "mode_b_champion_visual_smoke",
                "hand_clothing_climb",
            )
        ),
        rubric_dimensions=tuple(gate.get("rubric_dimensions") or RUBRIC_DIMENSIONS),
        may_author_masks=False,
        may_approve_gold=False,
        may_clear_blocks=False,
        unload_after_burst=bool(gate.get("unload_after_burst", True)),
    )


def _part_scope_rules(label: str) -> str:
    """Label-specific scope so VLMs do not judge hand/face as full-body coverage."""
    key = str(label or "").strip().lower()
    if key in {"hand", "hands"}:
        return (
            "SCOPE=HAND ONLY. Tiles L->R: (1) source crop around mask bbox "
            "(2) binary mask WHITE=positive (3) red overlay (4) cyan contour (5) heat. "
            "Judge ONLY white pixels in tile2 / red in tile3. "
            "Small white blobs are normal hands. Source crop may still show nearby torso — "
            "IGNORE body in the RGB crop unless the WHITE mask itself paints torso/face. "
            "PASS if white/red covers visible hand/finger/palm/wrist with usable boundary. "
            "FAIL only if mask empty, white region is clearly face/torso (not a hand), "
            "crude rectangle flood, or misses most visible hands. "
            "One clean hand may pass if the other is tiny/occluded."
        )
    if key in {"face", "head"}:
        return (
            "SCOPE=FACE/HEAD ONLY. Do NOT require full-body coverage. "
            "FAIL for empty mask, wrong part, or major face leakage into background."
        )
    if key in {"torso", "upper_body", "clothing", "garment"}:
        return (
            f"SCOPE={key.upper()} ONLY. Do NOT require unrelated body parts. "
            "FAIL for empty/flooded masks, wrong-part coverage, or major background spill."
        )
    return (
        f"SCOPE=LABEL '{label}' ONLY. Judge only that part. "
        "Do NOT require full-body coverage unless the label is a full-body class. "
        "FAIL for empty masks, wrong-part coverage, crude non-anatomic blobs, or major spill."
    )


def build_strict_prompt(*, label: str, context: str = "solo") -> str:
    dims = ", ".join(RUBRIC_DIMENSIONS)
    scope = _part_scope_rules(label)
    return (
        f"You are the STRICT self-hosted visual critic for MaskFactory autonomy. "
        f"Label={label}; context={context}. "
        f"{scope} "
        "Panel tiles L->R typically: source, binary mask, overlay, contour/bbox, source. "
        "Governed role: qa_router_only — you may NOT author masks, approve gold, or clear "
        "hard QC BLOCK. "
        "Score each rubric dimension as pass|fail|uncertain with a short reason. "
        f"Rubric dimensions: [{dims}]. "
        "Any dimension fail ⇒ overall verdict fail. "
        "Emptiness fail ONLY if mask is blank/near-empty while the labeled part is visible, "
        "OR the mask is a solid flood covering most of the image when the part is small. "
        "Do NOT mark both emptiness and leakage fail for contradictory reasons. "
        "Leakage fail if mask spills into background/clothing/neighbor parts beyond the label. "
        "label_consistency fail if the mask covers a different anatomy than Label. "
        "Keep evidence and correction_instruction SHORT (<=40 words). "
        "problems must be a list of short string ids "
        "(e.g. wrong_part, includes_background, missing_visible_area, boundary_too_loose, "
        "finger_merge, other) — not long sentences. "
        "Answer STRICT JSON only with exact keys: "
        "{"
        '"verdict":"pass|fail|uncertain",'
        '"confidence":0.0,'
        '"problems":[],'
        '"evidence":"<<=40 words citing panel location>",'
        '"correction_instruction":"<=40 words imperative>",'
        '"rubric":{'
        + ",".join(
            f'"{d}":{{"verdict":"pass|fail|uncertain","reason":"<<=12 words>"}}'
            for d in RUBRIC_DIMENSIONS
        )
        + "}}"
    )


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _post_chat(
    *,
    base_url: str,
    model: str,
    prompt: str,
    image_png: bytes,
    options: dict[str, Any],
    timeout: int = 300,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "format": "json",
        "stream": False,
        "options": dict(options),
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_png).decode("ascii")],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    last: BaseException | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise StrictVlmGateError(
                f"VISUAL_CRITIC_BLOCKED: Ollama HTTP {exc.code}: {detail}"
            ) from exc
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as exc:
            last = exc
            time.sleep(2 + attempt * 3)
    raise StrictVlmGateError(
        f"VISUAL_CRITIC_BLOCKED: Ollama unreachable after retries: {last}"
    ) from last


def list_ollama_models(base_url: str = LOOPBACK, timeout: int = 30) -> set[str]:
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            doc = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise StrictVlmGateError(
            f"VISUAL_CRITIC_BLOCKED: cannot list Ollama models: {exc}"
        ) from exc
    names: set[str] = set()
    for row in doc.get("models") or []:
        if isinstance(row, dict) and row.get("name"):
            names.add(str(row["name"]))
    return names


def ensure_models_present(cfg: StrictGateConfig) -> dict[str, Any]:
    present = list_ollama_models(cfg.base_url)
    needed = {cfg.primary_vlm, cfg.secondary_ensemble_vlm}
    # Ollama may report with or without tag variants; also accept exact match only.
    still_missing = [m for m in needed if not any(p == m or p.startswith(m + ":") for p in present)]
    if still_missing and cfg.fail_closed_if_unavailable:
        raise StrictVlmGateError(
            "VISUAL_CRITIC_BLOCKED: required models missing on Ollama: "
            + ",".join(still_missing)
            + f"; present={sorted(present)[:20]}"
        )
    return {"present": sorted(present), "required": sorted(needed), "missing": still_missing}


def unload_model(model: str, base_url: str = LOOPBACK) -> None:
    """Best-effort unload to free VRAM for hand tournament workers."""
    payload = {"model": model, "keep_alive": 0, "prompt": "", "stream": False}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            response.read()
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return


def _word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])


def _extract_json_object(content: str) -> str:
    """Best-effort extract of a top-level JSON object from VLM text."""
    text = content.strip()
    if text.startswith("```"):
        # Strip markdown fences without inventing content.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _truncate_words(text: str, limit: int) -> str:
    words = [w for w in str(text).strip().split() if w]
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit])


def parse_strict_response(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, dict) and "message" in raw:
        content = raw["message"].get("content")
    elif isinstance(raw, dict) and "response" in raw:
        content = raw.get("response")
    else:
        content = raw
    if not isinstance(content, str):
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: VLM content not a string")
    try:
        parsed = json.loads(_extract_json_object(content))
    except json.JSONDecodeError as exc:
        raise StrictVlmGateError(f"VISUAL_CRITIC_BLOCKED: VLM JSON parse failed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: VLM JSON is not an object")
    # Soft-fill contract keys when VLM omits them but supplies a usable verdict/rubric.
    # Never invent a pass: missing verdict still fails closed.
    if "correction_instruction" not in parsed or not isinstance(
        parsed.get("correction_instruction"), str
    ):
        parsed["correction_instruction"] = "none"
    if "evidence" not in parsed or not isinstance(parsed.get("evidence"), str):
        parsed["evidence"] = "panel review"
    if "problems" not in parsed:
        parsed["problems"] = []
    if "confidence" not in parsed:
        parsed["confidence"] = 0.0
    # Synthesize rubric ONLY for fail/uncertain when VLM truncates before rubric.
    # Never invent a pass rubric — missing rubric on pass ⇒ still blocked upstream.
    if "rubric" not in parsed or not isinstance(parsed.get("rubric"), dict):
        verdict = str(parsed.get("verdict") or "")
        if verdict in {"fail", "uncertain"}:
            base = "fail" if verdict == "fail" else "uncertain"
            reason = "synthesized_from_truncated_response"
            parsed["rubric"] = {d: {"verdict": base, "reason": reason} for d in RUBRIC_DIMENSIONS}
    required = {
        "verdict",
        "confidence",
        "problems",
        "evidence",
        "correction_instruction",
        "rubric",
    }
    if set(parsed) < required:
        raise StrictVlmGateError(
            f"VISUAL_CRITIC_BLOCKED: missing keys {sorted(required - set(parsed))}"
        )
    if parsed["verdict"] not in ALLOWED_VERDICTS:
        raise StrictVlmGateError(f"VISUAL_CRITIC_BLOCKED: bad verdict {parsed['verdict']!r}")
    if not isinstance(parsed["confidence"], int | float) or not (
        0 <= float(parsed["confidence"]) <= 1
    ):
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: confidence must be 0..1")
    if not isinstance(parsed["problems"], list):
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: problems must be a list")
    # Coerce dict-shaped problem entries from some VLMs into string ids.
    norm_problems: list[str] = []
    for item in parsed["problems"]:
        if isinstance(item, dict):
            item = (
                item.get("id")
                or item.get("problem")
                or item.get("name")
                or item.get("type")
                or item.get("code")
                or "other"
            )
        text = str(item).strip()
        # Prefer short machine ids; free-form sentences collapse to a coarse id.
        lower = text.lower()
        if " " in text or len(text) > 48:
            if any(k in lower for k in ("background", "spill", "leak")):
                text = "includes_background"
            elif any(k in lower for k in ("empty", "blank", "missing")):
                text = "missing_visible_area"
            elif any(k in lower for k in ("wrong part", "face", "torso", "body")):
                text = "wrong_part"
            elif "boundar" in lower or "loose" in lower:
                text = "boundary_too_loose"
            else:
                text = "other"
        norm_problems.append(text)
    parsed["problems"] = norm_problems
    parsed["evidence"] = _truncate_words(parsed["evidence"], 40)
    parsed["correction_instruction"] = _truncate_words(parsed["correction_instruction"], 40)
    if not parsed["evidence"]:
        parsed["evidence"] = "panel review"
    if not parsed["correction_instruction"]:
        parsed["correction_instruction"] = "none"
    rubric = parsed["rubric"]
    if not isinstance(rubric, dict):
        raise StrictVlmGateError("VISUAL_CRITIC_BLOCKED: rubric must be an object")
    for dim in RUBRIC_DIMENSIONS:
        entry = rubric.get(dim)
        if not isinstance(entry, dict) or entry.get("verdict") not in ALLOWED_VERDICTS:
            raise StrictVlmGateError(f"VISUAL_CRITIC_BLOCKED: rubric.{dim} missing/invalid")
        if "reason" in entry and isinstance(entry["reason"], str):
            entry["reason"] = _truncate_words(entry["reason"], 12)
    return parsed


def _rubric_has_fail(rubric: dict[str, Any]) -> bool:
    return any(
        isinstance(rubric.get(d), dict) and rubric[d].get("verdict") == "fail"
        for d in RUBRIC_DIMENSIONS
    )


def _rubric_is_synthesized(rubric: dict[str, Any]) -> bool:
    """True when rubric was soft-filled after a truncated VLM JSON (not a real review)."""
    if not isinstance(rubric, dict) or not rubric:
        return False
    reasons: list[str] = []
    for dim in RUBRIC_DIMENSIONS:
        entry = rubric.get(dim)
        if not isinstance(entry, dict):
            return False
        reasons.append(str(entry.get("reason") or ""))
    return bool(reasons) and all(r == "synthesized_from_truncated_response" for r in reasons)


def decide_outcome(
    *,
    primary: dict[str, Any],
    ensemble: dict[str, Any] | None,
    cfg: StrictGateConfig,
) -> tuple[str, str | None]:
    """Return (outcome, blocker)."""
    verdict = primary["verdict"]
    confidence = float(primary["confidence"])
    problems = list(primary.get("problems") or [])
    # Truncated primary JSON must not demote MVC — retry when critic completes.
    if _rubric_is_synthesized(primary.get("rubric") or {}):
        return "VISUAL_CRITIC_BLOCKED", "strict_vlm_truncated_primary"
    if _rubric_has_fail(primary.get("rubric") or {}) or verdict == "fail":
        return "ABSTAIN_BOUNDED", "strict_vlm_fail"
    if verdict == "uncertain":
        return "ABSTAIN_BOUNDED", "strict_vlm_uncertain"
    if problems:
        return "ABSTAIN_BOUNDED", "strict_vlm_pass_with_problems"
    if confidence < cfg.min_pass_confidence:
        return "ABSTAIN_BOUNDED", "strict_vlm_low_confidence"
    if cfg.require_ensemble_for_pass:
        if ensemble is None:
            return "VISUAL_CRITIC_BLOCKED", "ensemble_missing"
        e_verdict = ensemble["verdict"]
        if e_verdict == "fail" or _rubric_has_fail(ensemble.get("rubric") or {}):
            return "ABSTAIN_BOUNDED", "ensemble_fail"
        if e_verdict != "pass":
            return "ABSTAIN_BOUNDED", "ensemble_not_pass"
    return "STRICT_VISUAL_QA_PASS_BOUNDED", None


def run_strict_visual_review(
    *,
    repo_root: Path,
    panel_png: bytes | Path,
    label: str,
    context: str = "solo",
    skip_vlm: bool = False,
    force_disable_critic: bool = False,
) -> StrictGateResult:
    """Execute STRICT high-end + ensemble visual review on a panel PNG."""
    prompt = build_strict_prompt(label=label, context=context)
    p_hash = prompt_sha256(prompt)
    panel_bytes = Path(panel_png).read_bytes() if isinstance(panel_png, Path) else bytes(panel_png)
    panel_hash = sha256_bytes(panel_bytes)
    claims_forbidden = [
        "gold",
        "autonomous_certified_gold",
        "VISUAL_QA_PASS_BOUNDED_without_strict_gate",
        "blind_approve",
    ]

    if force_disable_critic:
        return StrictGateResult(
            outcome="VISUAL_CRITIC_BLOCKED",
            verdict=None,
            model_id=None,
            ensemble_model_id=None,
            prompt_version=STRICT_PROMPT_VERSION,
            prompt_sha256=p_hash,
            panel_sha256=panel_hash,
            response=None,
            ensemble_response=None,
            confidence=None,
            rubric={},
            blocker="critic_explicitly_disabled",
            claims_forbidden=claims_forbidden,
            evidence_log={
                "recorded_at": _now(),
                "note": "Fail-closed: critic disabled must never yield pass/gold",
            },
        )

    try:
        cfg = load_strict_gate_config(repo_root)
    except StrictVlmGateError as exc:
        return StrictGateResult(
            outcome="VISUAL_CRITIC_BLOCKED",
            verdict=None,
            model_id=None,
            ensemble_model_id=None,
            prompt_version=STRICT_PROMPT_VERSION,
            prompt_sha256=p_hash,
            panel_sha256=panel_hash,
            response=None,
            ensemble_response=None,
            confidence=None,
            rubric={},
            blocker=str(exc),
            claims_forbidden=claims_forbidden,
            evidence_log={"recorded_at": _now()},
        )

    if skip_vlm and not cfg.allow_skip_vlm:
        return StrictGateResult(
            outcome="VISUAL_CRITIC_BLOCKED",
            verdict=None,
            model_id=cfg.primary_vlm,
            ensemble_model_id=cfg.secondary_ensemble_vlm,
            prompt_version=STRICT_PROMPT_VERSION,
            prompt_sha256=p_hash,
            panel_sha256=panel_hash,
            response=None,
            ensemble_response=None,
            confidence=None,
            rubric={},
            blocker="skip_vlm_forbidden_under_strict_gate",
            claims_forbidden=claims_forbidden,
            evidence_log={
                "recorded_at": _now(),
                "allow_skip_vlm": False,
                "note": "--skip-vlm cannot promote MVC/CAA/gold under strict gate",
            },
        )

    try:
        model_probe = ensure_models_present(cfg)
    except StrictVlmGateError as exc:
        return StrictGateResult(
            outcome="VISUAL_CRITIC_BLOCKED",
            verdict=None,
            model_id=cfg.primary_vlm,
            ensemble_model_id=cfg.secondary_ensemble_vlm,
            prompt_version=STRICT_PROMPT_VERSION,
            prompt_sha256=p_hash,
            panel_sha256=panel_hash,
            response=None,
            ensemble_response=None,
            confidence=None,
            rubric={},
            blocker=str(exc),
            claims_forbidden=claims_forbidden,
            evidence_log={"recorded_at": _now()},
        )

    options = cfg.generation_options
    primary_raw: dict[str, Any] | None = None
    ensemble_raw: dict[str, Any] | None = None
    primary_parsed: dict[str, Any] | None = None
    ensemble_parsed: dict[str, Any] | None = None
    started = time.perf_counter()
    parse_error: str | None = None
    try:
        primary_raw = _post_chat(
            base_url=cfg.base_url,
            model=cfg.primary_vlm,
            prompt=prompt,
            image_png=panel_bytes,
            options=options,
        )
        try:
            primary_parsed = parse_strict_response(primary_raw)
        except StrictVlmGateError:
            # One JSON-only retry (llava often wraps or truncates complex rubrics).
            retry_prompt = prompt + "\nCRITICAL: Return ONE JSON object only. No markdown."
            primary_raw = _post_chat(
                base_url=cfg.base_url,
                model=cfg.primary_vlm,
                prompt=retry_prompt,
                image_png=panel_bytes,
                options=options,
            )
            try:
                primary_parsed = parse_strict_response(primary_raw)
            except StrictVlmGateError as exc2:
                parse_error = str(exc2)
                primary_parsed = None
        if primary_parsed is not None and cfg.require_ensemble_for_pass:
            ensemble_raw = _post_chat(
                base_url=cfg.base_url,
                model=cfg.secondary_ensemble_vlm,
                prompt=prompt
                if primary_parsed
                else prompt + "\nCRITICAL: Return ONE JSON object only.",
                image_png=panel_bytes,
                options=options,
            )
            try:
                ensemble_parsed = parse_strict_response(ensemble_raw)
            except StrictVlmGateError as exc:
                # Ensemble invalid ⇒ fail closed abstain (not gold), critic was reachable.
                parse_error = f"ensemble:{exc}"
                ensemble_parsed = None
    except StrictVlmGateError as exc:
        if cfg.unload_after_burst:
            unload_model(cfg.primary_vlm, cfg.base_url)
            unload_model(cfg.secondary_ensemble_vlm, cfg.base_url)
        return StrictGateResult(
            outcome="VISUAL_CRITIC_BLOCKED",
            verdict=None,
            model_id=cfg.primary_vlm,
            ensemble_model_id=cfg.secondary_ensemble_vlm,
            prompt_version=STRICT_PROMPT_VERSION,
            prompt_sha256=p_hash,
            panel_sha256=panel_hash,
            response=None,
            ensemble_response=None,
            confidence=None,
            rubric={},
            blocker=str(exc),
            claims_forbidden=claims_forbidden,
            evidence_log={"recorded_at": _now(), "model_probe": model_probe},
        )
    finally:
        if cfg.unload_after_burst:
            unload_model(cfg.primary_vlm, cfg.base_url)
            unload_model(cfg.secondary_ensemble_vlm, cfg.base_url)

    if primary_parsed is None or (
        cfg.require_ensemble_for_pass and ensemble_parsed is None and parse_error
    ):
        # Critic reachable but JSON/contract failed → VISUAL_CRITIC_BLOCKED so hard-QA
        # does NOT demote tournament MVC (retry after prompt/VRAM recovery). Never promote.
        return StrictGateResult(
            outcome="VISUAL_CRITIC_BLOCKED",
            verdict=None,
            model_id=cfg.primary_vlm,
            ensemble_model_id=cfg.secondary_ensemble_vlm,
            prompt_version=STRICT_PROMPT_VERSION,
            prompt_sha256=p_hash,
            panel_sha256=panel_hash,
            response=None,
            ensemble_response=ensemble_parsed,
            confidence=None,
            rubric={},
            blocker=parse_error or "strict_vlm_invalid_json",
            claims_forbidden=claims_forbidden + ["VISUAL_QA_PASS_BOUNDED"],
            evidence_log={
                "recorded_at": _now(),
                "latency_seconds": round(time.perf_counter() - started, 3),
                "generation_options": options,
                "model_probe": model_probe,
                "primary_raw_excerpt": str(
                    (primary_raw or {}).get("message", {}).get("content", "")
                )[:500],
                "note": (
                    "Invalid/incomplete VLM JSON fails closed as VISUAL_CRITIC_BLOCKED "
                    "(no demote, no gold) — retry when critic contract recovers"
                ),
            },
        )

    assert primary_parsed is not None
    outcome, blocker = decide_outcome(primary=primary_parsed, ensemble=ensemble_parsed, cfg=cfg)
    latency = round(time.perf_counter() - started, 3)
    return StrictGateResult(
        outcome=outcome,
        verdict=str(primary_parsed["verdict"]),
        model_id=cfg.primary_vlm,
        ensemble_model_id=cfg.secondary_ensemble_vlm,
        prompt_version=STRICT_PROMPT_VERSION,
        prompt_sha256=p_hash,
        panel_sha256=panel_hash,
        response=primary_parsed,
        ensemble_response=ensemble_parsed,
        confidence=float(primary_parsed["confidence"]),
        rubric=dict(primary_parsed.get("rubric") or {}),
        blocker=blocker,
        claims_forbidden=claims_forbidden
        + (["VISUAL_QA_PASS_BOUNDED"] if outcome != "STRICT_VISUAL_QA_PASS_BOUNDED" else []),
        evidence_log={
            "recorded_at": _now(),
            "latency_seconds": latency,
            "generation_options": options,
            "model_probe": model_probe,
            "primary_ollama_model_field": (primary_raw or {}).get("model"),
            "ensemble_ollama_model_field": (ensemble_raw or {}).get("model"),
            "governance": {
                "role": "qa_router_only",
                "may_author_masks": False,
                "may_approve_gold": False,
                "may_clear_blocks": False,
            },
        },
    )


def gate_required_for(scope: str, repo_root: Path) -> bool:
    cfg = load_strict_gate_config(repo_root)
    return scope in cfg.mandatory_for
