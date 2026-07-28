"""Closed visual-critic output parser for bounded repair intent only."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .calibration_corpus import DEFECT_TYPES
from .critic_catalog import canonical_sha256
from .target_contract import validate_target_contract

SHA256 = re.compile(r"^[a-f0-9]{64}$")
ROOT_KEYS = frozenset(
    {
        "schema_version",
        "verdict",
        "target_contract_sha256",
        "panel_set_sha256",
        "findings",
        "repair_plan",
    }
)
FINDING_KEYS = frozenset({"defect_type", "bbox_xyxy", "evidence_panel_sha256", "confidence"})
PLAN_KEYS = frozenset({"operations", "max_rounds", "max_seconds"})
OPERATION_KEYS = frozenset({"operation", "label_id", "roi_xyxy", "parameters"})
OPERATIONS = frozenset(
    {
        "add_point",
        "remove_point",
        "box_refine",
        "roi_resegment",
        "provider_switch",
        "threshold_adjust",
    }
)
PARAMETERS = {
    "add_point": frozenset({"x", "y", "polarity"}),
    "remove_point": frozenset({"x", "y", "polarity"}),
    "box_refine": frozenset({"padding_pixels"}),
    "roi_resegment": frozenset({"provider_role"}),
    "provider_switch": frozenset({"provider_role"}),
    "threshold_adjust": frozenset({"delta"}),
}


class RepairIntentError(ValueError):
    """Critic output is malformed, unbounded, or attempts pixel authority."""


def _bbox(value: Any, *, field: str, roi: list[int]) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise RepairIntentError(f"{field} must be xyxy")
    try:
        parsed = [int(cell) for cell in value]
    except (TypeError, ValueError) as exc:
        raise RepairIntentError(f"{field} must be integer xyxy") from exc
    x0, y0, x1, y1 = parsed
    rx0, ry0, rx1, ry1 = roi
    if not (rx0 <= x0 < x1 <= rx1 and ry0 <= y0 < y1 <= ry1):
        raise RepairIntentError(f"{field} escapes target ROI")
    return parsed


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RepairIntentError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RepairIntentError(f"{field} must be finite")
    return parsed


def parse_repair_intent(
    response: Mapping[str, Any],
    *,
    target_contract: Mapping[str, Any],
    panel_set_sha256: str,
    allowed_panel_sha256: set[str],
    controller_max_operations: int = 8,
    controller_max_rounds: int = 3,
    controller_max_seconds: int = 300,
) -> dict[str, Any]:
    """Parse critic output without accepting masks, pixels, tools, or authority."""

    try:
        validate_target_contract(target_contract)
    except Exception as exc:
        raise RepairIntentError(f"repair target contract is invalid: {exc}") from exc
    if set(response) != ROOT_KEYS:
        raise RepairIntentError("critic response fields are incomplete, unknown, or pixel-bearing")
    if response["schema_version"] != "1.0.0":
        raise RepairIntentError("critic response schema is unsupported")
    if response["target_contract_sha256"] != target_contract["contract_sha256"]:
        raise RepairIntentError("critic target contract hash drifted")
    if (
        response["panel_set_sha256"] != panel_set_sha256
        or SHA256.fullmatch(panel_set_sha256) is None
    ):
        raise RepairIntentError("critic panel-set hash drifted")
    if not allowed_panel_sha256 or any(
        SHA256.fullmatch(value) is None for value in allowed_panel_sha256
    ):
        raise RepairIntentError("allowed panel evidence is invalid")
    verdict = response["verdict"]
    if verdict not in {"pass", "defect", "abstain"}:
        raise RepairIntentError("critic verdict is invalid")
    roi = list(target_contract["target"]["allowed_roi_xyxy"])

    findings = response["findings"]
    if not isinstance(findings, Sequence) or isinstance(findings, (str, bytes)):
        raise RepairIntentError("critic findings must be a list")
    parsed_findings = []
    for finding in findings:
        if not isinstance(finding, Mapping) or set(finding) != FINDING_KEYS:
            raise RepairIntentError("critic finding fields are incomplete or unknown")
        if finding["defect_type"] not in DEFECT_TYPES:
            raise RepairIntentError("critic finding defect type is out of scope")
        evidence_hash = str(finding["evidence_panel_sha256"])
        if evidence_hash not in allowed_panel_sha256:
            raise RepairIntentError("critic finding cites an unknown panel")
        confidence = _finite_number(finding["confidence"], "finding confidence")
        if not 0 <= confidence <= 1:
            raise RepairIntentError("finding confidence is outside [0,1]")
        parsed_findings.append(
            {
                "defect_type": finding["defect_type"],
                "bbox_xyxy": _bbox(finding["bbox_xyxy"], field="finding bbox", roi=roi),
                "evidence_panel_sha256": evidence_hash,
                "confidence": confidence,
            }
        )

    plan = response["repair_plan"]
    if not isinstance(plan, Mapping) or set(plan) != PLAN_KEYS:
        raise RepairIntentError("critic repair plan fields are incomplete or unknown")
    max_rounds = int(plan["max_rounds"])
    max_seconds = int(plan["max_seconds"])
    if not (1 <= max_rounds <= controller_max_rounds):
        raise RepairIntentError("critic repair rounds exceed controller budget")
    if not (1 <= max_seconds <= controller_max_seconds):
        raise RepairIntentError("critic repair time exceeds controller budget")
    operations = plan["operations"]
    if (
        not isinstance(operations, Sequence)
        or isinstance(operations, (str, bytes))
        or len(operations) > controller_max_operations
    ):
        raise RepairIntentError("critic repair operation count exceeds controller budget")
    target_label = target_contract["target"]["label_id"]
    parsed_operations = []
    for operation in operations:
        if not isinstance(operation, Mapping) or set(operation) != OPERATION_KEYS:
            raise RepairIntentError("critic repair operation fields are incomplete or unknown")
        name = operation["operation"]
        if name not in OPERATIONS:
            raise RepairIntentError("critic repair operation is not allowlisted")
        if operation["label_id"] != target_label:
            raise RepairIntentError("critic repair operation changes target label")
        parameters = operation["parameters"]
        if not isinstance(parameters, Mapping) or set(parameters) != PARAMETERS[name]:
            raise RepairIntentError("critic repair parameters are incomplete or unknown")
        if name in {"add_point", "remove_point"}:
            if parameters["polarity"] not in {"positive", "negative"}:
                raise RepairIntentError("point polarity is invalid")
            x, y = int(parameters["x"]), int(parameters["y"])
            if not (roi[0] <= x < roi[2] and roi[1] <= y < roi[3]):
                raise RepairIntentError("repair point escapes target ROI")
        elif name == "box_refine":
            padding = int(parameters["padding_pixels"])
            if not 0 <= padding <= 64:
                raise RepairIntentError("box padding is unbounded")
        elif name in {"roi_resegment", "provider_switch"}:
            if (
                not isinstance(parameters["provider_role"], str)
                or not parameters["provider_role"].strip()
            ):
                raise RepairIntentError("provider role is empty")
        else:
            delta = _finite_number(parameters["delta"], "threshold delta")
            if not -0.25 <= delta <= 0.25:
                raise RepairIntentError("threshold delta is unbounded")
        parsed_operations.append(
            {
                "operation": name,
                "label_id": target_label,
                "roi_xyxy": _bbox(operation["roi_xyxy"], field="operation ROI", roi=roi),
                "parameters": dict(parameters),
            }
        )

    if verdict in {"pass", "abstain"} and (parsed_findings or parsed_operations):
        raise RepairIntentError("pass or abstain cannot carry repair work")
    if verdict == "defect" and (not parsed_findings or not parsed_operations):
        raise RepairIntentError("defect verdict requires findings and bounded operations")
    result = {
        "schema_version": "1.0.0",
        "verdict": verdict,
        "target_contract_sha256": target_contract["contract_sha256"],
        "panel_set_sha256": panel_set_sha256,
        "findings": parsed_findings,
        "repair_plan": {
            "operations": parsed_operations,
            "max_rounds": max_rounds,
            "max_seconds": max_seconds,
        },
        "critic_pixel_authority": False,
    }
    result["repair_intent_sha256"] = canonical_sha256(result)
    return result
