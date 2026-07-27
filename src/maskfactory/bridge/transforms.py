"""Frozen v1 bridge-coordinate transform execution and replay evidence.

This module deliberately accepts only the typed transform-chain shape already
published by ``mask_acquisition_request``.  It does not widen that wire
contract, and it refuses to guess omitted geometry, interpolation, orientation,
or protected-region ownership.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_transform_policy.yaml"
POLICY_ID = "maskfactory-bridge-transform-execution-v1"
_SPACES = frozenset(("source_pixel", "crop_pixel", "output_pixel"))
_OPERATIONS = frozenset(("crop", "resize", "pad", "horizontal_flip", "project", "inverse_project"))
_ROUNDING = frozenset(("floor", "ceil", "half_even", "half_away_from_zero"))


class TransformValidationError(ValueError):
    """A declared chain cannot be safely executed or replayed."""


@dataclass(frozen=True)
class CoordinateState:
    coordinate_space: str
    width: int
    height: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CoordinateState":
        space, width, height = (
            value.get("coordinate_space"),
            value.get("width"),
            value.get("height"),
        )
        if space not in _SPACES or isinstance(width, bool) or isinstance(height, bool):
            raise TransformValidationError("coordinate state is not a typed bridge pixel space")
        if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
            raise TransformValidationError("coordinate state dimensions must be positive integers")
        return cls(space, width, height)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coordinate_space": self.coordinate_space,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    coordinate_space: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Point":
        x, y, space = value.get("x"), value.get("y"), value.get("coordinate_space")
        if space not in _SPACES or not _finite_number(x) or not _finite_number(y):
            raise TransformValidationError(
                "point must use finite coordinates in a bridge pixel space"
            )
        return cls(float(x), float(y), space)

    def as_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "coordinate_space": self.coordinate_space}


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    coordinate_space: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Box":
        fields = tuple(value.get(name) for name in ("x0", "y0", "x1", "y1"))
        space = value.get("coordinate_space")
        if space not in _SPACES or not all(_finite_number(item) for item in fields):
            raise TransformValidationError(
                "box must use finite coordinates in a bridge pixel space"
            )
        box = cls(*(float(item) for item in fields), space)
        if box.x1 < box.x0 or box.y1 < box.y0:
            raise TransformValidationError("box bounds are inverted")
        return box

    def as_dict(self) -> dict[str, Any]:
        return {
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
            "coordinate_space": self.coordinate_space,
        }


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _policy() -> Mapping[str, Any]:
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransformValidationError(
            "frozen transform policy is unavailable or malformed"
        ) from exc
    if policy.get("policy_id") != POLICY_ID:
        raise TransformValidationError("unexpected transform policy identifier")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise TransformValidationError("transform policy self-hash mismatch")
    return policy


def _canonical_chain_hash(chain: Mapping[str, Any]) -> str:
    return canonical_document_sha256(chain, excluded_top_level_fields=("chain_sha256",))


def _canonical_step_hash(step: Mapping[str, Any]) -> str:
    return canonical_document_sha256(step, excluded_top_level_fields=("step_sha256",))


def validate_transform_chain(chain: Mapping[str, Any]) -> None:
    """Validate all execution-relevant v1 invariants before any transform runs."""
    policy = _policy()
    if not isinstance(chain, Mapping) or set(chain) != {
        "chain_id",
        "chain_sha256",
        "source",
        "output",
        "steps",
        "roundtrip_policy",
    }:
        raise TransformValidationError("transform chain must have the frozen v1 field set")
    if not isinstance(chain.get("chain_id"), str) or not chain["chain_id"]:
        raise TransformValidationError("transform chain identifier is required")
    if chain.get("chain_sha256") != _canonical_chain_hash(chain):
        raise TransformValidationError("canonical transform chain hash mismatch")
    source, output = CoordinateState.from_mapping(chain["source"]), CoordinateState.from_mapping(
        chain["output"]
    )
    steps = chain.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TransformValidationError("an executable transform chain requires ordered steps")
    previous = source
    for sequence, step in enumerate(steps):
        if not isinstance(step, Mapping) or set(step) != {
            "sequence",
            "operation",
            "input",
            "output",
            "parameters",
            "inverse_strategy",
            "step_sha256",
        }:
            raise TransformValidationError("transform step has opaque or unexpected fields")
        if step.get("sequence") != sequence or step.get("operation") not in _OPERATIONS:
            raise TransformValidationError("transform steps must be contiguous typed operations")
        if step.get("step_sha256") != _canonical_step_hash(step):
            raise TransformValidationError("canonical transform step hash mismatch")
        step_input, step_output = CoordinateState.from_mapping(
            step["input"]
        ), CoordinateState.from_mapping(step["output"])
        if step_input != previous:
            raise TransformValidationError("transform step input does not match preceding output")
        _validate_step(step, step_input, step_output, policy)
        previous = step_output
    if previous != output:
        raise TransformValidationError("chain output does not match final transform step")
    roundtrip = chain.get("roundtrip_policy")
    if not isinstance(roundtrip, Mapping) or set(roundtrip) != {
        "required",
        "maximum_error_px",
        "reject_noninvertible",
    }:
        raise TransformValidationError("roundtrip policy has opaque or unexpected fields")
    maximum = roundtrip.get("maximum_error_px")
    if roundtrip.get("required") is not True or roundtrip.get("reject_noninvertible") is not True:
        raise TransformValidationError("roundtrip and non-invertibility rejection are mandatory")
    if not _finite_number(maximum) or float(maximum) > float(policy["maximum_roundtrip_error_px"]):
        raise TransformValidationError("roundtrip tolerance is not within frozen policy")


def _validate_step(
    step: Mapping[str, Any],
    source: CoordinateState,
    output: CoordinateState,
    policy: Mapping[str, Any],
) -> None:
    operation, params, strategy = step["operation"], step["parameters"], step["inverse_strategy"]
    if not isinstance(params, Mapping) or params.get("parameter_type") != operation:
        raise TransformValidationError("transform operation and typed parameters disagree")
    if strategy not in {"exact_inverse", "reproject_with_context"}:
        raise TransformValidationError("non-invertible transform strategies are forbidden")
    if operation == "crop":
        _exact_keys(params, {"parameter_type", "x", "y", "width", "height"})
        x, y, width, height = (params.get(name) for name in ("x", "y", "width", "height"))
        if not all(
            isinstance(item, int) and not isinstance(item, bool) for item in (x, y, width, height)
        ):
            raise TransformValidationError("crop geometry must be integral")
        if (
            min(x, y) < 0
            or width < 1
            or height < 1
            or x + width > source.width
            or y + height > source.height
        ):
            raise TransformValidationError("crop is out of source bounds")
        if (output.width, output.height) != (width, height):
            raise TransformValidationError("crop output dimensions disagree with geometry")
    elif operation == "resize":
        _exact_keys(
            params, {"parameter_type", "width", "height", "interpolation", "rounding", "antialias"}
        )
        if (params.get("width"), params.get("height")) != (output.width, output.height):
            raise TransformValidationError("resize output dimensions disagree with parameters")
        if (
            params.get("interpolation") not in set(policy["permitted_interpolation"])
            or params.get("rounding") not in _ROUNDING
        ):
            raise TransformValidationError("resize interpolation or rounding is not frozen")
        if not isinstance(params.get("antialias"), bool):
            raise TransformValidationError("resize antialias must be explicit")
    elif operation == "pad":
        _exact_keys(params, {"parameter_type", "left", "right", "top", "bottom", "mode", "value"})
        pad = tuple(params.get(name) for name in ("left", "right", "top", "bottom"))
        if not all(
            isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in pad
        ):
            raise TransformValidationError("padding must be non-negative integral geometry")
        if (output.width, output.height) != (
            source.width + pad[0] + pad[1],
            source.height + pad[2] + pad[3],
        ):
            raise TransformValidationError("pad output dimensions disagree with geometry")
        if params.get("mode") not in {"constant", "reflect", "edge"} or not _finite_or_none(
            params.get("value")
        ):
            raise TransformValidationError("pad mode or value is invalid")
    elif operation == "horizontal_flip":
        _exact_keys(params, {"parameter_type", "axis", "character_side_swap"})
        if params.get("axis") != "horizontal" or params.get("character_side_swap") is not True:
            raise TransformValidationError("horizontal flip requires explicit character side swap")
        if output != source:
            raise TransformValidationError(
                "horizontal flip must preserve dimensions and coordinate state"
            )
    else:
        _exact_keys(params, {"parameter_type", "matrix_3x3", "clip_policy", "rounding"})
        matrix = params.get("matrix_3x3")
        if (
            not isinstance(matrix, list)
            or len(matrix) != 9
            or not all(_finite_number(value) for value in matrix)
        ):
            raise TransformValidationError("projection matrix must contain nine finite values")
        if abs(_determinant(matrix)) <= float(policy["minimum_matrix_determinant"]):
            raise TransformValidationError("projection matrix is not safely invertible")
        if (
            params.get("clip_policy") not in {"clip", "pad", "reject_out_of_bounds"}
            or params.get("rounding") not in _ROUNDING
        ):
            raise TransformValidationError("projection clip or rounding policy is invalid")


def _exact_keys(value: Mapping[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise TransformValidationError("transform parameters include opaque or missing fields")


def _finite_or_none(value: Any) -> bool:
    return value is None or _finite_number(value)


def _determinant(m: Sequence[float]) -> float:
    a, b, c, d, e, f, g, h, i = (float(value) for value in m)
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def execute_point(chain: Mapping[str, Any], point: Mapping[str, Any]) -> dict[str, Any]:
    """Execute a declared chain for one point; never clips silently."""
    validate_transform_chain(chain)
    current = Point.from_mapping(point)
    if current.coordinate_space != CoordinateState.from_mapping(chain["source"]).coordinate_space:
        raise TransformValidationError("point coordinate space does not match chain source")
    for step in chain["steps"]:
        current = _execute_step(current, step)
    return current.as_dict()


def _execute_step(point: Point, step: Mapping[str, Any]) -> Point:
    source, output = CoordinateState.from_mapping(step["input"]), CoordinateState.from_mapping(
        step["output"]
    )
    if point.coordinate_space != source.coordinate_space or not _point_in_bounds(point, source):
        raise TransformValidationError("point is outside the declared transform input")
    params, operation = step["parameters"], step["operation"]
    if operation == "crop":
        x, y = point.x - params["x"], point.y - params["y"]
    elif operation == "resize":
        x = 0.0 if source.width == 1 else point.x * (output.width - 1) / (source.width - 1)
        y = 0.0 if source.height == 1 else point.y * (output.height - 1) / (source.height - 1)
    elif operation == "pad":
        x, y = point.x + params["left"], point.y + params["top"]
    elif operation == "horizontal_flip":
        x, y = source.width - 1 - point.x, point.y
    else:
        x, y = _project(point.x, point.y, params["matrix_3x3"])
        if operation == "inverse_project":
            x, y = _project(point.x, point.y, _inverse_matrix(params["matrix_3x3"]))
        if params["clip_policy"] == "reject_out_of_bounds" and not _raw_in_bounds(x, y, output):
            raise TransformValidationError("projection leaves output bounds")
        if params["clip_policy"] == "clip":
            x, y = min(max(x, 0.0), output.width - 1.0), min(max(y, 0.0), output.height - 1.0)
        x, y = _round(x, params["rounding"]), _round(y, params["rounding"])
    result = Point(x, y, output.coordinate_space)
    if not _point_in_bounds(result, output):
        raise TransformValidationError("transform execution produced an out-of-bounds point")
    return result


def _point_in_bounds(point: Point, state: CoordinateState) -> bool:
    return _raw_in_bounds(point.x, point.y, state)


def _raw_in_bounds(x: float, y: float, state: CoordinateState) -> bool:
    return 0.0 <= x <= state.width - 1 and 0.0 <= y <= state.height - 1


def _project(x: float, y: float, matrix: Sequence[float]) -> tuple[float, float]:
    a, b, c, d, e, f, g, h, i = (float(value) for value in matrix)
    divisor = g * x + h * y + i
    if not math.isfinite(divisor) or abs(divisor) <= 1e-12:
        raise TransformValidationError("projection has a singular point")
    return ((a * x + b * y + c) / divisor, (d * x + e * y + f) / divisor)


def _inverse_matrix(matrix: Sequence[float]) -> list[float]:
    a, b, c, d, e, f, g, h, i = (float(value) for value in matrix)
    determinant = _determinant(matrix)
    if abs(determinant) <= 1e-12:
        raise TransformValidationError("projection matrix has no inverse")
    return [
        (e * i - f * h) / determinant,
        (c * h - b * i) / determinant,
        (b * f - c * e) / determinant,
        (f * g - d * i) / determinant,
        (a * i - c * g) / determinant,
        (c * d - a * f) / determinant,
        (d * h - e * g) / determinant,
        (b * g - a * h) / determinant,
        (a * e - b * d) / determinant,
    ]


def _round(value: float, policy: str) -> float:
    if policy == "floor":
        return float(math.floor(value))
    if policy == "ceil":
        return float(math.ceil(value))
    if policy == "half_even":
        return float(round(value))
    return float(math.copysign(math.floor(abs(value) + 0.5), value))


def execute_box(chain: Mapping[str, Any], box: Mapping[str, Any]) -> dict[str, Any]:
    """Transform all box corners and return their enclosing output bounds."""
    original = Box.from_mapping(box)
    corners = (
        {"x": original.x0, "y": original.y0, "coordinate_space": original.coordinate_space},
        {"x": original.x0, "y": original.y1, "coordinate_space": original.coordinate_space},
        {"x": original.x1, "y": original.y0, "coordinate_space": original.coordinate_space},
        {"x": original.x1, "y": original.y1, "coordinate_space": original.coordinate_space},
    )
    transformed = [Point.from_mapping(execute_point(chain, corner)) for corner in corners]
    return Box(
        min(point.x for point in transformed),
        min(point.y for point in transformed),
        max(point.x for point in transformed),
        max(point.y for point in transformed),
        transformed[0].coordinate_space,
    ).as_dict()


def invert_transform_chain(chain: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonically hashed executable inverse, or fail closed."""
    validate_transform_chain(chain)
    inverse_steps: list[dict[str, Any]] = []
    source = CoordinateState.from_mapping(chain["output"])
    for sequence, original in enumerate(reversed(chain["steps"])):
        inverse_steps.append(_inverse_step(original, source, sequence))
        source = CoordinateState.from_mapping(inverse_steps[-1]["output"])
    inverse = {
        "chain_id": f"{chain['chain_id']}:inverse",
        "chain_sha256": "",
        "source": chain["output"],
        "output": chain["source"],
        "steps": inverse_steps,
        "roundtrip_policy": dict(chain["roundtrip_policy"]),
    }
    inverse["chain_sha256"] = _canonical_chain_hash(inverse)
    validate_transform_chain(inverse)
    return inverse


