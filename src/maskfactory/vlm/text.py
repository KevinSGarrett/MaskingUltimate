"""Strict local text-LLM duties for weekly failure mining."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol


class TextLlmError(RuntimeError):
    """The governed local text model returned incomplete or invalid evidence."""


class TextClient(Protocol):
    def generate(
        self,
        *,
        model: str,
        prompt: str,
        images: tuple[Path, ...] = (),
        options: dict | None = None,
    ) -> str: ...


_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
ALLOWED_THEMES = frozenset(
    {
        "hands_fingers",
        "hair_boundary",
        "occlusion_contact",
        "left_right",
        "human_correction",
        "semantic_qc",
        "general_boundary",
    }
)
ALLOWED_COVERAGE_TARGETS = frozenset(
    {
        "front",
        "back",
        "left_profile",
        "right_profile",
        "left_3_4",
        "right_3_4",
        "arms_raised",
        "arms_down",
        "arms_crossed",
        "seated_or_crouched",
        "lying",
        "walking",
        "leg_overlap",
        "solo",
        "duo",
        "small_group",
        "hands_visible",
        "feet_visible",
        "hand_body_contact",
        "hair_occlusion",
        "clothing_boundary",
        "bare_skin_dominant",
        "tight_clothing",
        "loose_clothing",
        "back_visible",
        "fingers_spread",
        "fingers_merged",
        "props_present",
    }
)


def cluster_failure_reasons(
    reasons: tuple[str, ...],
    *,
    client: TextClient,
    model: str,
    prompt_version: str,
    output_path: Path,
) -> dict[str, str]:
    """Cluster every distinct reason with one strict retry and write audit evidence."""
    unique = tuple(sorted(set(reasons)))
    if any(not _SLUG.fullmatch(reason) for reason in unique):
        raise TextLlmError("failure reasons must be canonical snake_case slugs")
    if not unique:
        document = {
            "schema_version": "1.0.0",
            "model": model,
            "prompt_version": prompt_version,
            "prompt_sha256": None,
            "input_reasons": [],
            "clusters": {},
            "coverage_targets": [],
            "weekly_summary": "No unresolved failure reasons were available to cluster.",
            "model_called": False,
        }
        _write_evidence(output_path, document)
        return {}
    prompt = _prompt(unique)
    parsed = None
    raw = ""
    for attempt in range(2):
        raw = client.generate(
            model=model,
            prompt=(
                prompt
                if attempt == 0
                else prompt + "\nYour prior response was invalid. Return the exact JSON shape only."
            ),
            images=(),
            options={"temperature": 0, "seed": 1337},
        )
        parsed = _parse(raw, unique)
        if parsed is not None:
            break
    if parsed is None:
        raise TextLlmError("local text LLM returned invalid clustering JSON after one retry")
    document = {
        "schema_version": "1.0.0",
        "model": model,
        "prompt_version": prompt_version,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "input_reasons": list(unique),
        **parsed,
        "model_called": True,
        "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }
    _write_evidence(output_path, document)
    return dict(parsed["clusters"])


def _prompt(reasons: tuple[str, ...]) -> str:
    cluster_template = {reason: "choose_one_allowed_theme" for reason in reasons}
    return (
        "You are MaskFactory's local failure-mining analyst. Group every supplied failure "
        "reason into exactly one allowed acquisition theme, select concrete coverage targets "
        "only from the allowed list, and draft a short weekly summary. In this body-part "
        "segmentation system, lr_swap means an anatomical left/right label swap and NEVER "
        "means learning rate; human_edit_delta means the human changed an automatic mask. "
        "The clusters object MUST use every failure reason as a key and one allowed theme as "
        "its string value; never invert that mapping, never use arrays, and never add or omit "
        "reasons. finger_merge concerns hands/fingers; hair_edge concerns hair boundaries; "
        "occlusion_confusion concerns occlusion/contact; lr_swap concerns left/right; "
        "human_edit_delta concerns human correction. "
        "Return JSON only with exact keys: clusters (object reason->theme), coverage_targets "
        "(array), weekly_summary (nonempty string).\nALLOWED THEMES:\n"
        + json.dumps(sorted(ALLOWED_THEMES), separators=(",", ":"))
        + "\nALLOWED COVERAGE TARGETS:\n"
        + json.dumps(sorted(ALLOWED_COVERAGE_TARGETS), separators=(",", ":"))
        + "\nREQUIRED CLUSTERS OBJECT SHAPE (replace each placeholder with one allowed theme):\n"
        + json.dumps(cluster_template, separators=(",", ":"))
        + "\nREASONS:\n"
        + json.dumps(list(reasons), separators=(",", ":"))
    )


def _parse(raw: str, reasons: tuple[str, ...]) -> dict | None:
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(document, dict) or set(document) != {
        "clusters",
        "coverage_targets",
        "weekly_summary",
    }:
        return None
    clusters = document["clusters"]
    targets = document["coverage_targets"]
    summary = document["weekly_summary"]
    if (
        not isinstance(clusters, dict)
        or set(clusters) != set(reasons)
        or any(value not in ALLOWED_THEMES for value in clusters.values())
        or not isinstance(targets, list)
        or any(value not in ALLOWED_COVERAGE_TARGETS for value in targets)
        or len(set(targets)) != len(targets)
        or not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 1000
    ):
        return None
    return {
        "clusters": {key: clusters[key] for key in sorted(clusters)},
        "coverage_targets": targets,
        "weekly_summary": summary.strip(),
    }


def _write_evidence(path: Path, document: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
