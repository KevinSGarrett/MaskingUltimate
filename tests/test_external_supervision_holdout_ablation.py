from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maskfactory.datasets.authority import serialized_reader_capabilities
from maskfactory.external_supervision import EXTERNAL_LABEL_ROLE
from maskfactory.external_supervision_holdout_ablation import (
    ExternalHoldoutAblationError,
    assert_only_ablation_active_external_rows,
    decide_active_external_supervision,
    discover_holdout_ablation_report,
    evaluate_source_label_ablation,
    filter_active_selections,
    require_ablation_report,
    require_frozen_human_anchor_holdout,
)
from maskfactory.external_supervision_packages import (
    ExternalSupervisionPackageError,
    assert_builder_accepts_only_gated_external_rows,
)
from maskfactory.training.launch import TrainingLaunchError, validate_training_dataset_authority
from maskfactory.validation import validate_document

FINGERPRINT = "a" * 64


def _minimal_training_dataset(tmp_path: Path, *, count: int = 200) -> Path:
    root = tmp_path / "bodyparts@v3"
    root.mkdir(parents=True)
    instances = [f"img_{index:012d}_p0" for index in range(count)]
    train_end = max(1, count - 1)
    (root / "build_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "instances": {
                    "train": instances[:train_end],
                    "val": instances[train_end:],
                    "calibration": [],
                    "test_holdout": [],
                    "hard_case_holdout": [],
                },
                "trainer_inputs": ["train.txt", "val.txt", "sample_weights.json", "part_seg"],
                "holdout_trainer_read_path": None,
                "calibration_trainer_read_path": None,
                "protected_anchor_ids": "protected_anchor_ids.txt",
                "reader_capabilities": serialized_reader_capabilities(),
                "truth_metrics": {"certified_training_package_count": count},
                "reference_benchmark_isolation": {
                    "schema_version": "1.0.0",
                    "passed": True,
                    "benchmark_count": 2500,
                    "benchmark_fingerprint": "f" * 64,
                    "record_count": count,
                    "issues": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "sample_weights.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "samples": {
                    sample_id: {
                        "truth_tier": "human_anchor_gold",
                        "truth_partition": "train",
                        "training_loss_weight": 1.0 if index < train_end else 0.0,
                    }
                    for index, sample_id in enumerate(instances)
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "protected_anchor_ids.txt").write_text("", encoding="utf-8")
    return root


def _holdout() -> dict:
    return {
        "frozen_holdout_id": "human_anchor_holdout_fixture_v1",
        "fingerprint_sha256": FINGERPRINT,
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "source_role": "owned_photo",
        "external_labels_may_enter_holdout": False,
    }


def _passing_buckets() -> dict:
    return {
        name: {"passed": True, "observed_delta": 0.0, "noninferiority_margin": 0.01}
        for name in ("hard_bucket", "identity", "boundary", "calibration")
    }


def _row(
    *,
    source: str = "lapa",
    labels: list[str] | None = None,
    delta: float = 0.02,
    margin: float = 0.01,
    buckets: dict | None = None,
) -> dict:
    return {
        "source": source,
        "label_scope": labels or ["head_face", "hair"],
        "primary_metric": "miou",
        "observed_delta": delta,
        "noninferiority_margin": margin,
        "frozen_holdout_fingerprint_sha256": FINGERPRINT,
        "truth_tier": "weighted_pseudo_label",
        "counts_as_human_anchor_gold": False,
        "regression_buckets": buckets if buckets is not None else _passing_buckets(),
    }


def test_frozen_holdout_required_and_rejects_external_authority() -> None:
    require_frozen_human_anchor_holdout(_holdout())
    with pytest.raises(ExternalHoldoutAblationError, match="human_anchor_gold"):
        require_frozen_human_anchor_holdout({**_holdout(), "truth_tier": "weighted_pseudo_label"})
    with pytest.raises(ExternalHoldoutAblationError, match="external or synthetic"):
        require_frozen_human_anchor_holdout({**_holdout(), "source_role": EXTERNAL_LABEL_ROLE})


def test_non_regressing_source_label_remains_active() -> None:
    decision = evaluate_source_label_ablation(_row(), holdout=_holdout())
    assert decision.active is True
    report = decide_active_external_supervision(holdout=_holdout(), ablations=[_row()])
    assert report["active_count"] == 1
    assert report["inactive_count"] == 0
    assert report["live_holdout_executed"] is False
    assert report["admission_ready"] is False
    assert report["proof_tier"] == "STATIC_PASS"


def test_primary_and_bucket_regressions_deactivate() -> None:
    primary_fail = evaluate_source_label_ablation(
        _row(delta=-0.05, margin=0.01), holdout=_holdout()
    )
    assert primary_fail.active is False
    assert "primary metric" in primary_fail.reason

    buckets = _passing_buckets()
    buckets["identity"] = {
        "passed": False,
        "observed_delta": -0.2,
        "noninferiority_margin": 0.01,
    }
    identity_fail = evaluate_source_label_ablation(_row(buckets=buckets), holdout=_holdout())
    assert identity_fail.active is False
    assert "identity" in identity_fail.reason

    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[
            _row(source="lapa", labels=["head_face", "hair"], delta=0.01),
            _row(source="lv_mhp", labels=["coarse_limb_region"], delta=-0.2),
        ],
    )
    assert report["active_count"] == 1
    assert report["inactive_count"] == 1
    assert report["inactive_source_label_scopes"][0]["source"] == "lv_mhp"


