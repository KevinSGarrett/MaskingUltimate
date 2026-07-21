"""Strict HTTP adapters for cloud mask teachers; credentials and raw responses are never logged."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from .cloud_teacher import (
    CloudProviderRequestError,
    CloudTeacherError,
    TeacherJudgment,
    TeacherRequest,
    TeacherUsage,
    parse_teacher_judgment,
)


class JsonTransport(Protocol):
    def post(self, url: str, *, headers: dict[str, str], payload: dict, timeout: int) -> dict: ...


class UrllibJsonTransport:
    def post(self, url: str, *, headers: dict[str, str], payload: dict, timeout: int) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:2000]
            except OSError:
                detail = ""
            for secret in headers.values():
                if secret:
                    detail = detail.replace(secret, "<redacted>")
            raise CloudProviderRequestError(
                f"cloud provider request failed: HTTP {exc.code}: {detail or exc.reason}",
                definitely_unbilled=exc.code in {400, 401, 403, 404, 409, 422, 429},
            ) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise CloudTeacherError(
                f"cloud provider request failed: {type(exc).__name__}: {exc}"
            ) from exc


@dataclass(frozen=True)
class _ProviderSettings:
    model: str
    api_key_env: str
    base_url: str
    input_rate: float
    output_rate: float
    maximum_reserved_cost_usd: float
    timeout_sec: int


class _BaseProvider:
    name = "base"

    def __init__(self, settings: dict, *, transport: JsonTransport | None = None) -> None:
        self.settings = _settings(settings)
        self.model = self.settings.model
        self.maximum_reserved_cost_usd = self.settings.maximum_reserved_cost_usd
        self.transport = transport or UrllibJsonTransport()

    def _key(self) -> str:
        value = _credential(self.settings.api_key_env, self.name)
        if not value:
            raise CloudTeacherError(
                f"{self.name} credential environment variable is absent: {self.settings.api_key_env}"
            )
        return value

    def _usage(self, input_tokens: int, output_tokens: int) -> TeacherUsage:
        cost = (
            input_tokens * self.settings.input_rate + output_tokens * self.settings.output_rate
        ) / 1_000_000
        if cost > self.maximum_reserved_cost_usd:
            raise CloudTeacherError(
                f"{self.name} usage exceeds reserved per-request maximum: {cost:.6f}"
            )
        return TeacherUsage(int(input_tokens), int(output_tokens), float(cost))

    def _review_with_json_repair(
        self,
        *,
        prompt: str,
        dispatch: Any,
        extract_text: Any,
        extract_usage: Any,
    ) -> TeacherJudgment:
        """Parse structured output and make one bounded repair call when necessary.

        Providers occasionally wrap otherwise-valid JSON in Markdown or append prose.
        We recover a single complete JSON object locally first. If the response still
        violates the canonical schema, one concise repair request is permitted. Token
        usage from both billable calls is aggregated under the original reservation.
        """
        started = time.perf_counter()
        input_tokens = 0
        output_tokens = 0
        last_error: CloudTeacherError | None = None
        for attempt in range(2):
            repair_suffix = (
                ""
                if attempt == 0
                else (
                    "\nYour prior response violated the required JSON contract. Return one "
                    "concise JSON object only, with every required key and no Markdown. "
                    "Confidence must be a number. Every coordinate must be an integer. A pass "
                    "must have defects=[], correction.tool=none, and all correction point arrays "
                    "empty. Do not add keys."
                )
            )
            response = dispatch(prompt + repair_suffix)
            current_input, current_output = extract_usage(response)
            input_tokens += int(current_input)
            output_tokens += int(current_output)
            try:
                raw = _extract_json_object(extract_text(response))
                return parse_teacher_judgment(
                    raw,
                    provider=self.name,
                    model=self.model,
                    usage=self._usage(input_tokens, output_tokens),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
            except CloudTeacherError as exc:
                last_error = exc
        assert last_error is not None
        raise CloudTeacherError(
            f"{self.name} returned invalid structured output after one repair attempt: "
            f"{last_error}"
        ) from last_error


class OpenAITeacherProvider(_BaseProvider):
    name = "openai"

    def review(self, request: TeacherRequest, prompt: str) -> TeacherJudgment:
        _validate_evidence(request)
        image_content = [
            {"type": "input_image", "image_url": _data_url(path)}
            for path in request.evidence.images
        ]

        def dispatch(active_prompt: str) -> dict:
            payload = {
                "model": self.model,
                "store": False,
                "reasoning": {"effort": "low"},
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": active_prompt},
                            *image_content,
                        ],
                    }
                ],
                "text": {"format": _openai_schema()},
                "max_output_tokens": 2048,
            }
            return self.transport.post(
                self.settings.base_url.rstrip("/") + "/responses",
                headers={"Authorization": f"Bearer {self._key()}"},
                payload=payload,
                timeout=self.settings.timeout_sec,
            )

        return self._review_with_json_repair(
            prompt=prompt,
            dispatch=dispatch,
            extract_text=_openai_text,
            extract_usage=lambda response: (
                response.get("usage", {}).get("input_tokens", 0),
                response.get("usage", {}).get("output_tokens", 0),
            ),
        )


class GeminiTeacherProvider(_BaseProvider):
    name = "gemini"

    def review(self, request: TeacherRequest, prompt: str) -> TeacherJudgment:
        _validate_evidence(request)
        image_parts = [
            {
                "inline_data": {
                    "mime_type": _mime(path),
                    "data": base64.b64encode(Path(path).read_bytes()).decode("ascii"),
                }
            }
            for path in request.evidence.images
        ]
        model = urllib.parse.quote(self.model, safe="-._")
        url = f'{self.settings.base_url.rstrip("/")}/models/{model}:generateContent'

        def dispatch(active_prompt: str) -> dict:
            payload = {
                "contents": [{"role": "user", "parts": [{"text": active_prompt}, *image_parts]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": _canonical_schema(),
                    "maxOutputTokens": 2048,
                },
            }
            return self.transport.post(
                url,
                headers={"x-goog-api-key": self._key()},
                payload=payload,
                timeout=self.settings.timeout_sec,
            )

        return self._review_with_json_repair(
            prompt=prompt,
            dispatch=dispatch,
            extract_text=_gemini_text,
            extract_usage=lambda response: (
                response.get("usageMetadata", {}).get("promptTokenCount", 0),
                response.get("usageMetadata", {}).get("candidatesTokenCount", 0),
            ),
        )


class AnthropicTeacherProvider(_BaseProvider):
    name = "anthropic"

    def review(self, request: TeacherRequest, prompt: str) -> TeacherJudgment:
        _validate_evidence(request)
        image_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _mime(path),
                    "data": base64.b64encode(Path(path).read_bytes()).decode("ascii"),
                },
            }
            for path in request.evidence.images
        ]

        def dispatch(active_prompt: str) -> dict:
            payload = {
                "model": self.model,
                "max_tokens": 2048,
                "messages": [
                    {
                        "role": "user",
                        "content": [*image_content, {"type": "text", "text": active_prompt}],
                    }
                ],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": _canonical_schema(),
                    }
                },
            }
            return self.transport.post(
                self.settings.base_url.rstrip("/") + "/messages",
                headers={
                    "x-api-key": self._key(),
                    "anthropic-version": "2023-06-01",
                },
                payload=payload,
                timeout=self.settings.timeout_sec,
            )

        return self._review_with_json_repair(
            prompt=prompt,
            dispatch=dispatch,
            extract_text=_anthropic_text,
            extract_usage=lambda response: (
                response.get("usage", {}).get("input_tokens", 0),
                response.get("usage", {}).get("output_tokens", 0),
            ),
        )


def build_teacher_providers(config: dict, *, transport: JsonTransport | None = None) -> dict:
    classes = {
        "gemini": GeminiTeacherProvider,
        "openai": OpenAITeacherProvider,
        "anthropic": AnthropicTeacherProvider,
    }
    return {
        name: classes[name](settings, transport=transport)
        for name, settings in config["providers"].items()
        if name in classes and settings.get("enabled") is True
    }


def credential_present(environment_name: str, provider: str) -> bool:
    """Check configured environment or local .env without returning/logging a secret."""
    return bool(_credential(environment_name, provider))


def _credential(environment_name: str, provider: str) -> str:
    value = os.environ.get(environment_name, "").strip()
    if value:
        return value
    env_path = Path(os.environ.get("MASKFACTORY_ENV_FILE", ".env"))
    if not env_path.is_file():
        return ""
    canonical: list[str] = []
    legacy: list[str] = []
    alias = {"gemini": "gemini", "openai": "openai", "anthropic": "anthropic"}[provider]
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, candidate = line.split("=", 1)
            if name.strip() == environment_name:
                canonical.append(_strip_secret_quotes(candidate))
            continue
        if ":" in line:
            name, candidate = line.split(":", 1)
            if name.strip().casefold() == alias:
                legacy.append(_strip_secret_quotes(candidate))
    matches = [item for item in canonical or legacy if item]
    if len(matches) > 1 and len(set(matches)) != 1:
        raise CloudTeacherError(f"conflicting {provider} credentials in local .env")
    return matches[0] if matches else ""


def _strip_secret_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def _settings(value: dict) -> _ProviderSettings:
    required = {
        "enabled",
        "model",
        "api_key_env",
        "base_url",
        "input_usd_per_million",
        "output_usd_per_million",
        "maximum_reserved_cost_usd",
        "timeout_sec",
        "role",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CloudTeacherError(f"provider settings require exactly {sorted(required)}")
    if not str(value["base_url"]).startswith("https://"):
        raise CloudTeacherError("cloud teacher endpoint must use HTTPS")
    return _ProviderSettings(
        str(value["model"]),
        str(value["api_key_env"]),
        str(value["base_url"]),
        float(value["input_usd_per_million"]),
        float(value["output_usd_per_million"]),
        float(value["maximum_reserved_cost_usd"]),
        int(value["timeout_sec"]),
    )


def _mime(path: Path) -> str:
    suffix = Path(path).suffix.lower()
    types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    if suffix not in types:
        raise CloudTeacherError(f"unsupported cloud evidence image type: {suffix}")
    return types[suffix]


def _data_url(path: Path) -> str:
    return f"data:{_mime(path)};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _validate_evidence(request: TeacherRequest) -> None:
    """Bound transmitted evidence before credential access or billable dispatch."""
    paths = tuple(Path(path) for path in request.evidence.images)
    if len(paths) != 6:
        raise CloudTeacherError("cloud teacher requires exactly six evidence images")
    total_bytes = 0
    for path in paths:
        size = path.stat().st_size
        if size <= 0 or size > 10 * 1024 * 1024:
            raise CloudTeacherError(f"cloud evidence image has unsafe byte size: {path}")
        total_bytes += size
        with Image.open(path) as image:
            if image.width <= 0 or image.height <= 0 or max(image.size) > 2048:
                raise CloudTeacherError(f"cloud evidence image has unsafe dimensions: {path}")
    if total_bytes > 30 * 1024 * 1024:
        raise CloudTeacherError("cloud evidence bundle exceeds 30 MiB")


def _openai_text(response: dict) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    for output in response.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(
                content.get("text"), str
            ):
                return content["text"]
    raise CloudTeacherError("OpenAI response contains no output text")


def _gemini_text(response: dict) -> str:
    try:
        return "".join(
            part["text"]
            for candidate in response["candidates"]
            for part in candidate["content"]["parts"]
            if isinstance(part.get("text"), str)
        )
    except (KeyError, TypeError) as exc:
        raise CloudTeacherError("Gemini response contains no output text") from exc


def _anthropic_text(response: dict) -> str:
    text = "".join(
        block.get("text", "")
        for block in response.get("content", [])
        if block.get("type") == "text"
    )
    if not text:
        raise CloudTeacherError("Anthropic response contains no output text")
    return text


def _extract_json_object(raw: str) -> str:
    """Return one complete JSON object from strict output or harmless wrappers."""
    stripped = raw.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                value, end = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return stripped[index : index + end]
        raise CloudTeacherError("cloud provider returned invalid JSON")
    if not isinstance(value, dict):
        raise CloudTeacherError("cloud provider JSON response is not an object")
    return stripped


def _canonical_schema() -> dict[str, Any]:
    point = {
        "type": "array",
        "items": {"type": "integer"},
    }
    observations = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "full_context",
            "source_crop",
            "mask",
            "overlay",
            "contour",
            "neighbor_overlap",
        ],
        "properties": {
            key: {"type": "string"}
            for key in (
                "full_context",
                "source_crop",
                "mask",
                "overlay",
                "contour",
                "neighbor_overlap",
            )
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "confidence", "defects", "observations", "evidence", "correction"],
        "properties": {
            "verdict": {"type": "string", "enum": ["pass", "fail", "uncertain"]},
            "confidence": {"type": "number"},
            "defects": {
                "type": "array",
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
            "observations": observations,
            "evidence": {"type": "string"},
            "correction": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tool", "polygon", "positive_points", "negative_points", "rationale"],
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": ["none", "polygon", "points", "human_review"],
                    },
                    "polygon": {"type": "array", "items": point},
                    "positive_points": {"type": "array", "items": point},
                    "negative_points": {"type": "array", "items": point},
                    "rationale": {"type": "string"},
                },
            },
        },
    }


def _openai_schema() -> dict:
    return {
        "type": "json_schema",
        "name": "maskfactory_cloud_teacher",
        "strict": True,
        "schema": _canonical_schema(),
    }


__all__ = [
    "AnthropicTeacherProvider",
    "GeminiTeacherProvider",
    "JsonTransport",
    "OpenAITeacherProvider",
    "UrllibJsonTransport",
    "build_teacher_providers",
    "credential_present",
]
