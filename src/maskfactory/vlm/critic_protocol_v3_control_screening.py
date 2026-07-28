"""Fail-closed protocol-v3 screening for session-agent controls only.

The frozen CelebAMask board can exercise severity/localization interaction, but
never fit a qualified role, unlock strict acceptance, or claim certificate,
gold, training, or production authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .celebamask_control_admission import verify_celebamask_control_admission
from .critic_catalog import canonical_sha256
from .critic_protocol_v3 import CHECK_KEYS, SEVERITIES

CONTROL_PROTOCOL_ID = "maskfactory-critic-protocol-v3-session-agent-control-20260724"
SCHEMA_VERSION = "1.0.0"
CONTROL_AUTHORITY_TIER = "session_agent_control"
PANEL_LAYOUT = ("source", "binary_mask", "overlay", "contour", "full_context", "target_zoom")
PANEL_KEYS = frozenset(PANEL_LAYOUT)
SHA256 = re.compile(r"^[a-f0-9]{64}$")
REGISTRY_KEYS = frozenset(
    {
        "schema_version",
        "protocol_id",
        "protocol_version",
        "protocol_semantics_id",
        "authority_ceiling",
        "role_certificate_issuance_allowed",
        "strict_visual_authority_allowed",
        "gold_or_training_authority_allowed",
        "production_authority_allowed",
        "requires_reference_exemplar",
        "requires_describe_then_judge",
        "requires_coherent_localization",
        "minor_budget",
        "calibration_fitting_allowed",
        "holdout_role_qualification_allowed",
    }
)
RESPONSE_KEYS = frozenset({"description", "findings"})
FINDING_KEYS = frozenset({"severity", "cited_evidence_panels", "localization_xyxy"})


class CriticProtocolV3ControlScreeningError(ValueError):
    """A control-screening input attempts to widen, drift, or claim authority."""


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CriticProtocolV3ControlScreeningError(f"{field} must be a SHA-256")
    return value


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise CriticProtocolV3ControlScreeningError(f"{field} is empty")
    result = Path(value.replace("\\", "/"))
    if result.is_absolute() or ".." in result.parts:
        raise CriticProtocolV3ControlScreeningError(f"{field} is unsafe")
    return result


def validate_control_screening_registry(registry: Mapping[str, Any]) -> None:
    """Require a zero-budget registry separate from visual-role qualification."""

    if not isinstance(registry, Mapping) or set(registry) != REGISTRY_KEYS:
        raise CriticProtocolV3ControlScreeningError("control-screening registry fields are invalid")
    if (
        registry["schema_version"] != SCHEMA_VERSION
        or registry["protocol_id"] != CONTROL_PROTOCOL_ID
        or not isinstance(registry["protocol_version"], str)
        or not registry["protocol_version"].strip()
        or registry["protocol_semantics_id"] != "maskfactory-critic-protocol-v3-severity-20260723r"
        or registry["authority_ceiling"] != "session_agent_control_screening_only"
        or registry["minor_budget"] != 0
    ):
        raise CriticProtocolV3ControlScreeningError(
            "control-screening registry identity is invalid"
        )
    for field in (
        "role_certificate_issuance_allowed",
        "strict_visual_authority_allowed",
        "gold_or_training_authority_allowed",
        "production_authority_allowed",
        "calibration_fitting_allowed",
        "holdout_role_qualification_allowed",
    ):
        if registry[field] is not False:
            raise CriticProtocolV3ControlScreeningError(
                f"control-screening registry {field} drifted"
            )
    for field in (
        "requires_reference_exemplar",
        "requires_describe_then_judge",
        "requires_coherent_localization",
    ):
        if registry[field] is not True:
            raise CriticProtocolV3ControlScreeningError(
                f"control-screening registry {field} drifted"
            )


def control_registry_sha256(registry: Mapping[str, Any]) -> str:
    validate_control_screening_registry(registry)
    return canonical_sha256(registry)


def execution_manifest_sha256(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: item for key, item in value.items() if key != "execution_manifest_sha256"}
    )


def _scale(mask: Image.Image) -> str:
    ratio = sum(pixel > 0 for pixel in mask.getdata()) / (mask.width * mask.height)
    return "small" if ratio <= 0.025 else "medium" if ratio <= 0.15 else "large"


def _bound_panels(record: Mapping[str, Any], panel_root: Path) -> dict[str, Any]:
    sample_id = record.get("sample_id")
    files, hashes = record.get("panel_files"), record.get("panel_sha256s")
    if (
        not isinstance(sample_id, str)
        or not sample_id
        or not isinstance(files, Mapping)
        or not isinstance(hashes, Mapping)
    ):
        raise CriticProtocolV3ControlScreeningError("admission panel binding is invalid")
    if set(files) != PANEL_KEYS or set(hashes) != PANEL_KEYS:
        raise CriticProtocolV3ControlScreeningError(f"{sample_id} panel set is incomplete")
    root = Path(panel_root).resolve(strict=True)
    clean_files: dict[str, str] = {}
    clean_hashes: dict[str, str] = {}
    geometry: tuple[int, int] | None = None
    for name in PANEL_LAYOUT:
        relative = _safe_relative(files[name], f"{sample_id}.{name}")
        path = (root / sample_id / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CriticProtocolV3ControlScreeningError(
                f"{sample_id}.{name} escapes panel root"
            ) from exc
        expected = _sha(hashes[name], f"{sample_id}.{name}")
        if not path.is_file() or _sha_file(path) != expected:
            raise CriticProtocolV3ControlScreeningError(f"{sample_id}.{name} panel hash drifted")
        with Image.open(path) as opened:
            image = opened.convert("L") if name == "binary_mask" else opened.convert("RGB")
            if image.width < 2 or image.height < 2:
                raise CriticProtocolV3ControlScreeningError(
                    f"{sample_id}.{name} panel is degenerate"
                )
            if name in {"source", "binary_mask"}:
                if geometry is None:
                    geometry = image.size
                elif image.size != geometry:
                    raise CriticProtocolV3ControlScreeningError(
                        f"{sample_id} source/mask geometry drifted"
                    )
            if name == "binary_mask" and image.getbbox() is None:
                raise CriticProtocolV3ControlScreeningError(f"{sample_id} mask is empty")
        clean_files[name], clean_hashes[name] = relative.as_posix(), expected
    assert geometry is not None
    with Image.open(root / sample_id / clean_files["binary_mask"]) as opened:
        label_scale = _scale(opened.convert("L"))
    return {
        "sample_id": sample_id,
        "panel_files": clean_files,
        "panel_sha256s": clean_hashes,
        "geometry_wh": list(geometry),
        "label_scale": label_scale,
    }


def build_control_screening_execution(
    *,
    admission: Mapping[str, Any],
    admission_file_sha256: str,
    panel_root: Path,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind every admitted record to a same-label image-disjoint good control."""

    try:
        verify_celebamask_control_admission(admission)
    except Exception as exc:
        raise CriticProtocolV3ControlScreeningError(f"admission invalid: {exc}") from exc
    validate_control_screening_registry(registry)
    admission_file_sha256 = _sha(admission_file_sha256, "admission file")
    admission_self = _sha(admission.get("self_sha256"), "admission self")
    records = admission.get("records")
    if not isinstance(records, list) or not records:
        raise CriticProtocolV3ControlScreeningError("admission controls are missing")
    bound = {str(record.get("sample_id")): _bound_panels(record, panel_root) for record in records}
    if len(bound) != len(records) or "None" in bound:
        raise CriticProtocolV3ControlScreeningError("admission control IDs are duplicated")
    valid: dict[tuple[str, str], list[str]] = {}
    for record in records:
        if record.get("expected_outcome") == "valid_mask":
            key = (str(record.get("partition")), str(record.get("canonical_label")))
            valid.setdefault(key, []).append(str(record["sample_id"]))
    for values in valid.values():
        values.sort()
    cases: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda value: str(value["sample_id"])):
        case_id = str(record["sample_id"])
        partition = str(record.get("partition"))
        label_id = str(record.get("canonical_label"))
        if partition not in {"calibration", "qualification_holdout"} or not label_id:
            raise CriticProtocolV3ControlScreeningError(f"{case_id} partition/label is invalid")
        references = [item for item in valid.get((partition, label_id), []) if item != case_id]
        if not references:
            raise CriticProtocolV3ControlScreeningError(f"{case_id} lacks a known-good reference")
        candidate, reference = bound[case_id], bound[references[0]]
        if candidate["panel_sha256s"]["source"] == reference["panel_sha256s"]["source"]:
            raise CriticProtocolV3ControlScreeningError(
                f"{case_id} reference is not image-disjoint"
            )
        cases.append(
            {
                "case_id": case_id,
                "reference_case_id": references[0],
                "partition": partition,
                "label_id": label_id,
                "label_scale": candidate["label_scale"],
                "expected_outcome": record["expected_outcome"],
                "defect_type": record["defect_type"],
                "candidate": {
                    key: value for key, value in candidate.items() if key != "label_scale"
                },
                "reference": {
                    key: value for key, value in reference.items() if key != "label_scale"
                },
            }
        )
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "protocol_v3_session_agent_control_screening_execution",
        "execution_id": f"celebamask-control-v3-screening-{admission_self[:12]}",
        "registry_sha256": control_registry_sha256(registry),
        "control_admission_file_sha256": admission_file_sha256,
        "control_admission_self_sha256": admission_self,
        "case_count": len(cases),
        "cases": cases,
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
        "strict_visual_authority_allowed": False,
        "gold_or_training_authority_allowed": False,
        "production_authority_allowed": False,
        "calibration_fitting_allowed": False,
        "holdout_role_qualification_allowed": False,
        "execution_manifest_sha256": "",
    }
    value["execution_manifest_sha256"] = execution_manifest_sha256(value)
    validate_control_screening_execution(value, registry)
    return value


