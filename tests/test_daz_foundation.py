import copy
import sqlite3
from pathlib import Path

import pytest

from maskfactory.daz.policy import (
    DazPolicyError,
    inspect_acquisition_queue,
    validate_daz_configuration,
    validate_synthetic_authority,
    validate_synthetic_share,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "daz"


def _synthetic() -> dict:
    return copy.deepcopy(validate_daz_configuration(CONFIG)["training_policy"])


def test_daz_configuration_is_hidden_default_disabled_and_adult_assets_remain_eligible():
    documents = validate_daz_configuration(CONFIG)
    assert documents["worker"]["enabled"] is False
    assert documents["worker"]["window_visibility"] == "hidden"
    assert (
        documents["operating_profile"]["content_policy"]["adult_and_nsfw_assets_eligible"] is True
    )
    assert documents["training_policy"]["truth_tier"] == "weighted_pseudo_label"


@pytest.mark.parametrize(
    "field,value",
    [
        ("truth_tier", "human_anchor_gold"),
        ("truth_partition", "holdout"),
        ("training_loss_weight", 0.26),
    ],
)
def test_synthetic_authority_rejects_gold_holdout_and_excess_weight(field: str, value):
    record = _synthetic()
    record[field] = value
    with pytest.raises(DazPolicyError):
        validate_synthetic_authority(record)


def test_synthetic_share_cap_is_hard_and_independent():
    synthetic = _synthetic()
    real = {"source_origin": "owned_photo"}
    assert validate_synthetic_share([synthetic] * 3 + [real] * 7)["synthetic_image_share"] == 0.3
    with pytest.raises(DazPolicyError, match="exceeds"):
        validate_synthetic_share([synthetic] * 4 + [real] * 6)


def test_acquisition_status_uses_only_queue_counts(tmp_path: Path):
    database = tmp_path / "queue.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE jobs (state TEXT, stage TEXT);"
        "INSERT INTO jobs VALUES ('complete','installed');"
        "INSERT INTO jobs VALUES ('pending','queued');"
        "INSERT INTO jobs VALUES ('pending','queued');"
    )
    connection.commit()
    connection.close()
    report = inspect_acquisition_queue(database, query_counts=True)
    assert report == {
        "path": str(database),
        "exists": True,
        "bytes": database.stat().st_size,
        "wal_exists": False,
        "count_query_skipped_while_live": False,
        "total_jobs": 3,
        "states": {"complete": 1, "pending": 2},
        "stages": {"installed": 1, "queued": 2},
    }
