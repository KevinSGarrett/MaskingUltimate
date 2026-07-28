from pathlib import Path

import numpy as np
import pytest

from maskfactory.fusion.zorder import ZOrderDecision, apply_zorder
from maskfactory.ontology import get_ontology
from maskfactory.qa.core_drafts import (
    CoreDraftError,
    core_part_labels,
    verify_core_draft_contract,
    write_core_draft_contract,
)


def test_zorder_boosts_only_authorized_contested_evidence() -> None:
    authority = get_ontology()
    names = ("hair", "head_face", "neck")
    scores = np.zeros((3, 3, 3), dtype=np.float32)
    scores[0, 1, 1] = 0.8
    scores[1, 1, 1] = 0.7
    scores[2, 1, 1] = 0.8
    scores[0, 0, 0] = 0.8
    scores[1, 0, 0] = 0.7
    contested = np.zeros((3, 3), dtype=bool)
    contested[1, 1] = True

    records = apply_zorder(
        scores,
        names,
        contested,
        (ZOrderDecision("neck", "head_face", "neck_overlap"),),
        authority,
    )

    assert [(record.occluding_part, record.occluded_part, record.contested_pixels) for record in records] == [
        ("hair", "head_face", 1),
        ("hair", "neck", 1),
        ("neck", "head_face", 1),
    ]
    assert scores[0, 1, 1] > 1.0
    assert scores[0, 0, 0] == pytest.approx(0.8)


def test_core_draft_contract_writes_and_detects_tampered_slot(tmp_path: Path) -> None:
    labels = core_part_labels()
    drafted = next(label for label in labels if label.id != 0)
    part_map = np.zeros((5, 7), dtype=np.uint8)
    part_map[1:4, 2:5] = drafted.id

    manifest = write_core_draft_contract(part_map, tmp_path)
    document = verify_core_draft_contract(manifest, tmp_path)

    assert document["core_part_count"] == 46
    record = next(row for row in document["records"] if row["id"] == drafted.id)
    assert record["state"] == ("drafted" if drafted.enabled else "disabled")
    assert record["pixel_count"] == 9

    slot = tmp_path / record["path"]
    slot.write_bytes(b"tampered")
    with pytest.raises(CoreDraftError, match="hash mismatch"):
        verify_core_draft_contract(manifest, tmp_path)


def test_core_draft_contract_rejects_unknown_part_id(tmp_path: Path) -> None:
    with pytest.raises(CoreDraftError, match="outside the ontology"):
        write_core_draft_contract(np.array([[999]], dtype=np.int16), tmp_path)
