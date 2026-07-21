from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from maskfactory.qa.core_drafts import (
    FINGER_IDS,
    CoreDraftError,
    core_part_labels,
    verify_core_draft_contract,
    write_core_draft_contract,
)


def test_core_registry_is_exactly_v1_minus_ten_finger_atomics() -> None:
    labels = core_part_labels()
    assert len(labels) == 46
    assert {label.id for label in labels} == set(range(56)) - FINGER_IDS


def test_core_contract_writes_all_slots_with_honest_states_and_hashes(tmp_path: Path) -> None:
    part_map = np.zeros((20, 30), dtype=np.uint16)
    part_map[2:8, 4:10] = 2
    part_map[8:18, 6:12] = 7
    manifest = write_core_draft_contract(part_map, tmp_path)
    document = verify_core_draft_contract(manifest, tmp_path)
    by_id = {row["id"]: row for row in document["records"]}
    assert by_id[0]["state"] == "drafted"
    assert by_id[2]["state"] == "drafted"
    assert by_id[7]["state"] == "drafted"
    assert by_id[54]["state"] == "disabled"
    assert by_id[12]["state"] == "not_visible"


def test_core_contract_detects_tampering_and_unknown_ids(tmp_path: Path) -> None:
    bad = np.full((3, 3), 99, dtype=np.uint16)
    with pytest.raises(CoreDraftError, match="outside"):
        write_core_draft_contract(bad, tmp_path)
    manifest = write_core_draft_contract(np.zeros((3, 3), dtype=np.uint16), tmp_path)
    document = json.loads(manifest.read_text())
    slot = tmp_path / document["records"][0]["path"]
    slot.write_bytes(b"tampered")
    with pytest.raises(CoreDraftError, match="hash"):
        verify_core_draft_contract(manifest, tmp_path)