def test_builder_refuses_ablation_active_without_report() -> None:
    rows = [
        {
            "image_id": "ext_1",
            "source_role": EXTERNAL_LABEL_ROLE,
            "truth_tier": "weighted_pseudo_label",
            "truth_partition": "train",
            "external_qualification_admitted": True,
            "dataset_volume_eligible": False,
            "training_loss_weight": 0.15,
            "external_source": "lapa",
            "label_names": ["head_face", "hair"],
            "ablation_active": True,
        }
    ]
    with pytest.raises(ExternalSupervisionPackageError, match="without sealed"):
        assert_builder_accepts_only_gated_external_rows(rows)


def test_builder_accepts_only_active_scopes_from_report() -> None:
    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[_row(source="lapa", labels=["head_face", "hair"])],
    )
    active_row = {
        "image_id": "ext_1",
        "source_role": EXTERNAL_LABEL_ROLE,
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "external_qualification_admitted": True,
        "dataset_volume_eligible": False,
        "training_loss_weight": 0.15,
        "external_source": "lapa",
        "label_names": ["head_face", "hair"],
        "ablation_active": True,
    }
    assert_builder_accepts_only_gated_external_rows([active_row], ablation_report=report)

    inactive_claim = copy.deepcopy(active_row)
    inactive_claim["external_source"] = "lv_mhp"
    inactive_claim["label_names"] = ["coarse_limb_region"]
    with pytest.raises(ExternalSupervisionPackageError, match="ablation-inactive"):
        assert_builder_accepts_only_gated_external_rows([inactive_claim], ablation_report=report)


def test_filter_active_selections_and_assert_helpers() -> None:
    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[
            _row(source="lapa", labels=["head_face", "hair"]),
            _row(source="celebamask_hq", labels=["head_face"], delta=-0.5),
        ],
    )
    kept = filter_active_selections(
        [
            {"source": "lapa", "label_names": ["hair", "head_face"]},
            {"source": "celebamask_hq", "label_names": ["head_face"]},
        ],
        report,
    )
    assert len(kept) == 1
    assert kept[0]["source"] == "lapa"

    assert_only_ablation_active_external_rows(
        [
            {
                "source_role": EXTERNAL_LABEL_ROLE,
                "external_source": "lapa",
                "label_names": ["head_face", "hair"],
                "ablation_active": True,
            }
        ],
        report,
    )


def test_ablation_report_schema_valid_and_discoverable(tmp_path: Path) -> None:
    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[_row(source="lapa", labels=["head_face", "hair"])],
    )
    assert validate_document(report, "external_supervision_holdout_ablation_report") == ()
    require_ablation_report(report)

    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / "holdout_ablation_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    discovered = discover_holdout_ablation_report(packages)
    assert discovered is not None
    assert discovered["seal_sha256"] == report["seal_sha256"]
    assert discover_holdout_ablation_report(tmp_path / "missing_packages") is None


def test_launcher_refuses_ablation_active_without_bound_report(tmp_path: Path) -> None:
    root = _minimal_training_dataset(tmp_path)
    build_path = root / "build_manifest.json"
    weights_path = root / "sample_weights.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    weights = json.loads(weights_path.read_text(encoding="utf-8"))
    sample_id = next(iter(weights["samples"]))
    weights["samples"][sample_id] = {
        "image_id": sample_id.rsplit("_p", 1)[0],
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "training_loss_weight": 0.15,
        "dataset_volume_eligible": False,
        "source_role": EXTERNAL_LABEL_ROLE,
        "external_qualification_admitted": True,
        "external_source": "lapa",
        "label_names": ["head_face", "hair"],
        "ablation_active": True,
        "holdout_eligible": False,
        "counts_as_human_anchor_gold": False,
        "counts_as_autonomous_certified_gold": False,
    }
    # Keep certified dominance with one external image among 200.
    build["truth_metrics"]["certified_training_package_count"] = 199
    build["external_batch_metrics"] = {
        "total_images": 200,
        "external_images": 1,
        "certified_real_images": 199,
        "external_image_share": 0.005,
        "certified_real_image_share": 0.995,
        "maximum_combined_external_batch_fraction": 0.35,
        "certified_real_dominant": True,
    }
    build["holdout_ablation"] = {"bound": False, "live_holdout_executed": False}
    build_path.write_text(json.dumps(build), encoding="utf-8")
    weights_path.write_text(json.dumps(weights), encoding="utf-8")
    with pytest.raises(TrainingLaunchError, match="without sealed"):
        validate_training_dataset_authority(root)

    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[_row(source="lapa", labels=["head_face", "hair"])],
    )
    build["holdout_ablation"] = {
        "bound": True,
        "seal_sha256": report["seal_sha256"],
        "live_holdout_executed": False,
        "report": report,
    }
    build_path.write_text(json.dumps(build), encoding="utf-8")
    assert validate_training_dataset_authority(root) == 199
