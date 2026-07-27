"""Deterministic inputs and strict response parsing for live critic calibration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .calibration_corpus import (
    PANEL_KEYS,
    validate_calibration_corpus,
    validate_calibration_corpus_files,
)
from .critic_catalog import canonical_sha256, validate_catalog

CHECK_KEYS = (
    "anatomy",
    "boundary",
    "leakage",
    "missing_area",
    "label_consistency",
    "ownership",
    "laterality",
    "topology",
    "occlusion",
    "protected_regions",
)
CHECK_VALUES = frozenset({"pass", "defect", "uncertain"})
RESPONSE_KEYS = frozenset(
    {"verdict", "defect_type", "cited_context_tags", "checks", "cited_evidence_panels"}
)
VERDICTS = frozenset({"pass", "defect", "abstain"})
EVIDENCE_BOARD_LAYOUT = (
    "source",
    "binary_mask",
    "overlay",
    "contour",
    "full_context",
    "uncertainty_zoom",
)
PROMPT_VERSION = "maskfactory-live-critic-calibration-v3-single-board-explicit-checks"
PROMPT_TEMPLATE = """/no_think
You are evaluating one proposed binary mask for the exact target below.
The one evidence board has six explicitly labeled tiles. Top row: SOURCE,
BINARY_MASK (white is selected), OVERLAY (red is selected). Bottom row:
CONTOUR, FULL_CONTEXT, UNCERTAINTY_ZOOM. Every tile belongs to this exact record.

Target label: {label_id}
Owner person index: {person_index}
Expected presence: {expected_presence}
Allowed target ROI (source xyxy): {allowed_roi}
Inclusion rule: {inclusion_rule}
Exclusion rule: {exclusion_rule}
Explicitly excluded labels: {excluded_labels}
Protected region labels: {protected_labels}
Allowed context tags: {context_tags}
Allowed defect types: {defect_taxonomy}

Use this balanced decision sequence:
1. Confirm that every tile belongs to this exact target, owner, and ROI. If
   that cannot be established from the supplied evidence, abstain.
2. Locate the declared target in SOURCE and FULL_CONTEXT. Then compare the
   white BINARY_MASK, red OVERLAY, CONTOUR, and UNCERTAINTY_ZOOM directly with those
   visible target pixels. A mask over the whole person, a different body part,
   the other person, the opposite side, background, or clothing is a defect
   even when its boundary is clean.
3. Record every required check separately: anatomy, boundary, leakage,
   missing_area, label_consistency, ownership, laterality, topology, occlusion,
   and protected_regions. Do not copy one blanket status into all checks without
   comparing the relevant tiles.
4. Report a defect only when a visible localized error contradicts the target
   contract. The defect taxonomy is an output vocabulary, not a checklist of
   defects that must be found. Do not invent microscopic, hidden, amodal, or
   unsupported errors.
5. If the evidence is sufficient and no visible contract violation exists,
   the correct verdict is pass. Valid masks are expected in this qualification
   and rejecting every case is a failed reviewer, not a conservative success.

