from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.canonical_polygon_source_candidates import (
    CanonicalPolygonSourceCandidateError,
    build_canonical_polygon_source_candidates,
    verify_canonical_polygon_source_candidates,
)


def _registry() -> dict:
    return {
        "self_sha256": "1" * 64,
        "datasets": [
            {
                "dataset_id": "dataset_a",
                "primary_role": "polygon_external_supervision",
                "annotation_format": "coco_segmentation",
                "license_claim": "CC BY 4.0",
                "lineage_group": "family_a",
            },
            {
                "dataset_id": "dataset_b",
                "primary_role": "polygon_external_supervision",
                "annotation_format": "coco_segmentation",
                "license_claim": "license review pending",
                "lineage_group": "family_b",
            },
        ],
    }


def _record(index: int, partition: str, *, raw: str = "anus", dataset: str = "dataset_a") -> dict:
    candidate = "anus" if raw == "anus" else "vulva_external_region"
    kind = "anatomy" if raw == "anus" else "source_alias_for_visible_external_anatomy"
    return {
        "sample_id": f"sample_{index}",
        "dataset_id": dataset,
        "source_role": "polygon_external_supervision",
        "source_sha256": f"{100 + index:064x}",
        "annotation_ref": f"{dataset}/{partition}/annotations.json",
        "annotation_file_sha256": f"{200 + index:064x}",
        "split_group_id": f"group_{index}",
        "assigned_partition": partition,
        "outcome": "hard_qc_pass_candidate",
        "external_mask_authority": "machine_hard_qc_candidate_only",
        "masks": [
            {
                "raw_label": raw,
                "candidate_label": candidate,
                "candidate_kind": kind,
                "mask_sha256": f"{300 + index:064x}",
                "mask_pixels": 25,
                "mask_bbox_xyxy": [1, 1, 6, 6],
                "segmentation_encoding": "coco_polygon",
                "binary_mask_materialized": True,
                "production_authority": False,
                "gold_authority": False,
            }
        ],
    }


def test_selects_exact_split_disjoint_anus_sources_without_granting_authority() -> None:
    records = [_record(1, "train"), _record(2, "test")]
    report = build_canonical_polygon_source_candidates(
        records=records,
        registry=_registry(),
        records_file_sha256="2" * 64,
        registry_file_sha256="3" * 64,
        per_partition=1,
    )
    verify_canonical_polygon_source_candidates(report)
    assert report["selected_count"] == 2
    assert report["selected_by_partition"] == {"test": 1, "train": 1}
    assert all(not row["critic_positive_control_eligible"] for row in report["selected"])
    assert report["authority_claimed"] is False


def test_vagina_is_retained_as_bounded_alias_not_exact_vulva_control() -> None:
    records = [
        _record(1, "train"),
        _record(2, "test"),
        _record(3, "train", raw="vagina"),
        _record(4, "test", raw="vagina"),
    ]
    report = build_canonical_polygon_source_candidates(
        records=records,
        registry=_registry(),
        records_file_sha256="2" * 64,
        registry_file_sha256="3" * 64,
        per_partition=1,
    )
    assert report["bounded_alias_diagnostic_counts"] == {
        "test:vagina": 1,
        "train:vagina": 1,
    }
    assert {row["canonical_label"] for row in report["selected"]} == {"anus"}


def test_ineligible_license_and_duplicate_split_group_fail_closed() -> None:
    records = [
        _record(1, "train"),
        _record(2, "test"),
        _record(3, "train", dataset="dataset_b"),
    ]
    records[1]["split_group_id"] = records[0]["split_group_id"]
    with pytest.raises(
        CanonicalPolygonSourceCandidateError,
        match="insufficient exact split-disjoint sources:test",
    ):
        build_canonical_polygon_source_candidates(
            records=records,
            registry=_registry(),
            records_file_sha256="2" * 64,
            registry_file_sha256="3" * 64,
            per_partition=1,
        )


def test_authority_mutation_breaks_seal_and_verifier() -> None:
    report = build_canonical_polygon_source_candidates(
        records=[_record(1, "train"), _record(2, "test")],
        registry=_registry(),
        records_file_sha256="2" * 64,
        registry_file_sha256="3" * 64,
        per_partition=1,
    )
    drifted = deepcopy(report)
    drifted["selected"][0]["critic_positive_control_eligible"] = True
    with pytest.raises(CanonicalPolygonSourceCandidateError, match="self hash mismatch"):
        verify_canonical_polygon_source_candidates(drifted)
