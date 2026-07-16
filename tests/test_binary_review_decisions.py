import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.autonomy.decisions import (
    BinaryReviewError,
    build_binary_review_bundle,
    load_binary_review_bundle,
    record_binary_review_decision,
)
from maskfactory.cli import main


def _bundle(review_kind: str = "human_anchor_seal") -> dict:
    autonomous = review_kind == "autonomous_audit"
    return build_binary_review_bundle(
        {
            "schema_version": "1.0.0",
            "review_kind": review_kind,
            "image_id": "img_000000000001",
            "package_id": "img_000000000001_p0_v1",
            "truth_tier": ("autonomous_certified_gold" if autonomous else "human_anchor_gold"),
            "truth_partition": "train",
            "source_sha256": "a" * 64,
            "final_mask_set_sha256": "b" * 64,
            "evidence_sha256": "c" * 64,
            "certificate_ids": ["cert_ordinary"] if autonomous else [],
            "qa": {
                "status": "pass",
                "block_qc_ids": [],
                "format_passed": True,
                "identity_passed": True,
                "split_integrity_passed": True,
            },
        }
    )


def _write_bundle(tmp_path: Path, bundle: dict) -> Path:
    path = tmp_path / "review_bundle.json"
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return path


def test_human_anchor_approve_is_hash_chained_idempotent_and_requires_complete_qa(tmp_path: Path):
    bundle_path = _write_bundle(tmp_path, _bundle())
    ledger = tmp_path / "decisions.jsonl"
    at = datetime(2026, 7, 16, 3, 0, tzinfo=UTC)
    first = record_binary_review_decision(
        bundle_path,
        decision="approve",
        reviewer="Kevin Garrett",
        ledger_path=ledger,
        recorded_at=at,
    )
    second = record_binary_review_decision(
        bundle_path,
        decision="approve",
        reviewer="Kevin Garrett",
        ledger_path=ledger,
    )
    assert first == second
    assert first["outcome"] == "seal_human_anchor_gold"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(BinaryReviewError, match="conflicting decision"):
        record_binary_review_decision(
            bundle_path,
            decision="reject",
            reviewer="Kevin Garrett",
            ledger_path=ledger,
        )


def test_autonomous_reject_routes_repair_and_revokes_exact_certificate(tmp_path: Path):
    bundle_path = _write_bundle(tmp_path, _bundle("autonomous_audit"))
    record = record_binary_review_decision(
        bundle_path,
        decision="reject",
        reviewer="Kevin Garrett",
        ledger_path=tmp_path / "decisions.jsonl",
    )
    assert record["outcome"] == "route_bounded_repair"
    assert record["route"] == "residual_repair_queue"
    assert record["revoke_certificate"] is True
    assert record["certificate_ids"] == ["cert_ordinary"]


def test_bundle_hash_and_qa_are_fail_closed(tmp_path: Path):
    bundle = _bundle()
    bundle["qa"]["status"] = "needs_human"
    path = _write_bundle(tmp_path, bundle)
    with pytest.raises(BinaryReviewError):
        load_binary_review_bundle(path)


def test_binary_review_cli_exposes_only_approve_or_reject(tmp_path: Path):
    bundle_path = _write_bundle(tmp_path, _bundle())
    ledger = tmp_path / "decisions.jsonl"
    result = CliRunner().invoke(
        main,
        [
            "autonomy",
            "review-decision",
            "approve",
            str(bundle_path),
            "--reviewer",
            "Kevin Garrett",
            "--ledger",
            str(ledger),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["decision"] == "approve"
