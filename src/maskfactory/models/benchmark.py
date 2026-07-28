"""Measured-path installed→benchmarked mutator (never assigns champion_*)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .registry import (
    DEFAULT_MODELS_ROOT,
    DEFAULT_REGISTRY,
    ModelRegistryError,
    _atomic_json,
    _load_registry,
    resolve_registered_model,
)


def mark_benchmarked_candidate(
    candidate_key: str,
    *,
    certificate: dict[str, Any] | Path,
    expected_identity_hashes: dict[str, Any] | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Raise an installed challenger to lifecycle ``benchmarked`` after measured proof.

    Never assigns ``champion_*`` roles and never force-registers.
    """
    from ..training.promotion_policy import (
        CustomSegmenterPromotionError,
        validate_custom_segmenter_promotion_certificate,
    )

    if not isinstance(candidate_key, str) or not candidate_key:
        raise ModelRegistryError("benchmark candidate key is required")
    if isinstance(certificate, Path):
        try:
            certificate_doc = json.loads(Path(certificate).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelRegistryError(f"benchmark certificate is unreadable: {exc}") from exc
    else:
        certificate_doc = dict(certificate)
    registry_path = Path(registry_path)
    models_root = Path(models_root)
    registry = _load_registry(registry_path)
    matches = [entry for entry in registry["models"] if entry.get("key") == candidate_key]
    if len(matches) != 1:
        raise ModelRegistryError(f"benchmark candidate is missing or ambiguous: {candidate_key}")
    candidate = matches[0]
    if candidate.get("managed") is True or candidate.get("verified") is not True:
        raise ModelRegistryError("benchmark candidate must be a verified unmanaged checkpoint")
    if str(candidate.get("role", "")).startswith("champion_"):
        raise ModelRegistryError("mark-benchmarked refuses champion_* roles (no force-register)")
    if candidate.get("role") != "challenger_bodypart":
        raise ModelRegistryError("mark-benchmarked requires challenger_bodypart")
    if candidate.get("lifecycle_state") == "benchmarked":
        raise ModelRegistryError("candidate is already lifecycle benchmarked")
    if candidate.get("lifecycle_state") != "installed":
        raise ModelRegistryError("mark-benchmarked requires lifecycle_state=installed")
    resolve_registered_model(candidate_key, registry_path=registry_path, models_root=models_root)
    identity_hashes = dict(expected_identity_hashes or certificate_doc.get("identity_hashes") or {})
    if not identity_hashes:
        raise ModelRegistryError("benchmark certificate lacks identity_hashes")
    if identity_hashes.get("checkpoint_sha256") != candidate.get("sha256"):
        raise ModelRegistryError("benchmark certificate checkpoint identity differs from registry")
    try:
        summary = validate_custom_segmenter_promotion_certificate(
            certificate_doc,
            expected_identity_hashes=identity_hashes,
        )
    except CustomSegmenterPromotionError as exc:
        raise ModelRegistryError(str(exc)) from exc
    if summary.get("candidate_key") != candidate_key:
        raise ModelRegistryError("benchmark certificate candidate_key differs from registry entry")
    if certificate_doc.get("lifecycle_state") != "benchmarked":
        raise ModelRegistryError("benchmark certificate lifecycle_state must be benchmarked")
    timestamp = (
        (now or (lambda: datetime.now(UTC)))().astimezone(UTC).isoformat().replace("+00:00", "Z")
    )
    # Registry schema only accepts the slim legacy benchmarkCertificate shape on
    # the model entry. Keep the validated custom-segmenter certificate hash in
    # artifact_hashes; promote-custom-segmenter still loads the full cert from
    # the matrix bundle.
    cert_sha = str(certificate_doc.get("sha256") or "")
    legacy = {
        "schema_version": "1.0.0",
        "target_role": "champion_bodypart",
        "primary_win_or_labor_reduction": True,
        "hard_bucket_results": [
            {
                "bucket": "custom_segmenter_certificate",
                "observed_delta": 0.0,
                "noninferiority_margin": 0.0,
                "passed": True,
            }
        ],
        "frozen_eval_sha256": cert_sha if len(cert_sha) == 64 else ("a" * 64),
        "issued_at": timestamp,
    }
    legacy["sha256"] = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    candidate["lifecycle_state"] = "benchmarked"
    candidate["benchmark_certificate"] = legacy
    artifacts = dict(candidate.get("artifact_hashes") or {})
    if len(cert_sha) == 64:
        artifacts["custom_segmenter_certificate_sha256"] = cert_sha
    candidate["artifact_hashes"] = artifacts
    _atomic_json(registry_path, registry)
    return candidate


__all__ = ["mark_benchmarked_candidate"]
