"""Strict local text-LLM duties for failure mining and manifest QA."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Protocol

import yaml

from .client import OllamaClient


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
_MANIFEST_SEVERITIES = frozenset({"BLOCK", "ROUTE", "WARN"})
_MANIFEST_OVERALL = frozenset({"pass", "needs_human"})


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


def run_manifest_lint_sweep(
    *,
    packages_root: Path,
    output_path: Path,
    state_path: Path | None = None,
    client: TextClient | None = None,
    vlm_config_path: Path = Path("configs/vlm.yaml"),
) -> Path:
    """Lint every package manifest with the governed local text model.

    The batch is deliberately text-only, records malformed manifests without asking
    the model, and seals enough request/response evidence to audit every model call.
    """
    config = yaml.safe_load(Path(vlm_config_path).read_text(encoding="utf-8"))
    if config["runtime"]["base_url"] != "http://127.0.0.1:11434":
        raise TextLlmError("P-MANIFEST must remain on the fixed local Ollama endpoint")
    model = config["models"]["text_llm"]
    prompt_version = config["prompts"]["p_manifest"]["version"]
    active_client = client or OllamaClient(config["runtime"]["base_url"])
    packages_root = Path(packages_root)
    previous = _read_manifest_lint_state(state_path)
    current_hashes = {}
    results = []
    skipped_unchanged = 0
    manifests = _package_manifest_paths(packages_root)
    for manifest_path in manifests:
        relative = manifest_path.relative_to(packages_root).as_posix()
        try:
            source_bytes = manifest_path.read_bytes()
        except OSError as exc:
            source_bytes = f"unreadable:{type(exc).__name__}:{exc}".encode()
        manifest_hash = hashlib.sha256(source_bytes).hexdigest()
        current_hashes[relative] = manifest_hash
        if previous.get(relative) == manifest_hash:
            skipped_unchanged += 1
            continue
        try:
            manifest = json.loads(source_bytes.decode("utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest root must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            results.append(
                {
                    "package": str(manifest_path.parent),
                    "manifest": str(manifest_path),
                    "overall": "needs_human",
                    "findings": [
                        {
                            "severity": "BLOCK",
                            "path": "/",
                            "problem": f"manifest cannot be parsed: {exc}",
                            "suggestion": "repair the manifest before package review",
                        }
                    ],
                    "model_called": False,
                    "manifest_sha256": manifest_hash,
                }
            )
            continue
        result = lint_manifest(
            manifest,
            client=active_client,
            model=model,
            prompt_version=prompt_version,
        )
        results.append(
            {
                "package": str(manifest_path.parent),
                "manifest": str(manifest_path),
                **result,
            }
        )
    document = {
        "schema_version": "1.0.0",
        "model": model,
        "prompt_version": prompt_version,
        "packages_root": str(packages_root),
        "discovered_manifest_count": len(manifests),
        "package_count": len(results),
        "skipped_unchanged_count": skipped_unchanged,
        "packages": results,
    }
    _write_evidence(output_path, document)
    if state_path is not None:
        _write_evidence(
            state_path,
            {
                "schema_version": "1.0.0",
                "packages_root": str(packages_root),
                "manifest_sha256": current_hashes,
            },
        )
    return Path(output_path)


def lint_manifest(
    manifest: dict,
    *,
    client: TextClient,
    model: str,
    prompt_version: str,
) -> dict:
    """Run P-MANIFEST with one strict retry and return sealed text-only evidence."""
    prompt = _manifest_prompt(manifest)
    raw = ""
    parsed = None
    for attempt in range(2):
        raw = client.generate(
            model=model,
            prompt=(
                prompt
                if attempt == 0
                else prompt + "\nYour prior response was invalid. Return the exact JSON shape only."
            ),
            images=(),
            options={"temperature": 0, "seed": 1337, "num_predict": 1024},
        )
        parsed = _parse_manifest_lint(raw)
        if parsed is not None:
            break
    if parsed is None:
        raise TextLlmError("local text LLM returned invalid P-MANIFEST JSON after one retry")
    return {
        **parsed,
        "model_called": True,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


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


def _manifest_prompt(manifest: dict) -> str:
    return (
        "You are MaskFactory's local P-MANIFEST reviewer. Lint this text-only package "
        "manifest against the body-part ontology. Check that visibility states are complete "
        "and plausible, derived subsets are consistent, the occlusion graph is acyclic, and "
        "review notes are specific. You are QA routing only: never approve gold, clear a "
        "BLOCK, or claim to have inspected pixels. Return JSON only with exact keys findings "
        "and overall. findings must be an array of objects with exact keys severity, path, "
        "problem, suggestion. severity must be BLOCK, ROUTE, or WARN; path must be a JSON "
        "pointer; overall must be pass or needs_human. A nonempty findings array requires "
        "needs_human.\nMANIFEST:\n" + json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    )


def _package_manifest_paths(packages_root: Path) -> tuple[Path, ...]:
    """Return only authoritative instance or legacy package manifests."""
    output = []
    for path in packages_root.rglob("manifest.json"):
        relative = path.relative_to(packages_root)
        parts = relative.parts
        is_legacy = len(parts) == 2
        is_instance = (
            len(parts) == 4
            and parts[1] == "instances"
            and re.fullmatch(r"p\d+", parts[2]) is not None
        )
        if is_legacy or is_instance:
            output.append(path)
    return tuple(sorted(output))


def _read_manifest_lint_state(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).is_file():
        return {}
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        hashes = document["manifest_sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TextLlmError(f"invalid P-MANIFEST state: {exc}") from exc
    if not isinstance(hashes, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for key, value in hashes.items()
    ):
        raise TextLlmError("invalid P-MANIFEST state hashes")
    return hashes


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


def _parse_manifest_lint(raw: str) -> dict | None:
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(document, dict) or set(document) != {"findings", "overall"}:
        return None
    findings = document["findings"]
    overall = document["overall"]
    if not isinstance(findings, list) or overall not in _MANIFEST_OVERALL:
        return None
    normalized = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {
            "severity",
            "path",
            "problem",
            "suggestion",
        }:
            return None
        if (
            finding["severity"] not in _MANIFEST_SEVERITIES
            or not isinstance(finding["path"], str)
            or not finding["path"].startswith("/")
            or any(
                not isinstance(finding[key], str) or not finding[key].strip()
                for key in ("problem", "suggestion")
            )
        ):
            return None
        normalized.append({key: finding[key].strip() for key in finding})
    if bool(normalized) != (overall == "needs_human"):
        return None
    return {"findings": normalized, "overall": overall}


def _write_evidence(path: Path, document: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
