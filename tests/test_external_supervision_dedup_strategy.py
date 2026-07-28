from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.external_supervision_dedup_strategy import (
    PROOF_TIER,
    STRATEGY_ID,
    SplitDedupStrategyError,
    build_bounded_sample_dedup_probe,
    build_split_dedup_strategy_receipt,
    publish_split_dedup_strategy_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def _sample_fixture(tmp_path: Path):
    from test_external_supervision_dedup import _fixture

    return _fixture(tmp_path)


def test_strategy_receipt_is_static_and_never_admits():
    receipt = build_split_dedup_strategy_receipt(project_root=ROOT)
    assert receipt["proof_tier"] == PROOF_TIER
    assert receipt["strategy_id"] == STRATEGY_ID
    assert receipt["status"] == "STRATEGY_DEFERRED"
    assert receipt["admission_ready"] is False
    assert receipt["full_corpus_materialized"] is False
    assert receipt["split_dedup_gate_satisfied"] is False
    assert receipt["source_masks_are_gold"] is False
    assert receipt["any_source_admitted"] is False
    assert len(receipt["strategy_doc_sha256"]) == 64


def test_strategy_receipt_rejects_admission_overclaim(tmp_path: Path):
    receipt = build_split_dedup_strategy_receipt(project_root=ROOT)
    receipt["admission_ready"] = True
    with pytest.raises(SplitDedupStrategyError, match="admission_ready"):
        publish_split_dedup_strategy_receipt(receipt, tmp_path / "bad.json")


def test_bounded_sample_probe_wraps_algorithm_without_admission(tmp_path: Path):
    roots, manifests = _sample_fixture(tmp_path)
    probe = build_bounded_sample_dedup_probe(manifest_paths=manifests, source_roots=roots)
    assert probe["proof_tier"] == PROOF_TIER
    assert probe["status"] == "STATIC_SAMPLE_ONLY"
    assert probe["admission_ready"] is False
    assert probe["full_corpus_materialized"] is False
    assert probe["sample_record_count"] == 5
    assert probe["sample_evidence"]["status"] == "PASS"
