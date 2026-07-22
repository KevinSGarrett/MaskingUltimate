from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.external_supervision import EXTERNAL_LABEL_ROLE
from maskfactory.external_supervision_evidence import (
    CANONICAL_REQUIRED_GATES_BY_SOURCE,
    GATE_ARTIFACT_TYPES,
    SHARED_GATE_SOURCES,
    build_qualification_evidence_bundle,
    seal_payload,
)
from maskfactory.external_supervision_packages import (
    AUTHORITY,
    DEFAULT_MAXIMUM_COMBINED_EXTERNAL_BATCH_FRACTION,
    LIVE_AUTHORITY,
    LIVE_PROOF_TIER,
    PROOF_TIER,
    ExternalPackageSelection,
    ExternalSupervisionPackageError,
    assert_builder_accepts_only_gated_external_rows,
    assert_launcher_accepts_only_gated_external_rows,
    materialize_qualified_train_only_packages,
    require_external_package_qualification,
    validate_external_batch_cap,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "configs" / "maskedwarehouse_inventory.json"
PROVENANCE = ROOT / "configs" / "maskedwarehouse_provenance.yaml"


def _load_inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _load_provenance() -> dict:
    return yaml.safe_load(PROVENANCE.read_text(encoding="utf-8"))


def _sealed(value: dict) -> dict:
    value["seal_sha256"] = seal_payload(value)
    return value


def _gate_artifact_paths(tmp_path: Path, source: str) -> dict[str, Path]:
    artifact_directory = tmp_path / source
    artifact_directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for gate in CANONICAL_REQUIRED_GATES_BY_SOURCE[source]:
        artifact = _sealed(
            {
                "schema_version": "1.0.0",
                "artifact_type": GATE_ARTIFACT_TYPES[gate],
                "source": SHARED_GATE_SOURCES.get(gate, source),
                "gate": gate,
                "status": "PASS",
            }
        )
        path = artifact_directory / f"{gate}.json"
        path.write_bytes(json.dumps(artifact, sort_keys=True).encode("utf-8"))
        paths[gate] = path.relative_to(tmp_path)
    return paths


def _evidence_bundle(tmp_path: Path, source: str) -> dict:
    return build_qualification_evidence_bundle(
        source=source,
        gate_artifact_paths=_gate_artifact_paths(tmp_path, source),
        project_root=tmp_path,
    )


def _selection(source: str, image_id: str, labels: tuple[str, ...]) -> ExternalPackageSelection:
    part = np.zeros((4, 4), dtype=np.uint16)
    part[1:3, 1:3] = 2
    material = np.zeros((4, 4), dtype=np.uint8)
    material[1:3, 1:3] = 1
    return ExternalPackageSelection(
        source=source,
        image_id=image_id,
        part_map=part,
        material_map=material,
        label_names=labels,
        training_loss_weight=0.15,
        source_sha256="a" * 64,
        source_relative_path=f"{source}/source.jpg",
        annotation_sha256="b" * 64,
        annotation_relative_path=f"{source}/annotation.png",
        split_group_id="external_group_" + "c" * 24,
    )


def test_batch_cap_boundary_and_bypass_fail() -> None:
    certified = [
        {
            "image_id": f"real_{index}",
            "source_role": "owned_photo",
            "truth_tier": "human_anchor_gold",
        }
        for index in range(65)
    ]
    external = [
        {
            "image_id": f"ext_{index}",
            "source_role": EXTERNAL_LABEL_ROLE,
            "truth_tier": "weighted_pseudo_label",
            "external_qualification_admitted": True,
        }
        for index in range(35)
    ]
    metrics = validate_external_batch_cap(certified + external)
    assert metrics["external_image_share"] == pytest.approx(0.35)
    assert metrics["certified_real_dominant"] is True
    assert metrics["maximum_combined_external_batch_fraction"] == (
        DEFAULT_MAXIMUM_COMBINED_EXTERNAL_BATCH_FRACTION
    )

    with pytest.raises(ExternalSupervisionPackageError, match="exceeds cap"):
        validate_external_batch_cap(
            certified
            + external
            + [
                {
                    "image_id": "ext_bypass",
                    "source_role": EXTERNAL_LABEL_ROLE,
                    "truth_tier": "weighted_pseudo_label",
                    "external_qualification_admitted": True,
                }
            ]
        )


def test_certified_real_must_dominate_external_share() -> None:
    # Stay under the 0.35 cap while certified-real share fails to dominate.
    rows = [
        {
            "image_id": "real_0",
            "source_role": "owned_photo",
            "truth_tier": "human_anchor_gold",
        },
        {
            "image_id": "real_1",
            "source_role": "owned_photo",
            "truth_tier": "human_anchor_gold",
        },
        *[
            {
                "image_id": f"pseudo_{index}",
                "source_role": "owned_photo",
                "truth_tier": "weighted_pseudo_label",
            }
            for index in range(5)
        ],
        *[
            {
                "image_id": f"ext_{index}",
                "source_role": EXTERNAL_LABEL_ROLE,
                "truth_tier": "weighted_pseudo_label",
                "external_qualification_admitted": True,
            }
            for index in range(3)
        ],
    ]
    with pytest.raises(ExternalSupervisionPackageError, match="dominate"):
        validate_external_batch_cap(rows)


def test_builder_and_launcher_refuse_ungated_external_rows() -> None:
    ungated = [
        {
            "image_id": "img_x",
            "source_role": EXTERNAL_LABEL_ROLE,
            "truth_tier": "weighted_pseudo_label",
            "truth_partition": "train",
            "training_loss_weight": 0.15,
            "dataset_volume_eligible": False,
            "external_qualification_admitted": False,
        }
    ]
    with pytest.raises(ExternalSupervisionPackageError, match="builder refused ungated"):
        assert_builder_accepts_only_gated_external_rows(ungated)
    with pytest.raises(ExternalSupervisionPackageError, match="launcher refused ungated"):
        assert_launcher_accepts_only_gated_external_rows(ungated)


def test_materialize_gated_packages_and_dataset_card(tmp_path: Path) -> None:
    provenance = _load_provenance()
    inventory = _load_inventory()
    bundle = _evidence_bundle(tmp_path, "lapa")
    companion = [
        {
            "image_id": f"real_{index}",
            "source_role": "owned_photo",
            "truth_tier": "human_anchor_gold",
            "truth_partition": "train",
            "training_loss_weight": 1.0,
        }
        for index in range(3)
    ]
    report = materialize_qualified_train_only_packages(
        [
            _selection("lapa", "img_ext_lapa_0001", ("head_face", "hair")),
        ],
        destination=tmp_path / "batch",
        provenance=provenance,
        inventory=inventory,
        evidence_bundles_by_source={"lapa": bundle},
        project_root=tmp_path,
        companion_certified_rows=companion,
    )
    assert report["proof_tier"] == PROOF_TIER
    assert report["authority"] == AUTHORITY
    assert report["admission_ready"] is False
    assert report["live_warehouse_admission"] is False
    assert report["package_count"] == 1
    assert report["source_composition"]["lapa"] == 1
    assert "head_face" in report["label_composition"]
    card = (tmp_path / "batch" / "dataset_card.md").read_text(encoding="utf-8")
    assert "Source composition" in card
    assert "lapa" in card
    package = tmp_path / "batch" / "packages" / "img_ext_lapa_0001" / "instances" / "p0"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    require_external_package_qualification(manifest)
    assert (package / "label_map_part.png").is_file()
    assert (tmp_path / "batch" / "batch_manifest.json").is_file()


def test_explicit_live_admission_marks_only_verified_train_only_output(tmp_path: Path) -> None:
    report = materialize_qualified_train_only_packages(
        [_selection("lapa", "img_ext_lapa_live", ("head_face", "hair"))],
        destination=tmp_path / "live_batch",
        provenance=_load_provenance(),
        inventory=_load_inventory(),
        evidence_bundles_by_source={"lapa": _evidence_bundle(tmp_path, "lapa")},
        project_root=tmp_path,
        companion_certified_rows=[
            {
                "image_id": f"real_{index}",
                "source_role": "owned_photo",
                "truth_tier": "human_anchor_gold",
                "truth_partition": "train",
                "training_loss_weight": 1.0,
            }
            for index in range(3)
        ],
        live_warehouse_admission=True,
    )
    assert report["proof_tier"] == LIVE_PROOF_TIER
    assert report["authority"] == LIVE_AUTHORITY
    assert report["admission_ready"] is True
    assert report["live_warehouse_admission"] is True
    assert report["any_source_admitted_live"] is True


def test_package_population_does_not_require_a_fabricated_certified_batch(
    tmp_path: Path,
) -> None:
    report = materialize_qualified_train_only_packages(
        [_selection("lapa", "img_ext_lapa_population", ("head_face", "hair"))],
        destination=tmp_path / "population",
        provenance=_load_provenance(),
        inventory=_load_inventory(),
        evidence_bundles_by_source={"lapa": _evidence_bundle(tmp_path, "lapa")},
        project_root=tmp_path,
        live_warehouse_admission=True,
    )

    assert report["package_count"] == 1
    assert report["live_warehouse_admission"] is True
    assert report["training_batch_eligible"] is False
    assert report["batch_cap_enforced"] is False
    assert report["external_batch_metrics"] is None
    card = (tmp_path / "population" / "dataset_card.md").read_text(encoding="utf-8")
    assert "Training batch composition supplied: `false`" in card
    assert "must supply the full composition and enforce the cap" in card
    package = tmp_path / "population" / "packages" / "img_ext_lapa_population" / "instances" / "p0"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["source_sha256"] == "a" * 64
    assert manifest["source_lineage"]["annotation_sha256"] == "b" * 64
    assert manifest["source_lineage"]["split_group_id"] == "external_group_" + "c" * 24
    for name, expected in manifest["file_sha256"].items():
        assert hashlib.sha256((package / name).read_bytes()).hexdigest() == expected


def test_live_package_population_rejects_missing_source_lineage(tmp_path: Path) -> None:
    selection = replace(
        _selection("lapa", "img_missing_lineage", ("head_face",)), source_sha256=None
    )
    with pytest.raises(ExternalSupervisionPackageError, match="source_sha256"):
        materialize_qualified_train_only_packages(
            [selection],
            destination=tmp_path / "missing_lineage",
            provenance=_load_provenance(),
            inventory=_load_inventory(),
            evidence_bundles_by_source={"lapa": _evidence_bundle(tmp_path, "lapa")},
            project_root=tmp_path,
            live_warehouse_admission=True,
        )


def test_materialize_refuses_ungated_source(tmp_path: Path) -> None:
    provenance = _load_provenance()
    inventory = _load_inventory()
    # Bundle with no gate artifacts on disk -> not admitted.
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    with pytest.raises(ExternalSupervisionPackageError, match="ungated|missing qualification"):
        materialize_qualified_train_only_packages(
            [_selection("lapa", "img_ungated", ("head_face",))],
            destination=tmp_path / "batch",
            provenance=provenance,
            inventory=inventory,
            evidence_bundles_by_source={
                "lapa": {
                    "schema_version": "1.0.0",
                    "artifact_type": "external_supervision_qualification_evidence_bundle",
                    "source": "lapa",
                    "gates": [],
                    "seal_sha256": "0" * 64,
                }
            },
            project_root=empty_root,
            companion_certified_rows=[
                {
                    "image_id": "real_0",
                    "source_role": "owned_photo",
                    "truth_tier": "human_anchor_gold",
                }
            ],
        )


def test_materialize_refuses_blocked_source(tmp_path: Path) -> None:
    provenance = _load_provenance()
    inventory = _load_inventory()
    with pytest.raises(ExternalSupervisionPackageError):
        materialize_qualified_train_only_packages(
            [
                ExternalPackageSelection(
                    source="swimsuit_preview",
                    image_id="img_blocked",
                    part_map=np.zeros((2, 2), dtype=np.uint16),
                    material_map=np.zeros((2, 2), dtype=np.uint8),
                    label_names=("skin",),
                    training_loss_weight=0.15,
                )
            ],
            destination=tmp_path / "batch",
            provenance=provenance,
            inventory=inventory,
            evidence_bundles_by_source={"swimsuit_preview": {}},
            project_root=tmp_path,
        )


def test_require_qualification_rejects_gold_claims() -> None:
    with pytest.raises(ExternalSupervisionPackageError, match="human-anchor gold"):
        require_external_package_qualification(
            {
                "source_role": EXTERNAL_LABEL_ROLE,
                "external_qualification": {
                    "admitted": True,
                    "source": "lapa",
                    "truth_tier": "weighted_pseudo_label",
                    "truth_partition": "train",
                    "holdout_eligible": False,
                    "dataset_volume_eligible": False,
                    "counts_as_human_anchor_gold": True,
                    "evidence_bundle_sha256": "a" * 64,
                    "completed_gates": ["official_license_recorded"],
                },
            }
        )
