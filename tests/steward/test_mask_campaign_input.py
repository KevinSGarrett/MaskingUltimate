from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from maskfactory.steward.mask_campaign_input import (
    REQUIRED_RESOURCE_ROLES,
    SCHEMA_VERSION,
    MaskCampaignInputError,
    prepare_mask_campaign_input,
    validate_mask_campaign_preparation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_mask(path: Path, boxes: list[tuple[int, int, int, int]]) -> None:
    image = Image.new("L", (16, 16), 0)
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill=255)
    image.save(path, format="PNG")


def _resource(path: Path, role: str, *, absent: bool = False) -> dict:
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
    return {
        "role": role,
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
        "mode": mode,
        "width": width,
        "height": height,
        "semantic_absence": absent,
    }


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "assets"
    root.mkdir(parents=True)
    Image.new("RGB", (16, 16), (80, 90, 100)).save(
        root / "source.png",
        format="PNG",
    )
    _write_mask(root / "label.png", [(3, 3, 5, 5)])
    _write_mask(root / "owner.png", [(1, 1, 8, 8)])
    _write_mask(root / "side.png", [(0, 0, 8, 15)])
    _write_mask(root / "neighbor.png", [(10, 3, 12, 5)])
    _write_mask(root / "protected.png", [(9, 2, 13, 6)])
    paths = {
        "source_image": root / "source.png",
        "label_region": root / "label.png",
        "owner_region": root / "owner.png",
        "side_region": root / "side.png",
        "neighbor_region": root / "neighbor.png",
        "protected_region": root / "protected.png",
    }
    contract = {
        "schema_version": SCHEMA_VERSION,
        "record_id": "mask-record-1",
        "resources": [
            _resource(paths[role], role) for role in REQUIRED_RESOURCE_ROLES
        ],
        "semantic_binding": {
            "ontology_sha256": "a" * 64,
            "target_label": "left_hand",
            "target_label_id": 17,
            "owner_id": "person-1",
            "side": "left",
            "neighbor_labels": ["left_forearm"],
            "protected_labels": ["left_forearm"],
        },
        "providers": [
            {
                "provider_id": "sam31",
                "family": "sam",
                "contract_sha256": "b" * 64,
                "checkpoint_sha256": "c" * 64,
                "runtime_sha256": "d" * 64,
                "capabilities": ["mask_candidate"],
            },
            {
                "provider_id": "mask2former",
                "family": "transformer-segmentation",
                "contract_sha256": "e" * 64,
                "checkpoint_sha256": "f" * 64,
                "runtime_sha256": "1" * 64,
                "capabilities": ["mask_candidate"],
            },
        ],
    }
    return root, contract


def test_exact_semantic_resources_and_independent_providers_admit(
    tmp_path: Path,
) -> None:
    root, contract = _fixture(tmp_path)

    result = prepare_mask_campaign_input(asset_root=root, contract=contract)

    assert result["status"] == "ADMITTED"
    assert result["candidate_generation_allowed"] is True
    assert result["seeded_defect_generation_allowed"] is True
    assert result["text_only_acceptance_allowed"] is False
    assert result["campaign_input"]["semantic_binding"]["side"] == "left"
    assert len(result["campaign_input"]["providers"]) == 2
    assert result["campaign_input"]["input_sha256"]
    assert result["preparation_sha256"]
    assert validate_mask_campaign_preparation(
        result,
        asset_root=root,
        contract=contract,
    ) == result


@pytest.mark.parametrize("role", REQUIRED_RESOURCE_ROLES)
def test_every_missing_semantic_resource_abstains_before_inference(
    tmp_path: Path,
    role: str,
) -> None:
    root, contract = _fixture(tmp_path)
    contract["resources"] = [
        row for row in contract["resources"] if row["role"] != role
    ]

    result = prepare_mask_campaign_input(asset_root=root, contract=contract)

    assert result["status"] == "ABSTAIN"
    assert result["reason_code"] == "RESOURCE_SET_INCOMPLETE"
    assert result["candidate_generation_allowed"] is False
    assert result["seeded_defect_generation_allowed"] is False