def validate_control_screening_execution(
    value: Mapping[str, Any], registry: Mapping[str, Any]
) -> None:
    """Validate the sealed execution before a backend is allowed to load."""

    validate_control_screening_registry(registry)
    required = {
        "schema_version",
        "artifact_type",
        "execution_id",
        "registry_sha256",
        "control_admission_file_sha256",
        "control_admission_self_sha256",
        "case_count",
        "cases",
        "authority_claimed",
        "role_certificate_issuance_allowed",
        "strict_visual_authority_allowed",
        "gold_or_training_authority_allowed",
        "production_authority_allowed",
        "calibration_fitting_allowed",
        "holdout_role_qualification_allowed",
        "execution_manifest_sha256",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value["schema_version"] != SCHEMA_VERSION
    ):
        raise CriticProtocolV3ControlScreeningError(
            "control-screening execution fields are invalid"
        )
    if (
        value["artifact_type"] != "protocol_v3_session_agent_control_screening_execution"
        or value["registry_sha256"] != control_registry_sha256(registry)
        or value["execution_manifest_sha256"] != execution_manifest_sha256(value)
    ):
        raise CriticProtocolV3ControlScreeningError("control-screening execution seal drifted")
    for field in (
        "authority_claimed",
        "role_certificate_issuance_allowed",
        "strict_visual_authority_allowed",
        "gold_or_training_authority_allowed",
        "production_authority_allowed",
        "calibration_fitting_allowed",
        "holdout_role_qualification_allowed",
    ):
        if value[field] is not False:
            raise CriticProtocolV3ControlScreeningError(
                f"control-screening execution {field} drifted"
            )
    cases = value["cases"]
    if not isinstance(cases, list) or not cases or value["case_count"] != len(cases):
        raise CriticProtocolV3ControlScreeningError("control-screening execution cases invalid")
    if [str(case.get("case_id")) for case in cases] != sorted(
        str(case.get("case_id")) for case in cases
    ):
        raise CriticProtocolV3ControlScreeningError("control-screening order is nondeterministic")


