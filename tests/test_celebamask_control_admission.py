from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from maskfactory.vlm.celebamask_control_admission import (
    CelebAMaskControlAdmissionError,
    _assign_partitions,
    _parse_hq_mapping,
    _parse_identities,
    verify_celebamask_control_admission,
)
from maskfactory.vlm.critic_catalog import canonical_sha256


def _document() -> dict:
    records = []
    for index, (outcome, defect) in enumerate(
        (
            ("valid_mask", None),
            ("known_defect", "boundary"),
            ("valid_mask", None),
            ("known_defect", "missing_area"),
        )
    ):
        records.append(
            {
                "sample_id": f"sample_{index}",
                "partition": "calibration" if index < 2 else "qualification_holdout",
                "identity_id": index // 2,
                "split_group_id": f"group_{index // 2}",
                "expected_outcome": outcome,
                "defect_type": defect,
                "critic_corpus_control_eligible": True,
                "critic_role_authority": False,
                "gold_or_production_authority": False,
            }
        )
    value = {
        "schema_version": "maskfactory.celebamask_control_admission.v1",
        "critic_corpus_controls_frozen": True,
        "critic_role_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "admitted_count": 4,
        "excluded_count": 1,
        "records": records,
        "excluded_records": [{"critic_corpus_control_eligible": False}],
    }
    value["self_sha256"] = canonical_sha256(value)
    return value


def test_metadata_parsers_bind_exact_identity(tmp_path: Path) -> None:
    mapping = tmp_path / "mapping.txt"
    mapping.write_text("idx orig_idx orig_file\n0 8 000009.jpg\n1 9 000010.jpg\n", encoding="utf-8")
    assert _parse_hq_mapping(mapping) == {0: "000009.jpg", 1: "000010.jpg"}

    identity = tmp_path / "identity.txt"
    identity.write_text(
        "\n".join(f"{index:06d}.jpg {index}" for index in range(1, 202_600)) + "\n",
        encoding="utf-8",
    )
    parsed = _parse_identities(identity)
    assert parsed["000009.jpg"] == 9
    assert hashlib.sha256(identity.read_bytes()).hexdigest()


def test_partition_assignment_keeps_identity_and_split_groups_together() -> None:
    records = [
        {
            "sample_id": "a",
            "identity_id": 1,
            "split_group_id": "x",
            "expected_outcome": "valid_mask",
            "canonical_label": "hair",
        },
        {
            "sample_id": "b",
            "identity_id": 1,
            "split_group_id": "y",
            "expected_outcome": "known_defect",
            "canonical_label": "hair",
        },
        {
            "sample_id": "c",
            "identity_id": 2,
            "split_group_id": "y",
            "expected_outcome": "valid_mask",
            "canonical_label": "neck",
        },
    ]
    _assign_partitions(records)
    assert len({record["partition"] for record in records}) == 1


def test_verifier_rejects_identity_leak_and_authority_upgrade() -> None:
    value = _document()
    verify_celebamask_control_admission(value)
    value["records"][1]["partition"] = "qualification_holdout"
    value["self_sha256"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "self_sha256"}
    )
    with pytest.raises(CelebAMaskControlAdmissionError, match="leaked"):
        verify_celebamask_control_admission(value)

    value = _document()
    value["critic_role_authority_granted"] = True
    value["self_sha256"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "self_sha256"}
    )
    with pytest.raises(CelebAMaskControlAdmissionError, match="authority"):
        verify_celebamask_control_admission(value)
