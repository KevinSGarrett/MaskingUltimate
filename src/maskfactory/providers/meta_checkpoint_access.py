"""Read-only, credential-redacting probes for the two gated Meta checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parents[3]
PROBE_AUTHORITY = (
    "read_only_access_probe_no_terms_acceptance_download_inference_"
    "promotion_mask_truth_or_gold_authority"
)
SAM3D_FILES = ("model.ckpt", "model_config.yaml", "assets/mhr_model.pt")


class MetaCheckpointAccessError(ValueError):
    """A gate probe input or response violates the fail-closed contract."""


@dataclass(frozen=True)
class CheckpointAccessTarget:
    provider: str
    repository: str
    revision: str
    files: tuple[str, ...]
    terms_url: str


HttpHead = Callable[[str, Mapping[str, str]], tuple[int, Mapping[str, str], str | None]]


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _checkpoint_source(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    parts = tuple(part for part in parsed.path.split("/") if part)
    if parsed.scheme != "https" or parsed.netloc != "huggingface.co" or len(parts) != 4:
        raise MetaCheckpointAccessError("SAM 3D Body checkpoint source is not an exact HF tree")
    owner, name, route, revision = parts
    if route != "tree" or len(revision) != 40:
        raise MetaCheckpointAccessError("SAM 3D Body checkpoint revision is not immutable")
    return f"{owner}/{name}", revision


def load_meta_checkpoint_targets(root: Path = ROOT) -> tuple[CheckpointAccessTarget, ...]:
    """Derive exact repositories and revisions from the governed live registries."""
    root = Path(root)
    lock = json.loads((root / "env/sam31_runtime.lock.json").read_text(encoding="utf-8"))
    checkpoint = lock.get("checkpoint", {})
    if (
        lock.get("provider") != "sam3_1"
        or checkpoint.get("gating") != "manual"
        or checkpoint.get("access_status") != "needs_kevin_terms_acceptance"
        or len(str(checkpoint.get("repository_revision", ""))) != 40
    ):
        raise MetaCheckpointAccessError("official SAM 3.1 gate identity drifted")
    registry = yaml.safe_load((root / "configs/external_sources.yaml").read_text(encoding="utf-8"))
    sam3d = registry["providers"]["sam3d_body"]
    repository, revision = _checkpoint_source(str(sam3d["checkpoint_source"]))
    if sam3d.get("lifecycle_state") != "planned" or "NEEDS KEVIN" not in str(
        sam3d.get("checkpoint_gate", "")
    ):
        raise MetaCheckpointAccessError("SAM 3D Body gate identity drifted")
    targets = (
        CheckpointAccessTarget(
            "sam3_1",
            str(checkpoint["repository"]),
            str(checkpoint["repository_revision"]),
            (str(checkpoint["filename"]),),
            f"https://huggingface.co/{checkpoint['repository']}",
        ),
        CheckpointAccessTarget(
            "sam3d_body",
            repository,
            revision,
            SAM3D_FILES,
            f"https://huggingface.co/{repository}",
        ),
    )
    if len({target.provider for target in targets}) != len(targets):
        raise MetaCheckpointAccessError("Meta checkpoint target identities are duplicated")
    return targets


def _default_head(
    url: str, headers: Mapping[str, str]
) -> tuple[int, Mapping[str, str], str | None]:
    try:
        response = requests.head(url, headers=dict(headers), allow_redirects=False, timeout=30)
    except requests.RequestException as exc:
        return 0, {}, type(exc).__name__
    return int(response.status_code), dict(response.headers), None


def _state(status_code: int, error: str | None) -> str:
    if error is not None:
        return "transport_error"
    if status_code == 200 or 300 <= status_code < 400:
        return "accessible"
    if status_code in {401, 403}:
        return "human_gate_pending"
    if status_code == 404:
        return "missing"
    return "unexpected_response"


def probe_meta_checkpoint_access(
    *,
    token: str | None,
    requester: HttpHead = _default_head,
    root: Path = ROOT,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Probe exact resolve URLs without accepting terms or downloading response bodies."""
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise MetaCheckpointAccessError("configured Hugging Face token is empty")
    timestamp = observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MetaCheckpointAccessError("probe timestamp is invalid") from exc
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    provider_documents = []
    states = []
    for target in load_meta_checkpoint_targets(root):
        files = []
        for filename in target.files:
            encoded = "/".join(quote(part, safe="") for part in filename.split("/"))
            url = (
                f"https://huggingface.co/{target.repository}/resolve/"
                f"{target.revision}/{encoded}"
            )
            status_code, response_headers, error = requester(url, headers)
            if isinstance(status_code, bool) or not isinstance(status_code, int):
                raise MetaCheckpointAccessError("checkpoint probe returned an invalid HTTP status")
            state = _state(status_code, error)
            states.append(state)
            length = response_headers.get("Content-Length") or response_headers.get(
                "content-length"
            )
            files.append(
                {
                    "filename": filename,
                    "http_status": status_code,
                    "state": state,
                    "content_length": (
                        int(length) if isinstance(length, str) and length.isdigit() else None
                    ),
                    "error_type": error,
                }
            )
        provider_documents.append(
            {
                "provider": target.provider,
                "repository": target.repository,
                "revision": target.revision,
                "terms_url": target.terms_url,
                "all_files_accessible": all(row["state"] == "accessible" for row in files),
                "files": files,
            }
        )
    if all(state == "accessible" for state in states):
        result = "access_ready"
    elif any(state in {"transport_error", "unexpected_response", "missing"} for state in states):
        result = "probe_error"
    else:
        result = "human_gate_pending"
    document = {
        "schema_version": "1.0.0",
        "observed_at": timestamp,
        "result": result,
        "credential_present": token is not None,
        "credential_redacted": True,
        "request_method": "HEAD",
        "downloaded_bytes": 0,
        "providers": provider_documents,
        "authority": PROBE_AUTHORITY,
    }
    document["sha256"] = _canonical_sha256(document)
    return document