def _inverse_step(
    original: Mapping[str, Any], source: CoordinateState, sequence: int
) -> dict[str, Any]:
    operation, params = original["operation"], original["parameters"]
    original_input, original_output = CoordinateState.from_mapping(
        original["input"]
    ), CoordinateState.from_mapping(original["output"])
    if source != original_output:
        raise TransformValidationError("inverse construction lost coordinate state contiguity")
    strategy = "exact_inverse"
    if operation == "crop":
        inverse_operation, inverse_params = "pad", {
            "parameter_type": "pad",
            "left": params["x"],
            "right": original_input.width - params["x"] - params["width"],
            "top": params["y"],
            "bottom": original_input.height - params["y"] - params["height"],
            "mode": "constant",
            "value": 0,
        }
    elif operation == "resize":
        inverse_operation, inverse_params = "resize", {
            **params,
            "width": original_input.width,
            "height": original_input.height,
        }
        strategy = "reproject_with_context"
    elif operation == "pad":
        inverse_operation, inverse_params = "crop", {
            "parameter_type": "crop",
            "x": params["left"],
            "y": params["top"],
            "width": original_input.width,
            "height": original_input.height,
        }
        strategy = "reproject_with_context"
    elif operation == "horizontal_flip":
        inverse_operation, inverse_params = operation, dict(params)
    else:
        inverse_operation = "inverse_project" if operation == "project" else "project"
        inverse_params = {
            **params,
            "parameter_type": inverse_operation,
            "matrix_3x3": _inverse_matrix(params["matrix_3x3"]),
        }
    step = {
        "sequence": sequence,
        "operation": inverse_operation,
        "input": source.as_dict(),
        "output": original_input.as_dict(),
        "parameters": inverse_params,
        "inverse_strategy": strategy,
        "step_sha256": "",
    }
    step["step_sha256"] = _canonical_step_hash(step)
    return step


