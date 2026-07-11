"""Local Ollama VLM client, input preparation, strict parsing, and report append."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..gpu import GpuLock
from ..validation import validate_document

ALLOWED_VERDICTS = {"pass", "fail", "uncertain"}
ALLOWED_PROBLEMS = {
    "wrong_part",
    "wrong_side",
    "boundary_too_loose",
    "boundary_too_tight",
    "includes_clothing_as_skin",
    "includes_background",
    "includes_neighbor_part",
    "missing_visible_area",
    "mask_on_hidden_area",
    "finger_merge",
    "hair_edge_bad",
    "occlusion_error",
    "other",
}


class VlmClientError(RuntimeError):
    """Local Ollama request or report mutation failed safely."""


@dataclass(frozen=True)
class VlmVerdict:
    label: str
    panel_file: str
    model: str
    prompt_version: str
    verdict: str
    confidence: float
    problems: tuple[str, ...]
    evidence: str
    correction_instruction: str
    latency_ms: int


@dataclass(frozen=True)
class ImageReviewContext:
    overlay_path: Path
    manifest_digest: str
    qa_excerpts: tuple[dict[str, Any], ...]


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout_sec: int = 180):
        if base_url.rstrip("/") != "http://127.0.0.1:11434":
            raise VlmClientError("VLM endpoint is fixed local-only at 127.0.0.1:11434")
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def generate(self, *, model: str, prompt: str, images: tuple[Path, ...] = ()) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [
                base64.b64encode(Path(path).read_bytes()).decode("ascii") for path in images
            ],
            "stream": False,
            "format": "json",
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                document = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise VlmClientError(f"local Ollama request failed: HTTP {exc.code}: {detail}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise VlmClientError(f"local Ollama request failed: {exc}") from exc
        if not isinstance(document.get("response"), str):
            raise VlmClientError("Ollama response field unavailable")
        return document["response"]


def prepare_panel_input(panel_path: Path, output_path: Path) -> Path:
    """Downscale the five-tile panel to at most 1024 long side for local VLM input."""
    with Image.open(panel_path) as opened:
        image = opened.convert("RGB")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")  # png-strict: allow (RGB VLM evidence, never mask)
    return output_path


def compact_manifest_digest(manifest: dict[str, Any]) -> str:
    rows = ["label:state:area_pct"]
    for label, entry in sorted(manifest.get("parts", {}).items()):
        if isinstance(entry, dict):
            rows.append(
                f"{label}:{entry.get('visibility', 'missing')}:{float(entry.get('area_pct', 0)):.4f}"
            )
    return "\n".join(rows)


def prepare_image_context(
    overlay_path: Path,
    manifest: dict[str, Any],
    qa_report: dict[str, Any],
    *,
    output_path: Path,
) -> ImageReviewContext:
    """Prepare P-IMAGE's 1024 overlay, compact state table, and non-pass QC excerpts."""
    prepared = prepare_panel_input(overlay_path, output_path)
    excerpts = tuple(
        check
        for check in qa_report.get("checks", ())
        if isinstance(check, dict) and check.get("result") in {"fail", "warn", "route"}
    )
    return ImageReviewContext(prepared, compact_manifest_digest(manifest), excerpts)


def review_part(
    client: OllamaClient,
    *,
    label: str,
    panel_path: Path,
    panel_file: str,
    model: str,
    prompt_template: str,
    prompt_version: str,
    gpu_lock_path: Path,
) -> VlmVerdict:
    prompt = prompt_template.replace("<label>", label)
    started = time.perf_counter()
    with GpuLock(path=gpu_lock_path, purpose="S11_vlm_qa"):
        raw = client.generate(model=model, prompt=prompt, images=(panel_path,))
        parsed = _parse_part(raw)
        if parsed is None:
            raw = client.generate(
                model=model,
                prompt=prompt + "\nYour prior response was invalid. JSON only.",
                images=(panel_path,),
            )
            parsed = _parse_part(raw)
    latency = round((time.perf_counter() - started) * 1000)
    if parsed is None:
        parsed = {
            "verdict": "uncertain",
            "confidence": 0.0,
            "problems": [],
            "evidence": "Response remained invalid after JSON-only retry.",
            "correction_instruction": "",
        }
    return VlmVerdict(
        label,
        panel_file,
        model,
        prompt_version,
        parsed["verdict"],
        parsed["confidence"],
        tuple(parsed["problems"]),
        parsed["evidence"],
        parsed["correction_instruction"],
        latency,
    )


def append_verdict(qa_report_path: Path, verdict: VlmVerdict) -> None:
    path = Path(qa_report_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    review = document.setdefault("vlm_review", {"model": verdict.model, "verdicts": []})
    if review.get("model") != verdict.model or not isinstance(review.get("verdicts"), list):
        raise VlmClientError("qa_report VLM review block incompatible")
    review["verdicts"].append(asdict(verdict) | {"problems": list(verdict.problems)})
    issues = validate_document(document, "qa_report")
    if issues:
        raise VlmClientError(
            "verdict would invalidate qa_report: " + "; ".join(str(issue) for issue in issues)
        )
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_part(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != {
        "verdict",
        "confidence",
        "problems",
        "evidence",
        "correction_instruction",
    }:
        return None
    if (
        value["verdict"] not in ALLOWED_VERDICTS
        or not isinstance(value["confidence"], (int, float))
        or not 0 <= value["confidence"] <= 1
    ):
        return None
    if (
        not isinstance(value["problems"], list)
        or len(set(value["problems"])) != len(value["problems"])
        or not set(value["problems"]) <= ALLOWED_PROBLEMS
    ):
        return None
    if not isinstance(value["evidence"], str) or len(value["evidence"].split()) > 25:
        return None
    if (
        not isinstance(value["correction_instruction"], str)
        or len(value["correction_instruction"].split()) > 30
    ):
        return None
    return value
