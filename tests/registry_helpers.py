"""Strict v2 model-registry builders for runtime-facing tests."""

from __future__ import annotations

from typing import Any

FIXTURE_LICENSE_REVIEW = {
    "status": "verified",
    "source_url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    "snapshot_sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "reviewed_at": "2026-07-14T00:00:00Z",
}
FIXTURE_TIMESTAMP = "2026-07-14T00:00:00Z"


def governed_registry(models: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "use_profile": "private_personal_noncommercial",
        "distribution_allowed": False,
        "commercial_deployment": False,
        "models": models,
    }


def governed_file_model(
    *,
    key: str,
    role: str,
    file: str,
    sha256: str,
    version_tag: str = "fixture-v1",
    **extra: Any,
) -> dict[str, Any]:
    relative = file.replace("\\", "/")
    if not relative.startswith("models/"):
        relative = f"models/{relative}"
    entry: dict[str, Any] = {
        "key": key,
        "role": role,
        "lifecycle_state": "promoted",
        "license_review": dict(FIXTURE_LICENSE_REVIEW),
        "source_url": f"https://example.invalid/maskfactory-fixtures/{key}",
        "file": relative,
        "sha256": sha256,
        "version_tag": version_tag,
        "license": "Apache-2.0",
        "runtime": "pytest-fixture",
        "vram_note": "not applicable to fixture",
        "downloaded_at": FIXTURE_TIMESTAMP,
        "verified": True,
        "smoke_test": {
            "image": "qa/fixtures/smoke/ultralytics_bus_adults.jpg",
            "output_sha256": sha256,
            "runner": "pytest_fixture",
            "verified_at": FIXTURE_TIMESTAMP,
        },
    }
    entry.update(extra)
    return entry


def governed_ollama_model(
    *,
    key: str,
    role: str,
    ollama_name: str,
    digest: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "role": role,
        "lifecycle_state": "installed",
        "license_review": {"status": "pending"},
        "managed": True,
        "manager": "ollama",
        "ollama_name": ollama_name,
        "digest": digest,
        "sha256": digest,
        "ollama_list_id": digest[:12],
        "availability_check": "api_tags+ollama_list_digest_match",
        "family": "fixture",
        "format": "gguf",
        "parameter_size": "1B",
        "quantization": "Q4_K_M",
        "size": 1,
        "registered_at": FIXTURE_TIMESTAMP,
        "verified": True,
    }