def remap_side_label(label: str, *, flip_applied: bool) -> str:
    """Swap standalone anatomical left/right tokens only for a declared flip."""
    if not isinstance(label, str) or not label:
        raise TransformValidationError("side label must be a non-empty string")
    if not flip_applied:
        return label

    def swap(match: re.Match[str]) -> str:
        value = match.group(0)
        replacement = "right" if value.lower() == "left" else "left"
        return replacement.capitalize() if value[0].isupper() else replacement

    return re.sub(r"(?<![A-Za-z])(?:left|right)(?![A-Za-z])", swap, label, flags=re.IGNORECASE)


def validate_protected_regions(
    chain: Mapping[str, Any],
    regions: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
) -> None:
    """Prove declared protected boxes replay exactly; counts and owners are closed."""
    if len(regions) != len(expected):
        raise TransformValidationError("protected-region count mismatch")
    seen: set[str] = set()
    for region, expected_region in zip(regions, expected, strict=True):
        region_id = region.get("region_id")
        if not isinstance(region_id, str) or not region_id or region_id in seen:
            raise TransformValidationError("protected regions require unique identifiers")
        seen.add(region_id)
        if region.get("region_id") != expected_region.get("region_id") or region.get(
            "owner"
        ) != expected_region.get("owner"):
            raise TransformValidationError("protected-region identity or owner mismatch")
        observed = execute_box(chain, region.get("box", {}))
        if observed != expected_region.get("box"):
            raise TransformValidationError("protected-region transform replay mismatch")


