import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATIONS = ROOT / "configs" / "civitai_classifications.json"


def _load() -> dict:
    return json.loads(CLASSIFICATIONS.read_text(encoding="utf-8"))


def test_every_manifest_record_has_a_valid_primary_classification() -> None:
    data = _load()
    allowed = set(data["policy"]["allowed_classifications"])
    records = data["records"]

    assert data["record_count"] == 79
    assert len(records) == 79
    assert len({(record["id"], record["file_name"]) for record in records}) == 79
    assert {record["classification"] for record in records} <= allowed
    assert all(record["authority"] == "proposal_or_reference_only" for record in records)


def test_metadata_only_variants_are_explicitly_disposed() -> None:
    metadata_only = [
        record for record in _load()["records"] if record["download_status"] == "metadata_only"
    ]

    assert len(metadata_only) == 6
    assert all(
        record["metadata_only_disposition"] == "superseded_by_downloaded_variant"
        for record in metadata_only
    )
    assert all(record["download_action"] == "unnecessary" for record in metadata_only)
    assert all(record["superseded_by"] for record in metadata_only)


def test_rejected_assets_are_deliberate_and_v1_out_of_scope() -> None:
    rejected = {
        record["file_name"] for record in _load()["records"] if record["classification"] == "reject"
    }

    assert rejected == {"rotomakerWith_v3.zip", "breastExpansion_v10.zip"}
