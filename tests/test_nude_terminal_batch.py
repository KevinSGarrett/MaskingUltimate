from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.nude_record_qualification import verify_complete_panel_evidence
from maskfactory.nude_terminal_batch import NudeTerminalBatchError, process_terminal_batch
from test_nude_record_qualification import _panels, _record


def _accepted(tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    return {"record": _record(bundle["panel_bundle_sha256"]), "panels": panels}


def test_batch_qualifies_valid_record_and_continues_after_invalid_record(tmp_path: Path) -> None:
    accepted = _accepted(tmp_path / "accepted")
    invalid = copy.deepcopy(accepted)
    invalid["record"]["hard_qc"]["status"] = "fail"
    output = tmp_path / "out"
    summary = process_terminal_batch(
        [accepted, invalid], source_manifest_sha256="a" * 64, output_root=output
    )
    assert summary["record_count"] == 2
    assert summary["qualified_count"] == 1
    assert summary["error_count"] == 1
    assert summary["outcome_counts"] == {"accepted": 1, "processing_error": 1}
    assert summary["authority"] == "qualification_receipts_only_no_certificate_or_gold_authority"
    assert summary["completion_claimed"] is False
    assert (output / "records/record_000000_accepted.json").is_file()
    error = json.loads((output / "records/record_000001_processing_error.json").read_text())
    assert error["error"]["reason"] == "hard_qc_veto"


def test_batch_replay_is_exact_and_conflicting_existing_output_fails(tmp_path: Path) -> None:
    accepted = _accepted(tmp_path / "accepted")
    output = tmp_path / "out"
    first = process_terminal_batch([accepted], source_manifest_sha256="b" * 64, output_root=output)
    second = process_terminal_batch([accepted], source_manifest_sha256="b" * 64, output_root=output)
    assert first == second
    path = output / "records/record_000000_accepted.json"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(NudeTerminalBatchError, match="immutable_output_conflict"):
        process_terminal_batch([accepted], source_manifest_sha256="b" * 64, output_root=output)


def test_output_root_is_bound_to_one_source_manifest(tmp_path: Path) -> None:
    accepted = _accepted(tmp_path / "accepted")
    output = tmp_path / "out"
    process_terminal_batch([accepted], source_manifest_sha256="8" * 64, output_root=output)
    with pytest.raises(NudeTerminalBatchError, match="immutable_output_conflict"):
        process_terminal_batch([accepted], source_manifest_sha256="9" * 64, output_root=output)


def test_batch_routes_input_quarantine_without_panels(tmp_path: Path) -> None:
    record = {
        "sample_id": "sample-quarantine",
        "source_sha256": "1" * 64,
        "source_role": "reference_only_no_mask_truth",
        "registry_sha256": "2" * 64,
        "shard_sha256": "3" * 64,
        "outcome": "quarantined",
        "reasons": ["decode_failed"],
        "input_report_sha256": "4" * 64,
    }
    summary = process_terminal_batch(
        [{"record": record, "panels": None}],
        source_manifest_sha256="c" * 64,
        output_root=tmp_path / "out",
    )
    assert summary["outcome_counts"] == {"quarantined": 1}
    artifact = json.loads((tmp_path / "out/records/record_000000_quarantined.json").read_text())
    assert artifact["payload"]["qualification_evidence"]["mask_generated"] is False


def test_batch_rejects_bad_manifest_hash_and_empty_population(tmp_path: Path) -> None:
    with pytest.raises(NudeTerminalBatchError, match="source_manifest_sha256_invalid"):
        process_terminal_batch([], source_manifest_sha256="bad", output_root=tmp_path)
    with pytest.raises(NudeTerminalBatchError, match="entries_invalid"):
        process_terminal_batch([], source_manifest_sha256="d" * 64, output_root=tmp_path)


def test_summary_binds_input_file_hash_semantics(tmp_path: Path) -> None:
    accepted = _accepted(tmp_path / "accepted")
    encoded = (json.dumps(accepted, sort_keys=True) + "\n").encode()
    source_hash = hashlib.sha256(encoded).hexdigest()
    summary = process_terminal_batch(
        [accepted], source_manifest_sha256=source_hash, output_root=tmp_path / "out"
    )
    assert summary["source_manifest_sha256"] == source_hash