def build_roundtrip_evidence(
    chain: Mapping[str, Any],
    probes: Sequence[Mapping[str, Any]],
    *,
    protected_regions: Sequence[Mapping[str, Any]] = (),
    expected_protected_regions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Execute deterministic round-trip probes and return canonical replay evidence."""
    validate_transform_chain(chain)
    inverse = invert_transform_chain(chain)
    max_allowed = float(chain["roundtrip_policy"]["maximum_error_px"])
    results = []
    maximum = 0.0
    for probe in probes:
        start = Point.from_mapping(probe)
        output = Point.from_mapping(execute_point(chain, start.as_dict()))
        replay = Point.from_mapping(execute_point(inverse, output.as_dict()))
        error = max(abs(start.x - replay.x), abs(start.y - replay.y))
        maximum = max(maximum, error)
        results.append(
            {
                "input": start.as_dict(),
                "output": output.as_dict(),
                "replayed": replay.as_dict(),
                "error_px": error,
            }
        )
    if not results or maximum > max_allowed:
        raise TransformValidationError("round-trip probes exceed the declared tolerance")
    validate_protected_regions(chain, protected_regions, expected_protected_regions)
    policy = _policy()
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "bridge_transform_roundtrip_evidence",
        "policy_id": POLICY_ID,
        "policy_sha256": policy["policy_sha256"],
        "transform_chain_id": chain["chain_id"],
        "transform_chain_sha256": chain["chain_sha256"],
        "inverse_chain_sha256": inverse["chain_sha256"],
        "roundtrip_passed": True,
        "maximum_error_px": maximum,
        "probe_results": results,
        "protected_region_count": len(protected_regions),
        "evidence_sha256": "",
    }
    evidence["evidence_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("evidence_sha256",)
    )
    return evidence
