"""Exact local Qwen3-VL shadow reviewers behind the provider contract."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..vlm.client import (
    DETERMINISTIC_GENERATION_OPTIONS,
    PART_VERDICT_JSON_SCHEMA,
    OllamaClient,
    parse_part_verdict,
)
from .contracts import ProviderIdentity

QWEN3_VL_SOURCE_REVISION = "96588727e44c78b25ba03ea03b8e12f7e64fd0da"
QWEN3_VL_VARIANTS = {
    "qwen3_vl_4b": {
        "model": "qwen3-vl:4b-instruct-q4_K_M",
        "digest": "ee4b975b58c17ce268cd19d40db35d5edc64603035d2ffc1fee1968eb0947f7b",
        "parameter_size": "4.4B",
    },
    "qwen3_vl_8b_quantized": {
        "model": "qwen3-vl:8b-instruct-q4_K_M",
        "digest": "0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319",
        "parameter_size": "8.8B",
    },
}

TagLoader = Callable[[], Mapping[str, Mapping[str, Any]]]


class Qwen3VlmProviderError(RuntimeError):
    """A Qwen3-VL identity, response, or local-only boundary failed."""


def _local_ollama_tags() -> Mapping[str, Mapping[str, Any]]:
    request = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise Qwen3VlmProviderError(f"cannot read local Ollama model identities: {exc}") from exc
    models = document.get("models")
    if not isinstance(models, list):
        raise Qwen3VlmProviderError("local Ollama tags response has no model array")
    return {str(model.get("name")): model for model in models if isinstance(model, Mapping)}


class Qwen3VlmReviewer:
    """Strict-JSON Qwen3-VL reviewer with criticism-only authority."""

    def __init__(
        self,
        provider_key: str,
        *,
        client: OllamaClient | Any | None = None,
        tag_loader: TagLoader = _local_ollama_tags,
    ) -> None:
        try:
            variant = QWEN3_VL_VARIANTS[provider_key]
        except KeyError as exc:
            raise ValueError(f"unsupported Qwen3-VL provider key: {provider_key}") from exc
        self.provider_key = provider_key
        self.model = str(variant["model"])
        self.expected_digest = str(variant["digest"])
        self.identity = ProviderIdentity(
            provider_key=provider_key,
            role="vlm_reviewer",
            model_family="qwen3_vl",
            source_commit=QWEN3_VL_SOURCE_REVISION,
            runtime_fingerprint=self.expected_digest,
        )
        self._client = client or OllamaClient(timeout_sec=300)
        self._tag_loader = tag_loader

    def review(
        self,
        image_path: Path,
        *,
        masks: Mapping[str, Path],
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        image_path = Path(image_path)
        if not image_path.is_file():
            raise Qwen3VlmProviderError(f"Qwen3-VL review image is missing: {image_path}")
        label = evidence.get("label")
        if not isinstance(label, str) or not label.strip():
            raise Qwen3VlmProviderError("Qwen3-VL reviewer evidence requires a label")
        local = self._tag_loader().get(self.model)
        if not isinstance(local, Mapping) or local.get("digest") != self.expected_digest:
            raise Qwen3VlmProviderError(f"Qwen3-VL model digest mismatch for {self.model}")
        details = local.get("details")
        capabilities = local.get("capabilities")
        if (
            not isinstance(details, Mapping)
            or details.get("family") != "qwen3vl"
            or details.get("quantization_level") != "Q4_K_M"
            or not isinstance(capabilities, list)
            or "vision" not in capabilities
        ):
            raise Qwen3VlmProviderError("Qwen3-VL local capability metadata is invalid")

        image_paths = (image_path,) + tuple(Path(path) for _, path in sorted(masks.items()))
        if any(not path.is_file() for path in image_paths):
            raise Qwen3VlmProviderError("Qwen3-VL review mask/image evidence is missing")
        bounded_evidence = json.dumps(dict(evidence), sort_keys=True, default=str)[:2000]
        prompt = (
            f"Audit body-part mask label {label!r}. Images are source then masks sorted by label. "
            f"Context: {bounded_evidence}. Return STRICT JSON with exactly: verdict "
            "(pass|fail|uncertain), confidence (0..1), problems (canonical strings), "
            "evidence (<=25 words), correction_instruction (<=30 words)."
        )
        try:
            raw = self._client.generate(
                model=self.model,
                prompt=prompt,
                images=image_paths,
                options=DETERMINISTIC_GENERATION_OPTIONS | {"num_ctx": 4096},
                think=False,
                format_schema=PART_VERDICT_JSON_SCHEMA,
            )
        except Exception as exc:  # noqa: BLE001 - normalize provider boundary
            raise Qwen3VlmProviderError(f"Qwen3-VL local review failed: {exc}") from exc
        parsed = parse_part_verdict(raw)
        if parsed is None:
            raise Qwen3VlmProviderError("Qwen3-VL response violated the strict verdict schema")
        return parsed


__all__ = [
    "QWEN3_VL_SOURCE_REVISION",
    "QWEN3_VL_VARIANTS",
    "Qwen3VlmProviderError",
    "Qwen3VlmReviewer",
]
