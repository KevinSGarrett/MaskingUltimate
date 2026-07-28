"""Fail-closed critic-protocol v3 semantics.

This is deliberately separate from the frozen single-board calibration protocol.
It implements the 2026-07-23R severity vocabulary and deterministic verdict
derivation, but it cannot issue role authority or silently reuse a threshold
profile.  A caller must bind an exact, calibration-only-fitted registry before
it may contact a qualification holdout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .critic_catalog import canonical_sha256
from .live_calibration import CHECK_KEYS, EVIDENCE_BOARD_LAYOUT

PROTOCOL_ID = "maskfactory-critic-protocol-v3-severity-20260723r"
PROTOCOL_SCHEMA_VERSION = "1.0.0"
SEVERITIES = frozenset({"none", "cosmetic", "minor", "serious"})
DERIVED_VERDICTS = frozenset({"pass", "pass_with_findings", "defect", "abstain"})
SOURCE_AUTHORITY_TIERS = frozenset({"external_labeled_reference", "certified_package_bytes"})
LABEL_SCALES = frozenset({"small", "medium", "large"})
SHA256 = re.compile(r"^[a-f0-9]{64}$")
DESCRIPTION_VERDICT_TOKENS = re.compile(
    r"\b(?:verdict|pass|fail|approve|reject|defect|serious|cosmetic|minor)\b",
    re.IGNORECASE,
)

REGISTRY_KEYS = frozenset(
    {
        "schema_version",
        "protocol_id",
        "protocol_version",
        "authority_ceiling",
        "role_certificate_issuance_allowed",
        "frozen_before_holdout",
        "calibration_split_only",
        "calibration_status",
        "calibration_evidence_sha256",
        "calibration_observation_count",
        "requires_reference_exemplar",
        "requires_describe_then_judge",
        "requires_coherent_localization",
        "serious_false_pass_tolerance",
        "tolerance_bands",
    }
)
TOLERANCE_BAND_KEYS = frozenset(
    {"label_id", "source_authority_tier", "label_scale", "minor_budget"}
)
FINDING_KEYS = frozenset({"severity", "cited_evidence_panels", "localization_xyxy"})
RESPONSE_KEYS = frozenset({"description", "findings"})
FIT_OBSERVATION_KEYS = frozenset(
    {
        "split",
        "label_id",
        "source_authority_tier",
        "label_scale",
        "expected_outcome",
        "serious_defect_count",
        "minor_finding_count",
    }
)


class CriticProtocolV3Error(ValueError):
    """Protocol-v3 evidence, registry, or calibration input is invalid."""


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CriticProtocolV3Error(f"{field} must be a SHA-256")
    return value


def _require_nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CriticProtocolV3Error(f"{field} must be a nonnegative integer")
    return value


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```json"):
        value = value[len("```json") :]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return value.strip()


def validate_protocol_registry(registry: Mapping[str, Any]) -> None:
    """Validate a sealed protocol registry without accepting a permissive default."""

    if not isinstance(registry, Mapping) or set(registry) != REGISTRY_KEYS:
        raise CriticProtocolV3Error("protocol-v3 registry fields are incomplete or unknown")
    if registry["schema_version"] != PROTOCOL_SCHEMA_VERSION:
        raise CriticProtocolV3Error("protocol-v3 registry schema is unsupported")
    if registry["protocol_id"] != PROTOCOL_ID or not isinstance(registry["protocol_version"], str):
        raise CriticProtocolV3Error("protocol-v3 registry identity is invalid")
    if registry["authority_ceiling"] != "qualification_canary_only":
        raise CriticProtocolV3Error("protocol-v3 authority ceiling is invalid")
    for field, expected in (
        ("role_certificate_issuance_allowed", False),
        ("frozen_before_holdout", True),
        ("calibration_split_only", True),
        ("requires_reference_exemplar", True),
        ("requires_describe_then_judge", True),
        ("requires_coherent_localization", True),
    ):
        if registry[field] is not expected:
            raise CriticProtocolV3Error(f"protocol-v3 registry {field} is invalid")
    if registry["calibration_status"] not in {
        "preholdout_defaults_only",
        "fitted_calibration_only",
    }:
        raise CriticProtocolV3Error("protocol-v3 calibration status is invalid")
    observation_count = _require_nonnegative_int(
        registry["calibration_observation_count"], "calibration_observation_count"
    )
    evidence_sha256 = registry["calibration_evidence_sha256"]
    if registry["calibration_status"] == "preholdout_defaults_only":
        if evidence_sha256 is not None or observation_count != 0:
            raise CriticProtocolV3Error(
                "protocol-v3 preholdout registry carries calibration evidence"
            )
    else:
        _require_sha256(evidence_sha256, "calibration_evidence_sha256")
        if observation_count == 0:
            raise CriticProtocolV3Error(
                "protocol-v3 fitted registry lacks calibration observations"
            )
    if registry["serious_false_pass_tolerance"] != 0.0:
        raise CriticProtocolV3Error("protocol-v3 serious false-pass tolerance must remain zero")
    bands = registry["tolerance_bands"]
    if not isinstance(bands, Sequence) or isinstance(bands, (str, bytes)) or not bands:
        raise CriticProtocolV3Error("protocol-v3 tolerance bands are empty")
    seen: set[tuple[str, str, str]] = set()
    for band in bands:
        if not isinstance(band, Mapping) or set(band) != TOLERANCE_BAND_KEYS:
            raise CriticProtocolV3Error("protocol-v3 tolerance band fields are invalid")
        label_id = band["label_id"]
        tier = band["source_authority_tier"]
        scale = band["label_scale"]
        if not isinstance(label_id, str) or not label_id:
            raise CriticProtocolV3Error("protocol-v3 tolerance label is invalid")
        if tier not in SOURCE_AUTHORITY_TIERS or scale not in LABEL_SCALES:
            raise CriticProtocolV3Error("protocol-v3 tolerance context is invalid")
        key = (label_id, tier, scale)
        if key in seen:
            raise CriticProtocolV3Error("protocol-v3 tolerance band is duplicated")
        seen.add(key)
        _require_nonnegative_int(band["minor_budget"], "minor_budget")


def protocol_registry_sha256(registry: Mapping[str, Any]) -> str:
    """Return the exact registry binding after fail-closed validation."""

    validate_protocol_registry(registry)
    return canonical_sha256(registry)


def resolve_minor_budget(
    registry: Mapping[str, Any],
    *,
    label_id: str,
    source_authority_tier: str,
    label_scale: str,
) -> int:
    """Resolve one exact label/tier/scale tolerance; no global fallback exists."""

    validate_protocol_registry(registry)
    matches = [
        band
        for band in registry["tolerance_bands"]
        if band["label_id"] == label_id
        and band["source_authority_tier"] == source_authority_tier
        and band["label_scale"] == label_scale
    ]
    if len(matches) != 1:
        raise CriticProtocolV3Error(
            "protocol-v3 tolerance band is unavailable for this exact target"
        )
    return int(matches[0]["minor_budget"])


def require_holdout_eligible_registry(registry: Mapping[str, Any]) -> None:
    """Reject qualification-holdout contact until calibration fit seals a new registry."""

    validate_protocol_registry(registry)
    if registry["calibration_status"] != "fitted_calibration_only":
        raise CriticProtocolV3Error(
            "protocol-v3 registry is not fitted on calibration-only evidence for holdout"
        )


def build_description_prompt(
    *,
    label_id: str,
    source_authority_tier: str,
    label_scale: str,
    reference_case_id: str,
) -> str:
    """Build the first, non-verdict pass of the reference-anchored protocol."""

    if source_authority_tier not in SOURCE_AUTHORITY_TIERS or label_scale not in LABEL_SCALES:
        raise CriticProtocolV3Error("protocol-v3 prompt context is invalid")
    if not isinstance(label_id, str) or not label_id or not isinstance(reference_case_id, str):
        raise CriticProtocolV3Error("protocol-v3 prompt binding is invalid")
    return (
        "/no_think\n"
        "Describe the proposed mask and the image-disjoint known-good reference only. "
        "Do not issue a verdict or diagnose defects in this pass.\n"
        f"Target label: {label_id}\n"
        f"Source authority tier: {source_authority_tier}\n"
        f"Label scale: {label_scale}\n"
        f"Known-good reference case: {reference_case_id}\n"
        "Ground the description in the source, mask, overlay, contour, full-context, and focus panels."
    )


def build_judgement_prompt(
    *,
    description: str,
    label_id: str,
    source_authority_tier: str,
    label_scale: str,
    reference_case_id: str,
    registry: Mapping[str, Any],
) -> str:
    """Build the second pass that returns graded, localized findings only."""

    if not isinstance(description, str) or not description.strip():
        raise CriticProtocolV3Error("protocol-v3 description is required before judgement")
    budget = resolve_minor_budget(
        registry,
        label_id=label_id,
        source_authority_tier=source_authority_tier,
        label_scale=label_scale,
    )
    return (
        "/no_think\n"
        "Judge the proposed mask against the image-disjoint known-good reference and the target "
        "contract. A serious visible defect is a defect. Cosmetic findings never fail a record. "
        f"At most {budget} minor findings are permitted for this exact label/fidelity/scale. "
        "Every non-none finding needs two exact evidence panels and a coherent source-coordinate "
        "localization. Return only JSON with description and findings.\n"
        f"Target label: {label_id}; reference case: {reference_case_id}\n"
        f"First-pass description: {description.strip()}\n"
        "Findings must contain exactly these dimensions: "
        + ", ".join(CHECK_KEYS)
        + ". Each finding is {severity:none|cosmetic|minor|serious,"
        "cited_evidence_panels:[two panel labels],localization_xyxy:[x1,y1,x2,y2]|null}. "
        "Use null localization only for severity none."
    )


def parse_protocol_v3_description(raw: str) -> str:
    """Accept only a bounded non-verdict first-pass description."""

    if not isinstance(raw, str):
        raise CriticProtocolV3Error("protocol-v3 description is not text")
    description = raw.strip()
    if (
        not description
        or len(description) > 4096
        or description.startswith(("{", "[", "```"))
        or DESCRIPTION_VERDICT_TOKENS.search(description) is not None
    ):
        raise CriticProtocolV3Error(
            "protocol-v3 first pass is not a bounded non-verdict description"
        )
    return description


def protocol_v3_response_schema() -> dict[str, Any]:
    """Provide a strict transport schema; semantic checks remain in the parser."""

    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["severity", "cited_evidence_panels", "localization_xyxy"],
        "properties": {
            "severity": {"type": "string", "enum": sorted(SEVERITIES)},
            "cited_evidence_panels": {
                "type": "array",
                "items": {"type": "string", "enum": list(EVIDENCE_BOARD_LAYOUT)},
                "maxItems": len(EVIDENCE_BOARD_LAYOUT),
            },
            "localization_xyxy": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                ]
            },
        },
    }
    return {
        "name": "maskfactory_critic_protocol_v3_response",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["description", "findings"],
            "properties": {
                "description": {"type": "string", "minLength": 1, "maxLength": 4096},
                "findings": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(CHECK_KEYS),
                    "properties": {dimension: finding for dimension in CHECK_KEYS},
                },
            },
        },
    }


def _validate_localization(value: Any, field: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise CriticProtocolV3Error(f"{field} must be an xyxy coordinate array")
    coordinates: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise CriticProtocolV3Error(f"{field} coordinates are invalid")
        coordinates.append(float(coordinate))
    if not coordinates[0] < coordinates[2] or not coordinates[1] < coordinates[3]:
        raise CriticProtocolV3Error(f"{field} must have positive area")
    return coordinates


def parse_protocol_v3_response(raw: str) -> dict[str, Any]:
    """Parse an exact graded response; malformed output remains a typed abstention upstream."""

    try:
        response = json.loads(_strip_json_fence(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CriticProtocolV3Error("protocol-v3 response is not one JSON object") from exc
    if not isinstance(response, Mapping) or set(response) != RESPONSE_KEYS:
        raise CriticProtocolV3Error("protocol-v3 response fields are incomplete or unknown")
    description = response["description"]
    if not isinstance(description, str) or not description.strip() or len(description) > 4096:
        raise CriticProtocolV3Error("protocol-v3 response description is invalid")
    findings = response["findings"]
    if not isinstance(findings, Mapping) or set(findings) != set(CHECK_KEYS):
        raise CriticProtocolV3Error("protocol-v3 findings are incomplete or unknown")
    normalized: dict[str, Any] = {}
    for dimension in CHECK_KEYS:
        finding = findings[dimension]
        if not isinstance(finding, Mapping) or set(finding) != FINDING_KEYS:
            raise CriticProtocolV3Error(f"protocol-v3 finding fields are invalid for {dimension}")
        severity = finding["severity"]
        if severity not in SEVERITIES:
            raise CriticProtocolV3Error(f"protocol-v3 severity is invalid for {dimension}")
        panels = finding["cited_evidence_panels"]
        localization = finding["localization_xyxy"]
        if severity == "none":
            if localization is not None or panels != []:
                raise CriticProtocolV3Error(f"protocol-v3 none finding localizes {dimension}")
            normalized_localization = None
        else:
            if (
                not isinstance(panels, Sequence)
                or isinstance(panels, (str, bytes))
                or len(panels) < 2
                or len(set(panels)) != len(panels)
                or not set(panels) <= set(EVIDENCE_BOARD_LAYOUT)
            ):
                raise CriticProtocolV3Error(
                    f"protocol-v3 evidence panels are invalid for {dimension}"
                )
            normalized_localization = _validate_localization(
                localization, f"protocol-v3 localization for {dimension}"
            )
        normalized[dimension] = {
            "severity": severity,
            "cited_evidence_panels": list(panels),
            "localization_xyxy": normalized_localization,
        }
    return {"description": description.strip(), "findings": normalized}


def _localization_overlaps_target(
    localization: Sequence[float], target_roi_xyxy: Sequence[float]
) -> bool:
    left = max(float(localization[0]), float(target_roi_xyxy[0]))
    top = max(float(localization[1]), float(target_roi_xyxy[1]))
    right = min(float(localization[2]), float(target_roi_xyxy[2]))
    bottom = min(float(localization[3]), float(target_roi_xyxy[3]))
    return left < right and top < bottom


def derive_protocol_v3_verdict(
    *,
    response: Mapping[str, Any],
    registry: Mapping[str, Any],
    label_id: str,
    source_authority_tier: str,
    label_scale: str,
    target_roi_xyxy: Sequence[float],
) -> dict[str, Any]:
    """Derive a fail-closed verdict from severity, localization, and a frozen budget."""

    parsed = parse_protocol_v3_response(json.dumps(response, sort_keys=True))
    if not isinstance(target_roi_xyxy, Sequence) or len(target_roi_xyxy) != 4:
        raise CriticProtocolV3Error("protocol-v3 target ROI is invalid")
    target_roi = _validate_localization(target_roi_xyxy, "protocol-v3 target ROI")
    budget = resolve_minor_budget(
        registry,
        label_id=label_id,
        source_authority_tier=source_authority_tier,
        label_scale=label_scale,
    )
    serious = [
        dimension
        for dimension, finding in parsed["findings"].items()
        if finding["severity"] == "serious"
    ]
    minor = [
        dimension
        for dimension, finding in parsed["findings"].items()
        if finding["severity"] == "minor"
    ]
    incoherent = [
        dimension
        for dimension, finding in parsed["findings"].items()
        if finding["severity"] != "none"
        and not _localization_overlaps_target(finding["localization_xyxy"], target_roi)
    ]
    if incoherent:
        verdict = "abstain"
        reason = "evidence_localization_incoherent"
    elif serious:
        verdict = "defect"
        reason = "serious_finding"
    elif len(minor) > budget:
        verdict = "defect"
        reason = "minor_budget_exceeded"
    elif minor:
        verdict = "pass_with_findings"
        reason = "minor_findings_within_frozen_budget"
    else:
        verdict = "pass"
        reason = "no_serious_or_excess_minor_findings"
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": registry["protocol_version"],
        "registry_sha256": protocol_registry_sha256(registry),
        "verdict": verdict,
        "reason": reason,
        "serious_dimensions": serious,
        "minor_dimensions": minor,
        "incoherent_localization_dimensions": incoherent,
        "evidence_localization_coherent": not incoherent,
        "minor_budget": budget,
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
    }


def evaluate_visual_acceptance(
    *,
    deterministic_qa_passes: bool,
    critic_is_qualified: bool,
    verdict: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply Amendment 1 without allowing protocol-v3 canaries to certify anything."""

    if verdict.get("verdict") not in DERIVED_VERDICTS:
        raise CriticProtocolV3Error("protocol-v3 derived verdict is invalid")
    if deterministic_qa_passes is not True:
        status, reason = "blocked", "deterministic_qa_hard_block"
    elif critic_is_qualified is not True:
        status, reason = "abstain", "qualified_critic_unavailable"
    elif verdict["evidence_localization_coherent"] is not True:
        status, reason = "abstain", "evidence_localization_incoherent"
    elif verdict["verdict"] in {"pass", "pass_with_findings"}:
        status, reason = "pass", "amendment_1_visual_semantics_satisfied"
    elif verdict["verdict"] == "defect":
        status, reason = "defect", "critic_reports_serious_or_excess_minor_defect"
    else:
        status, reason = "abstain", "critic_abstained"
    return {
        "status": status,
        "reason": reason,
        "authority_claimed": False,
        "certificate_issuance_allowed": False,
    }


