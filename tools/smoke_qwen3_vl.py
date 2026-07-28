from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from PIL import Image, ImageDraw

from maskfactory.providers.qwen3_vl import (
    QWEN3_VL_SOURCE_REVISION,
    QWEN3_VL_VARIANTS,
    Qwen3VlmReviewer,
)
from maskfactory.vlm.client import parse_part_verdict

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "qa" / "live_verification" / "qwen3_vl_ollama_runtime_20260714.json"
BASE_URL = "http://127.0.0.1:11434"

VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "confidence",
        "problems",
        "evidence",
        "correction_instruction",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail", "uncertain"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "problems": {
            "type": "array",
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": [
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
                ],
            },
        },
        "evidence": {"type": "string"},
        "correction_instruction": {"type": "string"},
    },
}


def _post(path: str, payload: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    req = request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc


def _get(path: str) -> dict[str, Any]:
    with request.urlopen(BASE_URL + path, timeout=30) as response:
        return json.loads(response.read().decode())


def _panel() -> bytes:
    panel = Image.new("RGB", (1024, 256), "#20242a")
    for index, title in enumerate(("source", "mask", "overlay", "contour")):
        tile = Image.new("RGB", (256, 256), "#30343a")
        draw = ImageDraw.Draw(tile)
        draw.rectangle((74, 42, 126, 210), fill="#d8b48b")
        draw.rectangle((118, 54, 178, 214), fill="#d8b48b")
        draw.ellipse((84, 30, 130, 80), fill="#d8b48b")
        if title == "mask":
            tile = Image.new("RGB", (256, 256), "black")
            ImageDraw.Draw(tile).polygon(
                [(116, 56), (176, 58), (170, 212), (112, 210)], fill="white"
            )
        elif title == "overlay":
            draw.polygon([(116, 56), (176, 58), (170, 212), (112, 210)], fill="#33cc66")
        elif title == "contour":
            draw.line(
                [(116, 56), (176, 58), (170, 212), (112, 210), (116, 56)],
                fill="#33ff66",
                width=4,
            )
        ImageDraw.Draw(tile).text((8, 8), title, fill="white")
        panel.paste(tile, (index * 256, 0))
    output = io.BytesIO()
    panel.save(output, format="PNG")
    return output.getvalue()


def _prompt() -> str:
    return (
        "Audit the left_forearm mask in this four-tile source/mask/overlay/contour panel. "
        "Left/right is from the character perspective. Return only the required JSON verdict. "
        "Evidence must be at most 25 words and correction_instruction at most 30 words."
    )


def _run(model: str, image_b64: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model,
        "prompt": _prompt(),
        "images": [image_b64],
        "format": VERDICT_SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "seed": 1337,
            "num_predict": 192,
            "num_ctx": 4096,
        },
    }
    started = time.perf_counter()
    response = _post("/api/generate", payload)
    elapsed = time.perf_counter() - started
    parsed = parse_part_verdict(str(response.get("response", "")))
    if parsed is None:
        raise RuntimeError(f"{model} violated strict verdict contract: {response.get('response')}")
    metrics = {
        "elapsed_seconds": round(elapsed, 6),
        "total_duration_ns": response.get("total_duration"),
        "load_duration_ns": response.get("load_duration"),
        "prompt_eval_count": response.get("prompt_eval_count"),
        "prompt_eval_duration_ns": response.get("prompt_eval_duration"),
        "eval_count": response.get("eval_count"),
        "eval_duration_ns": response.get("eval_duration"),
    }
    return parsed, metrics


def _unload(model: str) -> None:
    _post("/api/generate", {"model": model, "prompt": "", "keep_alive": 0, "stream": False})


def main() -> int:
    tags = {entry["name"]: entry for entry in _get("/api/tags")["models"]}
    image = _panel()
    image_b64 = base64.b64encode(image).decode()
    model_results: dict[str, Any] = {}

    for provider_key, variant in QWEN3_VL_VARIANTS.items():
        model = str(variant["model"])
        local = tags.get(model)
        if not isinstance(local, dict) or local.get("digest") != variant["digest"]:
            raise RuntimeError(f"exact installed model missing: {model}")
        warmup, cold = _run(model, image_b64)
        first, warm_first = _run(model, image_b64)
        second, warm_second = _run(model, image_b64)
        processes = {entry["name"]: entry for entry in _get("/api/ps").get("models", [])}
        process = processes.get(model)
        if not isinstance(process, dict):
            raise RuntimeError(f"{model} missing from Ollama process inventory after inference")
        first_hash = hashlib.sha256(
            json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        second_hash = hashlib.sha256(
            json.dumps(second, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if first_hash != second_hash:
            raise RuntimeError(f"{model} verdict was nondeterministic")
        adapter_response = dict(
            Qwen3VlmReviewer(provider_key).review(
                ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg",
                masks={},
                evidence={"label": "person", "qa": "shadow_smoke"},
            )
        )
        model_results[provider_key] = {
            "model": model,
            "manifest_sha256": local["digest"],
            "size_bytes": local["size"],
            "details": local["details"],
            "capabilities": local["capabilities"],
            "cold": cold,
            "warm": [warm_first, warm_second],
            "warmup_response_sha256": hashlib.sha256(
                json.dumps(warmup, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "response": second,
            "provider_adapter_response": adapter_response,
            "response_sha256": second_hash,
            "post_warmup_cross_request_deterministic": True,
            "process": {
                key: process.get(key)
                for key in ("size", "size_vram", "context_length", "expires_at")
            },
        }
        _unload(model)

    failure_exit = None
    try:
        _post(
            "/api/generate",
            {"model": "qwen3-vl:missing-governed-fixture", "prompt": "test", "stream": False},
            timeout=30,
        )
    except RuntimeError as exc:
        failure_exit = str(exc)
    if not failure_exit or "HTTP 404" not in failure_exit:
        raise RuntimeError("missing-model failure boundary did not return HTTP 404")

    gpu = subprocess.run(  # noqa: S603, S607 - fixed diagnostic command
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    version = _get("/api/version")["version"]
    incumbent = tags.get("qwen2.5vl:7b")
    if not isinstance(incumbent, dict):
        raise RuntimeError("Qwen2.5-VL incumbent is no longer locally available")

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "source_revision": QWEN3_VL_SOURCE_REVISION,
        "runtime": {"kind": "native_ollama", "version": version, "gpu": gpu},
        "fixture": {
            "description": "programmatic 1024x256 source/mask/overlay/contour panel",
            "bytes": len(image),
            "sha256": hashlib.sha256(image).hexdigest(),
        },
        "models": model_results,
        "incumbent_preserved": {
            "model": "qwen2.5vl:7b",
            "digest": incumbent["digest"],
            "available": True,
        },
        "failure_behavior": {
            "missing_model": "qwen3-vl:missing-governed-fixture",
            "http_404": True,
        },
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "may_author_masks": False,
            "may_approve_gold": False,
            "may_clear_blocks": False,
            "promotion_claimed": False,
        },
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
