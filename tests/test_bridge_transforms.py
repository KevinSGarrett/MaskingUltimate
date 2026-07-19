from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.bridge.transforms import (
    TransformValidationError,
    build_roundtrip_evidence,
    execute_box,
    execute_point,
    invert_transform_chain,
    remap_side_label,
    validate_transform_chain,
)
from maskfactory.validation import canonical_document_sha256, schema_validator

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "qa/governance/bridge/bridge_transform_golden_vectors_v1.json"
SCHEMA = ROOT / "src/maskfactory/schemas/bridge_transform_roundtrip_evidence.schema.json"


def _step(sequence: int, operation: str, source: dict, output: dict, parameters: dict) -> dict:
    step = {
        "sequence": sequence,
        "operation": operation,
        "input": source,
        "output": output,
        "parameters": parameters,
        "inverse_strategy": "exact_inverse",
        "step_sha256": "",
    }
    step["step_sha256"] = canonical_document_sha256(
        step, excluded_top_level_fields=("step_sha256",)
    )
    return step


def _chain() -> dict:
    source = {"coordinate_space": "source_pixel", "width": 10, "height": 8}
    crop = {"coordinate_space": "crop_pixel", "width": 8, "height": 6}
    resized = {"coordinate_space": "output_pixel", "width": 16, "height": 12}
    padded = {"coordinate_space": "output_pixel", "width": 20, "height": 16}
    steps = [
        _step(
            0,
            "crop",
            source,
            crop,
            {"parameter_type": "crop", "x": 1, "y": 1, "width": 8, "height": 6},
        ),
        _step(
            1,
            "resize",
            crop,
            resized,
            {
                "parameter_type": "resize",
                "width": 16,
                "height": 12,
                "interpolation": "nearest",
                "rounding": "half_even",
                "antialias": False,
            },
        ),
        _step(
            2,
            "pad",
            resized,
            padded,
            {
                "parameter_type": "pad",
                "left": 2,
                "right": 2,
                "top": 2,
                "bottom": 2,
                "mode": "constant",
                "value": 0,
            },
        ),
        _step(
            3,
            "horizontal_flip",
            padded,
            padded,
            {
                "parameter_type": "horizontal_flip",
                "axis": "horizontal",
                "character_side_swap": True,
            },
        ),
    ]
    chain = {
        "chain_id": "full-frame-crop-resize-pad-flip-v1",
        "chain_sha256": "",
        "source": source,
        "output": padded,
        "steps": steps,
        "roundtrip_policy": {
            "required": True,
            "maximum_error_px": 1.0,
            "reject_noninvertible": True,
        },
    }
    chain["chain_sha256"] = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    return chain


def test_full_frame_crop_resize_pad_flip_executes_and_replays() -> None:
    chain = _chain()
    validate_transform_chain(chain)
    point = {"x": 4, "y": 3, "coordinate_space": "source_pixel"}
    assert execute_point(chain, point) == {
        "x": 10.571428571428571,
        "y": 6.4,
        "coordinate_space": "output_pixel",
    }
    assert execute_box(
        chain, {"x0": 2, "y0": 2, "x1": 5, "y1": 4, "coordinate_space": "source_pixel"}
    ) == {
        "x0": 8.428571428571429,
        "y0": 4.2,
        "x1": 14.857142857142858,
        "y1": 8.6,
        "coordinate_space": "output_pixel",
    }
    inverse = invert_transform_chain(chain)
    assert inverse["output"] == chain["source"]
    evidence = build_roundtrip_evidence(
        chain,
        [point, {"x": 8, "y": 6, "coordinate_space": "source_pixel"}],
        protected_regions=[
            {
                "region_id": "face",
                "owner": "person-1",
                "box": {"x0": 2, "y0": 2, "x1": 4, "y1": 4, "coordinate_space": "source_pixel"},
            }
        ],
        expected_protected_regions=[
            {
                "region_id": "face",
                "owner": "person-1",
                "box": execute_box(
                    chain, {"x0": 2, "y0": 2, "x1": 4, "y1": 4, "coordinate_space": "source_pixel"}
                ),
            }
        ],
    )
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(evidence)
    assert evidence["maximum_error_px"] <= 1.0


def test_golden_vectors_are_stable() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    chain = _chain()
    assert golden["chain_sha256"] == chain["chain_sha256"]
    assert execute_point(chain, golden["input_point"]) == golden["expected_point"]
    evidence = build_roundtrip_evidence(chain, golden["probes"])
    assert evidence["evidence_sha256"] == golden["evidence_sha256"]
    assert schema_validator("bridge_transform_roundtrip_evidence") is not None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda chain: chain["steps"][0]["parameters"].update(opaque=1),
        lambda chain: chain["steps"][0]["parameters"].update(x=9),
        lambda chain: chain["steps"][1].update(input=chain["source"]),
        lambda chain: chain["steps"][2].update(
            output={"coordinate_space": "output_pixel", "width": 19, "height": 16}
        ),
        lambda chain: chain["steps"][3]["parameters"].update(character_side_swap=False),
        lambda chain: chain["roundtrip_policy"].update(maximum_error_px=1.1),
    ],
)
def test_opaque_bounds_order_dimension_side_swap_and_tolerance_fail_closed(mutation) -> None:
    chain = copy.deepcopy(_chain())
    mutation(chain)
    with pytest.raises(TransformValidationError):
        validate_transform_chain(chain)


def test_inverse_and_protected_region_mismatch_fail_closed() -> None:
    chain = _chain()
    with pytest.raises(TransformValidationError, match="protected-region"):
        build_roundtrip_evidence(
            chain,
            [{"x": 4, "y": 3, "coordinate_space": "source_pixel"}],
            protected_regions=[
                {
                    "region_id": "hand",
                    "owner": "person-1",
                    "box": {"x0": 2, "y0": 2, "x1": 3, "y1": 3, "coordinate_space": "source_pixel"},
                }
            ],
            expected_protected_regions=[
                {
                    "region_id": "hand",
                    "owner": "person-2",
                    "box": {"x0": 0, "y0": 0, "x1": 1, "y1": 1, "coordinate_space": "output_pixel"},
                }
            ],
        )
    tampered = _chain()
    tampered["steps"][1]["inverse_strategy"] = "none"
    with pytest.raises(TransformValidationError):
        invert_transform_chain(tampered)


def test_side_swap_and_subpixel_projection_policy_are_explicit() -> None:
    assert remap_side_label("left_hand", flip_applied=True) == "right_hand"
    assert remap_side_label("Right eye", flip_applied=True) == "Left eye"
    assert remap_side_label("cleft", flip_applied=True) == "cleft"
    assert remap_side_label("left_hand", flip_applied=False) == "left_hand"
