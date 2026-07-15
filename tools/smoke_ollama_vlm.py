"""Exercise the local Ollama VLM with a synthetic P-PART-style panel."""

from __future__ import annotations

import base64
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "vlm.yaml"
REPORT_PATH = ROOT / "qa" / "reports" / "ollama_vlm_smoke.json"

P_PART_PROMPT = """You are auditing a body-part segmentation mask for label `left_forearm` (left/right is from the CHARACTER's perspective). Panel tiles: source crop, mask, overlay, contour, protected-overlap heat. Answer STRICT JSON only: {verdict: pass|fail|uncertain, confidence: 0-1, problems: [subset of [wrong_part, wrong_side, boundary_too_loose, boundary_too_tight, includes_clothing_as_skin, includes_background, includes_neighbor_part, missing_visible_area, mask_on_hidden_area, finger_merge, hair_edge_bad, occlusion_error, other]], evidence: '<<=25 words pointing at panel location>', correction_instruction: '<=30 words imperative for the annotator>'}."""


def _read_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _validate_governance(config: dict[str, Any]) -> None:
    governance = config["governance"]
    forbidden_flags = ("may_author_masks", "may_approve_gold", "may_clear_blocks")
    if any(governance[flag] for flag in forbidden_flags):
        raise RuntimeError(f"VLM governance must remain non-authoritative: {governance}")
    if governance["source_images_leave_machine"] not in {False, "exact_hash_opt_in_only"}:
        raise RuntimeError("VLM smoke requires local or exact-hash-governed image handling")


def _synthetic_panel_png() -> bytes:
    panel = Image.new("RGB", (1024, 256), "#242424")
    labels = ["source", "mask", "overlay", "contour"]
    for index, label in enumerate(labels):
        x0 = index * 256
        tile = Image.new("RGB", (256, 256), "#30343a")
        draw = ImageDraw.Draw(tile)
        draw.rectangle((74, 42, 126, 210), fill="#d8b48b")
        draw.rectangle((118, 54, 178, 214), fill="#d8b48b")
        draw.ellipse((84, 30, 130, 80), fill="#d8b48b")
        if label == "mask":
            tile = Image.new("RGB", (256, 256), "#000000")
            draw = ImageDraw.Draw(tile)
            draw.polygon([(116, 56), (176, 58), (170, 212), (112, 210)], fill="#ffffff")
        elif label == "overlay":
            draw.polygon([(116, 56), (176, 58), (170, 212), (112, 210)], fill="#33ff6688")
        elif label == "contour":
            draw.line(
                [(116, 56), (176, 58), (170, 212), (112, 210), (116, 56)], fill="#33ff66", width=4
            )
        draw.text((8, 8), label, fill="#ffffff")
        panel.paste(tile, (x0, 0))

    output = io.BytesIO()
    panel.save(output, format="PNG")
    return output.getvalue()


def _post_json(url: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc


def _word_count(text: str) -> int:
    return len([word for word in text.strip().split() if word])


def _parse_json_response(content: str) -> dict[str, Any]:
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("response is not a JSON object")
    return parsed


def _validate_p_part(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    prompt_config = config["prompts"]["p_part"]
    required = set(prompt_config["required_keys"])
    allowed_keys = required
    allowed_verdicts = set(prompt_config["allowed_verdicts"])
    allowed_problems = set(prompt_config["allowed_problems"])

    checks = {
        "exact_required_keys": set(payload) == allowed_keys,
        "verdict_allowed": payload.get("verdict") in allowed_verdicts,
        "confidence_number_0_1": isinstance(payload.get("confidence"), int | float)
        and 0 <= float(payload["confidence"]) <= 1,
        "problems_list_allowed": isinstance(payload.get("problems"), list)
        and all(problem in allowed_problems for problem in payload["problems"]),
        "evidence_string_25_words": isinstance(payload.get("evidence"), str)
        and _word_count(payload["evidence"]) <= 25,
        "correction_instruction_string_30_words": isinstance(
            payload.get("correction_instruction"), str
        )
        and _word_count(payload["correction_instruction"]) <= 30,
    }
    return checks


def _call_p_part(
    config: dict[str, Any], image_png: bytes, json_only_retry: bool = False
) -> dict[str, Any]:
    base_url = config["runtime"]["base_url"].rstrip("/")
    prompt = P_PART_PROMPT
    if json_only_retry:
        prompt += "\nReturn JSON only. Do not include Markdown or explanation."
    payload = {
        "model": config["models"]["primary_vlm"],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_png).decode("ascii")],
            }
        ],
    }
    return _post_json(f"{base_url}/api/chat", payload)


def main() -> None:
    config = _read_config()
    _validate_governance(config)
    image_png = _synthetic_panel_png()
    attempts: list[dict[str, Any]] = []
    started = time.perf_counter()

    parsed: dict[str, Any] | None = None
    checks: dict[str, bool] = {}
    for attempt in range(config["prompts"]["p_part"]["retry_on_invalid_json"] + 1):
        response = _call_p_part(config, image_png, json_only_retry=attempt > 0)
        content = response["message"]["content"]
        attempt_record = {
            "attempt": attempt + 1,
            "model": response.get("model"),
            "eval_count": response.get("eval_count"),
        }
        try:
            parsed = _parse_json_response(content)
            checks = _validate_p_part(parsed, config)
            attempt_record["parsed"] = True
            attempt_record["checks"] = checks
        except (json.JSONDecodeError, ValueError) as exc:
            attempt_record["parsed"] = False
            attempt_record["error"] = str(exc)
        attempts.append(attempt_record)
        if parsed is not None and checks and all(checks.values()):
            break

    latency_seconds = time.perf_counter() - started
    if parsed is None or not all(checks.values()):
        raise RuntimeError(f"Ollama VLM P-PART smoke failed: {attempts}")

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "base_url": config["runtime"]["base_url"],
        "model": config["models"]["primary_vlm"],
        "prompt_version": config["prompts"]["p_part"]["version"],
        "fixture": "programmatically generated 1024x256 four-tile synthetic P-PART panel",
        "latency_seconds": round(latency_seconds, 3),
        "response": parsed,
        "checks": checks,
        "attempts": attempts,
        "governance": config["governance"],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "ollama_vlm_smoke=pass; "
        f"model={report['model']}; latency_seconds={latency_seconds:.3f}; "
        f"verdict={parsed['verdict']}; confidence={parsed['confidence']}"
    )


if __name__ == "__main__":
    main()