def build_control_description_prompt(
    *, label_id: str, label_scale: str, reference_case_id: str
) -> str:
    if (
        not isinstance(label_id, str)
        or not label_id
        or label_scale not in {"small", "medium", "large"}
    ):
        raise CriticProtocolV3ControlScreeningError("control-screening prompt context invalid")
    return (
        "/no_think\nDescribe the proposed mask and image-disjoint known-good reference only. "
        "Do not issue a verdict, acceptance, qualification, or authority decision.\n"
        f"Target label: {label_id}\nSource authority tier: {CONTROL_AUTHORITY_TIER}\n"
        f"Label scale: {label_scale}\nKnown-good reference case: {reference_case_id}\n"
        "This is a non-authoritative session-agent control screen. Ground the description in "
        "SOURCE, BINARY_MASK, OVERLAY, CONTOUR, FULL_CONTEXT, and TARGET_ZOOM only."
    )


def build_control_judgement_prompt(
    *, description: str, label_id: str, label_scale: str, reference_case_id: str
) -> str:
    if not isinstance(description, str) or not description.strip():
        raise CriticProtocolV3ControlScreeningError("control-screening description missing")
    none_finding = {
        "severity": "none",
        "cited_evidence_panels": [],
        "localization_xyxy": None,
    }
    response_shape = {
        "description": description.strip(),
        "findings": {dimension: none_finding for dimension in CHECK_KEYS},
    }
    return (
        "/no_think\nScreen the candidate against the image-disjoint known-good reference. This is not "
        "semantic qualification, a strict visual pass, or an authority decision. A serious visible "
        "discrepancy is a screening defect and the frozen minor budget is zero. Every non-none finding "
        "requires two exact evidence panels and coherent source coordinates.\n"
        f"Target label: {label_id}; reference case: {reference_case_id}; label scale: {label_scale}\n"
        f"First-pass description: {description.strip()}\nFindings must contain exactly: "
        + ", ".join(CHECK_KEYS)
        + ". Return exactly one JSON object, no Markdown, no top-level array, no findings array, and no per-item anatomy field. "
        "Copy this exact object shape and replace only its values:\n"
        + json.dumps(response_shape, separators=(",", ":"), sort_keys=True)
        + "\nFor severity none, cited_evidence_panels must be [] and localization_xyxy must be null. "
        "Nonempty cited_evidence_panels or a non-null localization_xyxy with severity none invalidates the response. "
        "Copy the response description from the first-pass description exactly; never use a placeholder. "
        "For any other severity, cite at least two distinct lowercase panels from "
        + ", ".join(PANEL_LAYOUT)
        + ", and provide a positive-area [x1,y1,x2,y2] localization."
    )