def resolve_huggingface_token() -> str | None:
    """Resolve the standard local credential without ever returning it to output."""
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    try:
        from huggingface_hub import get_token

        return get_token()
    except (ImportError, OSError):
        return None


def verify_meta_checkpoint_access_probe(document: Mapping[str, Any]) -> dict[str, Any]:
    """Verify canonical seal and the no-download/no-authority invariants."""
    required = {
        "schema_version",
        "observed_at",
        "result",
        "credential_present",
        "credential_redacted",
        "request_method",
        "downloaded_bytes",
        "providers",
        "authority",
        "sha256",
    }
    if set(document) != required:
        raise MetaCheckpointAccessError("checkpoint probe document keys drifted")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise MetaCheckpointAccessError("checkpoint probe document hash mismatch")
    if (
        document["schema_version"] != "1.0.0"
        or document["credential_redacted"] is not True
        or document["request_method"] != "HEAD"
        or document["downloaded_bytes"] != 0
        or document["authority"] != PROBE_AUTHORITY
    ):
        raise MetaCheckpointAccessError("checkpoint probe safety boundary drifted")
    providers = document["providers"]
    if not isinstance(providers, list) or [row.get("provider") for row in providers] != [
        "sam3_1",
        "sam3d_body",
    ]:
        raise MetaCheckpointAccessError("checkpoint probe provider coverage drifted")
    states = [item.get("state") for row in providers for item in row.get("files", ())]
    expected = (
        "access_ready"
        if states and all(state == "accessible" for state in states)
        else (
            "probe_error"
            if any(
                state in {"transport_error", "unexpected_response", "missing"} for state in states
            )
            else "human_gate_pending"
        )
    )
    if document["result"] != expected:
        raise MetaCheckpointAccessError("checkpoint probe aggregate result is inconsistent")
    return {
        "result": expected,
        "credential_present": bool(document["credential_present"]),
        "provider_count": len(providers),
        "file_count": len(states),
        "sha256": document["sha256"],
    }


__all__ = [
    "CheckpointAccessTarget",
    "MetaCheckpointAccessError",
    "PROBE_AUTHORITY",
    "load_meta_checkpoint_targets",
    "probe_meta_checkpoint_access",
    "resolve_huggingface_token",
    "verify_meta_checkpoint_access_probe",
]
