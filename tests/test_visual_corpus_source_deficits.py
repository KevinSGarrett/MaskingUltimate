from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from tools.build_visual_corpus_source_deficits import build

from maskfactory.ontology_v2_authority_pilot import OntologyV2AuthorityPilotError
from maskfactory.vlm.corpus_source_deficits import (
    VisualCorpusSourceDeficitError,
    verify_visual_corpus_source_deficits,
)

ROOT = Path(__file__).resolve().parents[1]


def test_repository_sources_fail_closed_without_inventing_66_label_coverage(
    tmp_path: Path,
) -> None:
    report = build(tmp_path / "deficits.json")
    verify_visual_corpus_source_deficits(report)
    assert report["required_canonical_label_count"] == 66
    assert report["eligible_canonical_label_count"] == 0
    assert report["missing_canonical_label_count"] == 66
    assert report["promotion_allowed"] is False
    assert report["qualification_corpus_ready"] is False
    assert report["source_population"]["real_regression_case_count"] == 14
    assert report["source_population"]["pilot_reference_only_count"] == 4
    assert report["source_population"]["quarantined_historical_package_count"] == 641


def test_coarse_external_aliases_are_diagnostic_not_canonical_coverage(
    tmp_path: Path,
) -> None:
    report = build(tmp_path / "deficits.json")
    aliases = report["source_population"]["noncanonical_target_label_counts"]
    assert aliases == {
        "face_external_reference": 2,
        "hair_external_reference": 2,
        "left_foot_external_reference": 2,
        "left_hand_region_external_reference": 2,
        "right_arm_external_reference": 4,
        "torso_skin_external_reference": 2,
    }
    assert report["source_population"]["regression_case_classifications"] == {
        "noncanonical_or_coarse_diagnostic": 14
    }


def test_unsided_and_fine_anatomy_ambiguity_never_becomes_positive(
    tmp_path: Path,
) -> None:
    report = build(tmp_path / "deficits.json")
    by_label = {row["canonical_label"]: row for row in report["labels"]}
    for label in (
        "left_nipple",
        "right_nipple",
        "left_areola",
        "right_areola",
        "penis_shaft",
        "glans_penis",
        "left_scrotal_region",
        "right_scrotal_region",
    ):
        assert by_label[label]["source_status"] == "missing_qualified_real_positive"
    assert by_label["left_nipple"]["ambiguous_fine_or_laterality_ids"]
    assert by_label["penis_shaft"]["ambiguous_fine_or_laterality_ids"]


def test_reference_and_quarantine_authority_drift_fails_closed() -> None:
    pilot = json.loads(
        (ROOT / "configs/ontology_v2_authority_pilot.generated.json").read_text(encoding="utf-8")
    )
    reference = next(
        row for row in pilot["images"] if row["source_kind"] == "reference_library_coverage"
    )
    reference["mask_truth_authority"] = True
    # Re-sealing the upstream artifact does not make the invalid authority valid.
    from maskfactory.ontology_v2_authority_pilot import canonical_sha256

    pilot["self_sha256"] = canonical_sha256(pilot)
    with pytest.raises(
        OntologyV2AuthorityPilotError,
        match="pilot_source_promoted_to_mask_truth",
    ):
        from maskfactory.vlm.corpus_source_deficits import (
            build_visual_corpus_source_deficits,
            sha256_bytes,
        )

        regression_raw = (ROOT / "qa/vlm_eval/visual_regression_v2_real/manifest.json").read_bytes()
        history_raw = (
            ROOT / "qa/live_verification/historical_caa_641_to_220_reconciliation_20260722.json"
        ).read_bytes()
        build_visual_corpus_source_deficits(
            regression_manifest=json.loads(regression_raw),
            authority_pilot=pilot,
            historical_caa_evidence=json.loads(history_raw),
            input_file_sha256s={
                "ontology": sha256_bytes((ROOT / "configs/ontology_v2.yaml").read_bytes()),
                "regression_manifest": sha256_bytes(regression_raw),
                "authority_pilot": "a" * 64,
                "historical_caa_evidence": sha256_bytes(history_raw),
            },
        )


def test_report_hash_and_label_summary_drift_fail_closed(tmp_path: Path) -> None:
    report = build(tmp_path / "deficits.json")
    drifted = deepcopy(report)
    drifted["missing_canonical_labels"].pop()
    with pytest.raises(VisualCorpusSourceDeficitError, match="hash drift"):
        verify_visual_corpus_source_deficits(drifted)