def control_response_schema() -> dict[str, Any]:
    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["severity", "cited_evidence_panels", "localization_xyxy"],
        "properties": {
            "severity": {"type": "string", "enum": sorted(SEVERITIES)},
            "cited_evidence_panels": {
                "type": "array",
                "items": {"type": "string", "enum": list(PANEL_LAYOUT)},
            },
            "localization_xyxy": {
                "anyOf": [
                    {"type": "null"},
                    {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                ]
            },
        },
    }
    return {
        "name": "maskfactory_critic_protocol_v3_control_screening_response",
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
                    "properties": {key: finding for key in CHECK_KEYS},
                },
            },
        },
    }


def _strip_json(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    return value[:-3].strip() if value.endswith("```") else value.strip()


def _xyxy(value: Any, field: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise CriticProtocolV3ControlScreeningError(f"{field} must be xyxy")
    result = [float(item) for item in value]
    if not result[0] < result[2] or not result[1] < result[3]:
        raise CriticProtocolV3ControlScreeningError(f"{field} has no area")
    return result


def parse_control_screening_response(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(_strip_json(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CriticProtocolV3ControlScreeningError(
            "control-screening response is not JSON"
        ) from exc
    if (
        not isinstance(value, Mapping)
        or set(value) != RESPONSE_KEYS
        or not isinstance(value["description"], str)
        or not value["description"].strip()
    ):
        raise CriticProtocolV3ControlScreeningError("control-screening response fields invalid")
    findings = value["findings"]
    if not isinstance(findings, Mapping) or set(findings) != set(CHECK_KEYS):
        raise CriticProtocolV3ControlScreeningError("control-screening findings invalid")
    normalized: dict[str, Any] = {}
    for dimension in CHECK_KEYS:
        finding = findings[dimension]
        if (
            not isinstance(finding, Mapping)
            or set(finding) != FINDING_KEYS
            or finding["severity"] not in SEVERITIES
        ):
            raise CriticProtocolV3ControlScreeningError(
                f"control-screening finding invalid:{dimension}"
            )
        severity = finding["severity"]
        panels = finding["cited_evidence_panels"]
        localization = finding["localization_xyxy"]
        if severity == "none":
            if panels != [] or localization is not None:
                raise CriticProtocolV3ControlScreeningError(
                    f"control-screening none finding localizes:{dimension}"
                )
            normalized_localization = None
        else:
            if (
                not isinstance(panels, Sequence)
                or isinstance(panels, (str, bytes))
                or len(panels) < 2
                or len(set(panels)) != len(panels)
                or not set(panels) <= PANEL_KEYS
            ):
                raise CriticProtocolV3ControlScreeningError(
                    f"control-screening evidence panels invalid:{dimension}"
                )
            normalized_localization = _xyxy(localization, f"{dimension}.localization")
        normalized[dimension] = {
            "severity": severity,
            "cited_evidence_panels": list(panels),
            "localization_xyxy": normalized_localization,
        }
    return {"description": value["description"].strip(), "findings": normalized}


def derive_control_screening_verdict(
    *, response: Mapping[str, Any], geometry_wh: Sequence[int]
) -> dict[str, Any]:
    """Use zero tolerance but return a screening result, never visual acceptance."""

    parsed = parse_control_screening_response(json.dumps(response, sort_keys=True))
    if (
        not isinstance(geometry_wh, Sequence)
        or len(geometry_wh) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) or v < 2 for v in geometry_wh)
    ):
        raise CriticProtocolV3ControlScreeningError("control-screening geometry invalid")
    width, height = geometry_wh
    serious, minor, incoherent = [], [], []
    for dimension, finding in parsed["findings"].items():
        if finding["severity"] == "serious":
            serious.append(dimension)
        if finding["severity"] == "minor":
            minor.append(dimension)
        box = finding["localization_xyxy"]
        if box is not None and not (
            box[0] < width and box[1] < height and box[2] > 0 and box[3] > 0
        ):
            incoherent.append(dimension)
    if incoherent:
        outcome, reason = "abstain", "evidence_localization_incoherent"
    elif serious:
        outcome, reason = "screening_defect", "serious_finding"
    elif minor:
        outcome, reason = "screening_defect", "zero_minor_budget_exceeded"
    else:
        outcome, reason = "no_screening_defect", "no_serious_or_minor_findings"
    return {
        "protocol_id": CONTROL_PROTOCOL_ID,
        "screening_outcome": outcome,
        "reason": reason,
        "serious_dimensions": serious,
        "minor_dimensions": minor,
        "incoherent_localization_dimensions": incoherent,
        "evidence_localization_coherent": not incoherent,
        "minor_budget": 0,
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
        "strict_visual_authority_allowed": False,
        "gold_or_training_authority_allowed": False,
        "production_authority_allowed": False,
    }


def materialize_control_evidence_board(
    *, side: Mapping[str, Any], panel_root: Path, output_path: Path
) -> dict[str, Any]:
    """Render a labeled board with TARGET_ZOOM explicitly named as such."""

    root = Path(panel_root).resolve(strict=True)
    images: list[Image.Image] = []
    try:
        for name in PANEL_LAYOUT:
            path = (root / str(side["sample_id"]) / str(side["panel_files"][name])).resolve()
            if not path.is_file() or _sha_file(path) != side["panel_sha256s"][name]:
                raise CriticProtocolV3ControlScreeningError("control board panel hash drifted")
            with Image.open(path) as opened:
                images.append(opened.convert("RGB"))
        width, height, header = 512, 768, 28
        board = Image.new("RGB", (width * 3, (height + header) * 2), color=(0, 0, 0))
        draw = ImageDraw.Draw(board)
        for index, (name, image) in enumerate(zip(PANEL_LAYOUT, images, strict=True)):
            row, column = divmod(index, 3)
            x0, y0 = column * width, row * (height + header)
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            draw.text((x0 + 5, y0 + 6), name.upper(), fill=(255, 255, 255))
            board.paste(
                image,
                (x0 + (width - image.width) // 2, y0 + header + (height - image.height) // 2),
            )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        board.save(output, format="PNG", optimize=False, compress_level=9)
    finally:
        for image in images:
            image.close()
    return {
        "path": Path(output_path),
        "sha256": _sha_file(Path(output_path)),
        "panel_names": list(PANEL_LAYOUT),
    }
