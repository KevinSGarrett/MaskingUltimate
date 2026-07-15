import re
from pathlib import Path

from click.testing import CliRunner
from tools.generate_ontology_version_reference import DEFAULT_OUTPUT, render_reference

from maskfactory.cli import main

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "Plan"


def test_generated_ontology_version_reference_is_current_and_exact() -> None:
    rendered = render_reference()
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == rendered
    assert "`0..55` / 56" in rendered
    assert "`0..64` / 65" in rendered
    assert rendered.count("| 56 | `left_areola` |") == 1
    assert rendered.count("| 64 | `right_scrotal_region` |") == 1
    assert "approved, inactive v2" in rendered.lower()


def test_numbered_docs_have_no_unqualified_legacy_class_conflict() -> None:
    documents = sorted(
        path for path in PLAN.glob("*.md") if re.match(r"^(?:0[0-9]|1[0-7])_", path.name)
    )
    assert len(documents) == 18
    obsolete = []
    for path in documents:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "57-class" in line.lower() and not any(
                word in line.lower() for word in ("obsolete", "invalid")
            ):
                obsolete.append(f"{path.name}:{line_number}")
    assert obsolete == []
    required_v2_pointers = {
        "00_MASTER_INDEX.md",
        "01_PROJECT_CHARTER_AND_SCOPE.md",
        "02_MASK_ONTOLOGY_SPEC.md",
        "04_DATA_SCHEMAS_AND_MANIFESTS.md",
        "11_HUMAN_REVIEW_WORKFLOW.md",
        "12_DATASET_TRAINING_ACTIVE_LEARNING.md",
        "17_MULTI_PERSON_MULTI_CHARACTER_MASKING_SPEC.md",
    }
    for path in documents:
        if path.name in required_v2_pointers:
            text = path.read_text(encoding="utf-8")
            assert "body_parts_v2" in text or "doc 18" in text.lower(), path.name


def test_items_master_and_tracker_metadata_match_live_item_scope() -> None:
    item_files = sorted((PLAN / "Items").glob("[0-9][0-9]_ITEMS_*.md"))
    item_files = [path for path in item_files if path.name != "00_ITEMS_MASTER_INDEX.md"]
    counts = {
        path.name: len(re.findall(r"^- \[[ xX]\] MF-", path.read_text(encoding="utf-8"), re.M))
        for path in item_files
    }
    master = (PLAN / "Items" / "00_ITEMS_MASTER_INDEX.md").read_text(encoding="utf-8")
    tracker = (PLAN / "Tracker" / "tracker.py").read_text(encoding="utf-8")
    expected = int(re.search(r"^EXPECTED_ITEM_COUNT = (\d+)$", tracker, re.M).group(1))
    assert sum(counts.values()) == expected
    assert f"**Total items: {expected}**" in master
    for name, count in counts.items():
        assert re.search(rf"\| {re.escape(name)} .* \| {count} \|", master)
    assert f"{expected} action items across phases P0-P8" in tracker
    assert "(D1-D11) and Goals (G1-G9)" in tracker


def test_cli_help_exposes_versioned_authority_without_activating_v2() -> None:
    runner = CliRunner()
    root_help = runner.invoke(main, ["--help"])
    draft_help = runner.invoke(main, ["draft", "--help"])
    dataset_help = runner.invoke(main, ["dataset", "build", "--help"])
    verify_help = runner.invoke(main, ["verify-package", "--help"])
    assert all(
        result.exit_code == 0 for result in (root_help, draft_help, dataset_help, verify_help)
    )
    assert "active v1" in root_help.output and "gated v2" in root_help.output
    assert "56" in draft_help.output and "65" in draft_help.output
    assert "body_parts_v1" in dataset_help.output and "body_parts_v2" in dataset_help.output
    assert "manifest ontology" in verify_help.output