Do not infer anything outside this evidence board and target. Left/right always
means the character's anatomical perspective; screen position alone is not
evidence of side. The cyan rectangle on SOURCE and FULL_CONTEXT is the allowed
target ROI. Return only one JSON object with exactly these keys:
{{"verdict":"pass|defect|abstain","defect_type":null_or_allowed_type,
"cited_context_tags":["one or more exact allowed tags"],
"checks":{{"anatomy":"pass|defect|uncertain","boundary":"pass|defect|uncertain",
"leakage":"pass|defect|uncertain","missing_area":"pass|defect|uncertain",
"label_consistency":"pass|defect|uncertain","ownership":"pass|defect|uncertain",
"laterality":"pass|defect|uncertain","topology":"pass|defect|uncertain",
"occlusion":"pass|defect|uncertain","protected_regions":"pass|defect|uncertain"}},
"cited_evidence_panels":["two or more exact panel labels"]}}
Use pass only when the exact mask is valid. Use defect with exactly one allowed
defect type for the primary visible error. A pass requires every check to pass;
a defect requires at least one defect check; abstain requires at least one
uncertain check. Cite at least two panels that support the verdict.
"""
PROMPT_SHA256 = hashlib.sha256(f"{PROMPT_VERSION}\n{PROMPT_TEMPLATE}".encode("utf-8")).hexdigest()
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class LiveCalibrationError(ValueError):
    """A live calibration input, response, or binding is invalid."""


def build_case_prompt(case: Mapping[str, Any], defect_taxonomy: Sequence[str]) -> str:
    """Render the versioned prompt without leaking the expected answer."""

    contract = case["target_contract"]
    target = contract["target"]
    if contract["schema_version"] == "2.0.0":
        inclusion_rule = "; ".join(target["inclusions"])
        exclusion_rule = "; ".join(target["exclusions"])
        excluded_labels = "; ".join(target["exclusions"])
    else:
        inclusion_rule = target["inclusion_rule"]
        exclusion_rule = target["exclusion_rule"]
        excluded_labels = ", ".join(contract["excluded_labels"]) or "none"
    return PROMPT_TEMPLATE.format(
        label_id=target["label_id"],
        person_index=contract["owner"]["person_index"],
        expected_presence=target.get("expected_presence", target.get("expected_state")),
        allowed_roi=target["allowed_roi_xyxy"],
        inclusion_rule=inclusion_rule,
        exclusion_rule=exclusion_rule,
        excluded_labels=excluded_labels,
        protected_labels=", ".join(
            str(region["label_id"]) for region in contract["protected_regions"]
        )
        or "none",
        context_tags=", ".join(case["context_tags"]),
        defect_taxonomy=", ".join(defect_taxonomy),
    )


def critic_response_schema(
    case: Mapping[str, Any], defect_taxonomy: Sequence[str]
) -> dict[str, Any]:
    """Return an exact per-case JSON schema for structured-output backends."""

    return {
        "name": "maskfactory_critic_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": sorted(VERDICTS)},
                "defect_type": {
                    "anyOf": [
                        {"type": "string", "enum": list(defect_taxonomy)},
                        {"type": "null"},
                    ]
                },
                "cited_context_tags": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "enum": list(case["context_tags"])},
                },
                "checks": {
                    "type": "object",
                    "properties": {
                        key: {"type": "string", "enum": sorted(CHECK_VALUES)} for key in CHECK_KEYS
                    },
                    "required": list(CHECK_KEYS),
                    "additionalProperties": False,
                },
                "cited_evidence_panels": {
                    "type": "array",
                    "minItems": 2,
                    "items": {"type": "string", "enum": list(EVIDENCE_BOARD_LAYOUT)},
                },
            },
            "required": sorted(RESPONSE_KEYS),
            "additionalProperties": False,
        },
    }


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```json"):
        value = value[len("```json") :]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return value.strip()


def parse_critic_response(
    raw: str, case: Mapping[str, Any], defect_taxonomy: Sequence[str]
) -> dict[str, Any]:
    """Parse an exact verdict and reject free-form, widened, or contradictory output."""

    try:
        value = json.loads(_strip_json_fence(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise LiveCalibrationError("critic response is not one JSON object") from exc
    if not isinstance(value, Mapping) or set(value) != RESPONSE_KEYS:
        raise LiveCalibrationError("critic response fields are incomplete or unknown")
    verdict = value["verdict"]
    defect_type = value["defect_type"]
    cited = value["cited_context_tags"]
    checks = value["checks"]
    cited_panels = value["cited_evidence_panels"]
    if verdict not in VERDICTS:
        raise LiveCalibrationError("critic verdict is invalid")
    if verdict == "defect":
        if defect_type not in defect_taxonomy:
            raise LiveCalibrationError("critic defect type is invalid")
    elif defect_type is not None:
        raise LiveCalibrationError("non-defect critic verdict carries a defect type")
    if (
        not isinstance(cited, Sequence)
        or isinstance(cited, (str, bytes))
        or not cited
        or len(set(cited)) != len(cited)
        or not set(cited) <= set(case["context_tags"])
    ):
        raise LiveCalibrationError("critic cited contexts are empty, duplicated, or widened")
    if (
        not isinstance(checks, Mapping)
        or set(checks) != set(CHECK_KEYS)
        or any(status not in CHECK_VALUES for status in checks.values())
    ):
        raise LiveCalibrationError("critic checks are incomplete, widened, or invalid")
    if verdict == "pass" and set(checks.values()) != {"pass"}:
        raise LiveCalibrationError("pass verdict carries a non-pass check")
    if verdict == "defect" and "defect" not in checks.values():
        raise LiveCalibrationError("defect verdict lacks a defect check")
    if verdict == "abstain" and "uncertain" not in checks.values():
        raise LiveCalibrationError("abstain verdict lacks an uncertain check")
    if (
        not isinstance(cited_panels, Sequence)
        or isinstance(cited_panels, (str, bytes))
        or len(cited_panels) < 2
        or len(set(cited_panels)) != len(cited_panels)
        or not set(cited_panels) <= set(EVIDENCE_BOARD_LAYOUT)
    ):
        raise LiveCalibrationError("critic panel citations are insufficient or invalid")
    return {
        "verdict": str(verdict),
        "defect_type": defect_type,
        "cited_context_tags": list(cited),
        "checks": dict(checks),
        "cited_evidence_panels": list(cited_panels),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_case_composites(
    case: Mapping[str, Any], corpus_root: Path, output_root: Path
) -> list[dict[str, Any]]:
    """Create one deterministic labeled board retaining every frozen panel."""

    if set(case["panel_files"]) != PANEL_KEYS:
        raise LiveCalibrationError("calibration case panel files are incomplete")
    case_root = Path(output_root) / str(case["case_id"])
    case_root.mkdir(parents=True, exist_ok=True)
    paths = [
        (Path(corpus_root) / case["panel_files"][name]).resolve() for name in EVIDENCE_BOARD_LAYOUT
    ]
    images: list[Image.Image] = []
    destination = case_root / "evidence_board.png"
    try:
        for path in paths:
            image = Image.open(path)
            image.load()
            images.append(image.convert("RGB"))
        tile_width, tile_height, header_height = 512, 768, 28
        sheet = Image.new(
            "RGB", (tile_width * 3, (tile_height + header_height) * 2), color=(0, 0, 0)
        )
        draw = ImageDraw.Draw(sheet)
        for index, (name, image) in enumerate(zip(EVIDENCE_BOARD_LAYOUT, images, strict=True)):
            row, column = divmod(index, 3)
            x0 = column * tile_width
            y0 = row * (tile_height + header_height)
            panel = image.copy()
            if name in {"source", "full_context"}:
                roi = tuple(
                    int(value) for value in case["target_contract"]["target"]["allowed_roi_xyxy"]
                )
                ImageDraw.Draw(panel).rectangle(roi, outline=(0, 255, 255), width=3)
            panel.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
            paste_x = x0 + (tile_width - panel.width) // 2
            paste_y = y0 + header_height + (tile_height - panel.height) // 2
            draw.text((x0 + 5, y0 + 6), name.upper(), fill=(255, 255, 255))
            sheet.paste(panel, (paste_x, paste_y))
            panel.close()
        sheet.save(destination, format="PNG", optimize=False, compress_level=9)
        sheet.close()
    finally:
        for image in images:
            image.close()
    return [
        {
            "index": 1,
            "panel_names": list(EVIDENCE_BOARD_LAYOUT),
            "path": destination,
            "sha256": _sha256_file(destination),
            "bytes": destination.stat().st_size,
        }
    ]


def build_prediction(
    *,
    case: Mapping[str, Any],
    parsed: Mapping[str, Any] | None,
    raw_response: str,
    replay_response: str,
    latency_ms: float,
    peak_vram_bytes: int,
) -> dict[str, Any]:
    """Build one fail-closed qualification row from two exact live responses."""

    schema_valid = parsed is not None
    if parsed is None:
        verdict = "abstain"
        defect_type = None
        cited: list[str] = []
        checks: dict[str, str] = {key: "uncertain" for key in CHECK_KEYS}
        cited_panels: list[str] = []
    else:
        verdict = parsed["verdict"]
        defect_type = parsed["defect_type"]
        cited = list(parsed["cited_context_tags"])
        checks = dict(parsed["checks"])
        cited_panels = list(parsed["cited_evidence_panels"])
    canonical_response = (
        json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        if parsed is not None
        else raw_response
    )
    return {
        "case_id": case["case_id"],
        "target_contract_sha256": case["target_contract"]["contract_sha256"],
        "panel_set_sha256": case["panel_set_sha256"],
        "verdict": verdict,
        "defect_type": defect_type,
        "cited_context_tags": cited,
        "checks": checks,
        "cited_evidence_panels": cited_panels,
        "schema_valid": schema_valid,
        "latency_ms": float(latency_ms),
        "peak_vram_bytes": int(peak_vram_bytes),
        "response_sha256": hashlib.sha256(canonical_response.encode("utf-8")).hexdigest(),
        "deterministic_replay": raw_response == replay_response,
    }


def build_qualification_evidence(
    *,
    corpus: Mapping[str, Any],
    catalog: Mapping[str, Any],
    role_id: str,
    model_id: str,
    runtime_sha256: str,
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind live predictions to one exact catalog model, runtime, corpus, and hardware."""

    validate_calibration_corpus(corpus)
    validate_catalog(catalog)
    models = {str(model["model_id"]): model for model in catalog["models"]}
    model = models.get(model_id)
    if model is None or role_id not in model["candidate_roles"]:
        raise LiveCalibrationError("model is not a candidate for the requested role")
    if not isinstance(runtime_sha256, str) or SHA256.fullmatch(runtime_sha256) is None:
        raise LiveCalibrationError("runtime hash is invalid")
    evidence = {
        "schema_version": "1.0.0",
        "role_id": role_id,
        "model_id": model_id,
        "family_id": model["family_id"],
        "revision": model["revision"],
        "quantization": model["quantization"],
        "artifact_tree_sha256": model["artifact_sha256"],
        "prompt_sha256": PROMPT_SHA256,
        "runtime_sha256": runtime_sha256,
        "corpus_sha256": corpus["corpus_sha256"],
        "hardware": {
            "gpu_name": catalog["current_hardware"]["gpu_name"],
            "gpu_count": catalog["current_hardware"]["gpu_count"],
            "vram_bytes": catalog["current_hardware"]["vram_bytes_per_gpu"],
        },
        "predictions": [dict(row) for row in predictions],
    }
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def validate_live_calibration_inputs(manifest: Mapping[str, Any], corpus_root: Path) -> None:
    """Public preflight used by the live runner before any model is loaded."""

    validate_calibration_corpus_files(manifest, corpus_root)