def fit_calibration_minor_budgets(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Fit deterministic minor budgets from calibration rows only; holdout contact is rejected."""

    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise CriticProtocolV3Error("protocol-v3 calibration observations must be an array")
    fitted: dict[tuple[str, str, str], int] = {}
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != FIT_OBSERVATION_KEYS:
            raise CriticProtocolV3Error("protocol-v3 calibration observation fields are invalid")
        if observation["split"] != "calibration":
            raise CriticProtocolV3Error("protocol-v3 calibration fit may not contact holdout")
        if observation["expected_outcome"] != "valid_mask":
            raise CriticProtocolV3Error("protocol-v3 calibration fit requires valid-mask rows")
        if observation["source_authority_tier"] not in SOURCE_AUTHORITY_TIERS:
            raise CriticProtocolV3Error("protocol-v3 calibration tier is invalid")
        if observation["label_scale"] not in LABEL_SCALES or not observation["label_id"]:
            raise CriticProtocolV3Error("protocol-v3 calibration target is invalid")
        if _require_nonnegative_int(observation["serious_defect_count"], "serious_defect_count"):
            raise CriticProtocolV3Error(
                "protocol-v3 calibration valid mask reports a serious defect"
            )
        minor_count = _require_nonnegative_int(
            observation["minor_finding_count"], "minor_finding_count"
        )
        key = (
            str(observation["label_id"]),
            str(observation["source_authority_tier"]),
            str(observation["label_scale"]),
        )
        fitted[key] = max(fitted.get(key, 0), minor_count)
    if not fitted:
        raise CriticProtocolV3Error("protocol-v3 calibration fit has no usable rows")
    return [
        {
            "label_id": label_id,
            "source_authority_tier": tier,
            "label_scale": scale,
            "minor_budget": minor_budget,
        }
        for (label_id, tier, scale), minor_budget in sorted(fitted.items())
    ]


def seal_fitted_calibration_registry(
    *,
    preholdout_registry: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    protocol_version: str,
) -> dict[str, Any]:
    """Create a new immutable calibration-only registry from exact observations.

    The source registry remains a pre-holdout default.  A caller must persist the
    returned object as a distinct version before it can be used on a qualification
    holdout.  No evidence from a holdout can enter the fitting operation.
    """

    validate_protocol_registry(preholdout_registry)
    if preholdout_registry["calibration_status"] != "preholdout_defaults_only":
        raise CriticProtocolV3Error("only a preholdout registry may seed a fitted registry")
    if not isinstance(protocol_version, str) or not protocol_version.strip():
        raise CriticProtocolV3Error("fitted protocol version is invalid")
    if protocol_version == preholdout_registry["protocol_version"]:
        raise CriticProtocolV3Error("fitted registry requires a distinct protocol version")

    bands = fit_calibration_minor_budgets(observations)
    fitted = dict(preholdout_registry)
    fitted.update(
        {
            "protocol_version": protocol_version.strip(),
            "calibration_status": "fitted_calibration_only",
            "calibration_evidence_sha256": canonical_sha256(
                {
                    "preholdout_registry_sha256": protocol_registry_sha256(preholdout_registry),
                    "observations": list(observations),
                }
            ),
            "calibration_observation_count": len(observations),
            "tolerance_bands": bands,
        }
    )
    validate_protocol_registry(fitted)
    return fitted