def test_duplicate_role_hash_mismatch_and_path_escape_abstain(tmp_path: Path) -> None:
    root, contract = _fixture(tmp_path)
    duplicate = copy.deepcopy(contract)
    duplicate["resources"][-1]["role"] = "neighbor_region"
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=duplicate,
    )["reason_code"] == "RESOURCE_ROLE_AMBIGUOUS"

    wrong_hash = copy.deepcopy(contract)
    wrong_hash["resources"][0]["sha256"] = "0" * 64
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=wrong_hash,
    )["reason_code"] == "RESOURCE_HASH_MISMATCH"

    escaped = copy.deepcopy(contract)
    escaped["resources"][0]["path"] = "../source.png"
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=escaped,
    )["reason_code"] == "RESOURCE_PATH_ESCAPE"


def test_geometry_owner_side_neighbor_and_protected_contradictions_abstain(
    tmp_path: Path,
) -> None:
    root, contract = _fixture(tmp_path)
    _write_mask(root / "owner.png", [(12, 12, 15, 15)])
    contract["resources"] = [
        _resource(root / row["path"], row["role"])
        for row in contract["resources"]
    ]
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=contract,
    )["reason_code"] == "OWNER_BINDING_MISMATCH"

    root, contract = _fixture(tmp_path / "second")
    contract["semantic_binding"]["side"] = "unspecified"
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=contract,
    )["reason_code"] == "SIDE_AMBIGUOUS"

    root, contract = _fixture(tmp_path / "third")
    contract["semantic_binding"]["neighbor_labels"] = []
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=contract,
    )["reason_code"] == "NEIGHBOR_BINDING_CONTRADICTORY"

    root, contract = _fixture(tmp_path / "fourth")
    _write_mask(root / "protected.png", [])
    contract["resources"] = [
        _resource(
            root / row["path"],
            row["role"],
            absent=row["role"] == "protected_region",
        )
        for row in contract["resources"]
    ]
    contract["semantic_binding"]["protected_labels"] = []
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=contract,
    )["reason_code"] == "PROTECTED_BINDING_MISMATCH"


def test_provider_count_family_and_capability_are_fail_closed(tmp_path: Path) -> None:
    root, contract = _fixture(tmp_path)
    one = copy.deepcopy(contract)
    one["providers"] = one["providers"][:1]
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=one,
    )["reason_code"] == "PROVIDER_SET_INCOMPLETE"

    same_family = copy.deepcopy(contract)
    same_family["providers"][1]["family"] = "sam"
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=same_family,
    )["reason_code"] == "PROVIDER_SET_AMBIGUOUS"

    missing_capability = copy.deepcopy(contract)
    missing_capability["providers"][1]["capabilities"] = ["points"]
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=missing_capability,
    )["reason_code"] == "PROVIDER_CAPABILITY_MISSING"


def test_explicit_empty_neighbor_and_protected_resources_are_unambiguous(
    tmp_path: Path,
) -> None:
    root, contract = _fixture(tmp_path)
    _write_mask(root / "neighbor.png", [])
    _write_mask(root / "protected.png", [])
    contract["resources"] = [
        _resource(
            root / row["path"],
            row["role"],
            absent=row["role"] in {"neighbor_region", "protected_region"},
        )
        for row in contract["resources"]
    ]
    contract["semantic_binding"]["neighbor_labels"] = []
    contract["semantic_binding"]["protected_labels"] = []

    result = prepare_mask_campaign_input(asset_root=root, contract=contract)

    assert result["status"] == "ADMITTED"
    assert result["text_only_acceptance_allowed"] is False


def test_rehashed_preparation_drift_and_shared_resource_paths_fail_closed(
    tmp_path: Path,
) -> None:
    root, contract = _fixture(tmp_path)
    result = prepare_mask_campaign_input(asset_root=root, contract=contract)
    result["text_only_acceptance_allowed"] = True
    result["preparation_sha256"] = "0" * 64
    result["preparation_sha256"] = hashlib.sha256(
        __import__("json").dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(MaskCampaignInputError, match="differs from exact"):
        validate_mask_campaign_preparation(
            result,
            asset_root=root,
            contract=contract,
        )

    root, contract = _fixture(tmp_path / "shared")
    owner = next(
        row for row in contract["resources"] if row["role"] == "owner_region"
    )
    label = next(
        row for row in contract["resources"] if row["role"] == "label_region"
    )
    label.update(
        {
            "path": owner["path"],
            "bytes": owner["bytes"],
            "sha256": owner["sha256"],
        }
    )
    assert prepare_mask_campaign_input(
        asset_root=root,
        contract=contract,
    )["reason_code"] == "RESOURCE_PATH_AMBIGUOUS"
