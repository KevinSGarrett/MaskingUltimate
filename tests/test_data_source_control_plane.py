import json
from pathlib import Path

from click.testing import CliRunner

from maskfactory.cli import main


def test_external_supervision_cli_reports_unmet_gates_then_admits_exact_gate_set():
    runner = CliRunner()
    pending = runner.invoke(main, ["external-supervision", "admission", "lapa"])
    assert pending.exit_code == 0, pending.output
    document = json.loads(pending.output)
    assert document["legally_eligible"] is True
    assert document["admitted"] is False
    assert "visual_alignment_qa_passed" in document["unmet_gates"]

    gates = [
        "official_license_recorded",
        "deterministic_remap_tested",
        "source_hash_manifested",
        "visual_alignment_qa_passed",
        "split_dedup_passed",
    ]
    command = ["external-supervision", "admission", "lapa"]
    for gate in gates:
        command.extend(["--completed-gate", gate])
    admitted = runner.invoke(main, command)
    assert admitted.exit_code == 0, admitted.output
    result = json.loads(admitted.output)
    assert result["admitted"] is True
    assert result["truth_tier"] == "weighted_pseudo_label"


def test_reference_status_cli_is_read_only_for_missing_database(tmp_path: Path):
    missing = tmp_path / "missing.sqlite"
    result = CliRunner().invoke(
        main,
        ["reference-library", "status", "--database", str(missing)],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"exists": False, "path": str(missing)}
    assert not missing.exists()


def test_daz_cli_is_exposed_as_guarded_doctor_only_at_foundation_stage():
    result = CliRunner().invoke(main, ["daz", "--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output
