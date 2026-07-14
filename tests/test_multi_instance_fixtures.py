import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from maskfactory.qa.multi_instance_fixtures import (
    MultiInstanceFixtureError,
    seal_multi_instance_fixture_set,
)


def _fixture(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = []
    for index, visible_count in enumerate((2, 4)):
        source = tmp_path / f"source_{index}.png"
        evidence = tmp_path / f"s01_{index}.json"
        Image.new("RGB", (100, 80), (index * 40, 0, 0)).save(source)
        promoted = min(visible_count, 4)
        evidence.write_text(
            json.dumps(
                {
                    "outcome": "promoted",
                    "raw_detection_count": visible_count,
                    "persons": [
                        {
                            "person_index": person,
                            "promoted": True,
                            "bbox_xyxy": [person * 20, 10, person * 20 + 15, 70],
                            "context_bbox_xyxy": [person * 20, 0, person * 20 + 20, 80],
                        }
                        for person in range(promoted)
                    ],
                }
            ),
            encoding="utf-8",
        )
        records.append(
            {
                "key": f"fixture_{index}",
                "source_path": source.name,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_origin": "generated",
                "rights_evidence": "test generated",
                "age_safety": "clear_adult",
                "age_evidence": "test fixture",
                "manual_visible_instance_count": visible_count,
                "reviewer": "fixture reviewer",
                "reviewed_at": "2026-07-11T00:00:00Z",
                "s01_evidence_path": evidence.name,
                "s01_evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                "s01_config_hash": "a" * 64,
                "model_key": "yolo11m",
            }
        )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"fixtures": records}), encoding="utf-8")
    return registry


def test_seals_distinct_manual_counts_and_configured_cap_promotions(tmp_path: Path) -> None:
    document = seal_multi_instance_fixture_set(
        _fixture(tmp_path), tmp_path / "manifest.json", project_root=tmp_path
    )
    assert document["fixture_count"] == 2
    assert [item["manual_visible_instance_count"] for item in document["fixtures"]] == [2, 4]
    assert [item["promoted_instance_count"] for item in document["fixtures"]] == [2, 4]
    assert all(not item["downstream_package_count_verified"] for item in document["fixtures"])


def test_sealer_verifies_exact_completed_downstream_package_fanout(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    document = json.loads(registry.read_text())
    fixture = document["fixtures"][0]
    image_id = "img_aaaaaaaaaaaa"
    source = tmp_path / fixture["source_path"]
    canonical = tmp_path / "data/images" / image_id
    canonical.mkdir(parents=True)
    canonical_source = canonical / "source.png"
    canonical_source.write_bytes(source.read_bytes())
    fixture["source_path"] = str(canonical_source.relative_to(tmp_path)).replace("\\", "/")
    fixture["source_sha256"] = hashlib.sha256(canonical_source.read_bytes()).hexdigest()
    document["fixtures"] = [fixture, document["fixtures"][1]]
    registry.write_text(json.dumps(document), encoding="utf-8")
    promoted = ["p0", "p1"]
    for name in promoted:
        draft = tmp_path / "work/drafts" / image_id / "instances" / name
        draft.mkdir(parents=True)
        (draft / "draft_contract.json").write_text("{}", encoding="utf-8")
        for stage in ("s02", "s03", "s04", "s05", "s06", "s07", "s08", "s08_5", "s09"):
            receipt = tmp_path / "work/instances" / name / stage / image_id
            receipt.mkdir(parents=True)
            (receipt / "stage_run.json").write_text('{"status":"complete"}', encoding="utf-8")
    recon = tmp_path / "work/s09_5" / image_id
    recon.mkdir(parents=True)
    (recon / "image_manifest.json").write_text(
        json.dumps({"promoted_instances": promoted}), encoding="utf-8"
    )
    sealed = seal_multi_instance_fixture_set(
        registry,
        tmp_path / "manifest.json",
        project_root=tmp_path,
        work_root=Path("work"),
    )
    assert sealed["fixtures"][0]["downstream_package_count_verified"] is True
    assert sealed["fixtures"][1]["downstream_package_count_verified"] is False


def test_refuses_detector_manual_mismatch_and_tampering(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    document = json.loads(registry.read_text())
    document["fixtures"][0]["manual_visible_instance_count"] = 3
    registry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MultiInstanceFixtureError, match="manual and S01 visible counts differ"):
        seal_multi_instance_fixture_set(registry, tmp_path / "manifest.json", project_root=tmp_path)

    registry = _fixture(tmp_path / "fresh")
    source = tmp_path / "fresh/source_0.png"
    source.write_bytes(source.read_bytes() + b"tamper")
    with pytest.raises(MultiInstanceFixtureError, match="source hash mismatch"):
        seal_multi_instance_fixture_set(
            registry, tmp_path / "manifest2.json", project_root=tmp_path / "fresh"
        )
