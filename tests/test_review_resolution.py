import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_grayscale
from maskfactory.review_resolution import (
    ReviewResolutionError,
    apply_s02_review_resolution,
    create_s02_review_resolution,
    s02_review_refresh_required,
)

IMAGE_ID = "img_a3f9c2e17b04"
CONFIG_HASH = "a" * 64


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    work = tmp_path / "work"
    images = tmp_path / "images"
    image_dir = images / IMAGE_ID
    image_dir.mkdir(parents=True)
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": IMAGE_ID,
                "source": {
                    "source_width": 10,
                    "source_height": 12,
                    "source_sha256": "b" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    s01 = work / "s01" / IMAGE_ID
    s01.mkdir(parents=True)
    (s01 / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "bbox_xyxy": [2, 1, 8, 11],
                        "context_bbox_xyxy": [1, 0, 9, 12],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    stage = work / "instances" / "p0" / "s02" / IMAGE_ID
    stage.mkdir(parents=True)
    mask = np.zeros((12, 10), dtype=np.uint8)
    mask[2:10, 3:7] = 255
    model_mask = write_binary_mask(stage / "person_full_visible.png", mask, source_size=(10, 12))
    write_grayscale(stage / "person_full_visible_confidence.png", mask, source_size=(10, 12))
    (stage / "silhouette_metrics.json").write_text(
        json.dumps(
            {
                "area_px": 32,
                "bbox_area_px": 60,
                "silhouette_bbox_ratio": 32 / 60,
                "qc_range": [0.6, 0.95],
                "qc_passed": False,
            }
        ),
        encoding="utf-8",
    )
    queue = work / "queues"
    queue.mkdir()
    (queue / "review_queue.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-07-12T00:00:00+00:00",
                "image_id": IMAGE_ID,
                "instance_id": "p0",
                "stage": "S02",
                "config_hash": CONFIG_HASH,
                "error": "ratio outside range",
                "terminal_outcome": "needs_review",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return work, images, model_mask


def test_confirmed_s02_resolution_is_immutable_replayed_and_auditable(tmp_path: Path) -> None:
    work, images, model_mask = _fixture(tmp_path)
    resolution = create_s02_review_resolution(
        IMAGE_ID,
        "p0",
        model_mask,
        reviewer="kevin",
        decision="confirmed_valid",
        note="wide pose is visibly complete",
        work_root=work,
        images_root=images,
        timestamp="2026-07-12T01:00:00+00:00",
    )
    assert resolution.is_file()
    assert s02_review_refresh_required(work, IMAGE_ID, "p0", work / "instances/p0/s02" / IMAGE_ID)

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    mask = read_mask(model_mask)
    write_binary_mask(fresh / "person_full_visible.png", mask, source_size=(10, 12))
    write_grayscale(fresh / "person_full_visible_confidence.png", mask, source_size=(10, 12))
    (fresh / "silhouette_metrics.json").write_text(
        json.dumps(
            {
                "area_px": 32,
                "bbox_area_px": 60,
                "silhouette_bbox_ratio": 32 / 60,
                "qc_range": [0.6, 0.95],
                "qc_passed": False,
            }
        ),
        encoding="utf-8",
    )
    applied = apply_s02_review_resolution(
        work_root=work,
        image_id=IMAGE_ID,
        instance_id="p0",
        output_dir=fresh,
        config_hash=CONFIG_HASH,
        person_bbox_xyxy=(2, 1, 8, 11),
        full_size=(10, 12),
    )
    assert applied == {
        "decision": "confirmed_valid",
        "reviewer": "kevin",
        "silhouette_bbox_ratio": 32 / 60,
        "resolution_sha256": hashlib.sha256(resolution.read_bytes()).hexdigest(),
    }
    metrics = json.loads((fresh / "silhouette_metrics.json").read_text())
    assert metrics["model_qc_passed"] is False
    assert metrics["human_review_passed"] is metrics["qc_passed"] is True
    assert not s02_review_refresh_required(work, IMAGE_ID, "p0", fresh)

    assert (
        create_s02_review_resolution(
            IMAGE_ID,
            "p0",
            model_mask,
            reviewer="kevin",
            decision="confirmed_valid",
            note="wide pose is visibly complete",
            work_root=work,
            images_root=images,
        )
        == resolution
    )
    with pytest.raises(ReviewResolutionError, match="immutable different"):
        create_s02_review_resolution(
            IMAGE_ID,
            "p0",
            model_mask,
            reviewer="other",
            decision="confirmed_valid",
            note="different authority",
            work_root=work,
            images_root=images,
        )


def test_corrected_resolution_rejects_bad_authority_geometry_and_stale_replay(
    tmp_path: Path,
) -> None:
    work, images, model_mask = _fixture(tmp_path)
    with pytest.raises(ReviewResolutionError, match="byte-identical"):
        changed = np.array(read_mask(model_mask), copy=True)
        changed[1, 2] = 255
        changed_path = write_binary_mask(tmp_path / "changed.png", changed, source_size=(10, 12))
        create_s02_review_resolution(
            IMAGE_ID,
            "p0",
            changed_path,
            reviewer="kevin",
            decision="confirmed_valid",
            note="invalid confirmation",
            work_root=work,
            images_root=images,
        )

    outside = np.array(read_mask(model_mask), copy=True)
    outside[0, 0] = 255
    outside_path = write_binary_mask(tmp_path / "outside.png", outside, source_size=(10, 12))
    with pytest.raises(ReviewResolutionError, match="outside the S01 context"):
        create_s02_review_resolution(
            IMAGE_ID,
            "p0",
            outside_path,
            reviewer="kevin",
            decision="corrected",
            note="bad geometry",
            work_root=work,
            images_root=images,
        )

    corrected = np.array(read_mask(model_mask), copy=True)
    corrected[1, 2] = 255
    corrected_path = write_binary_mask(tmp_path / "corrected.png", corrected, source_size=(10, 12))
    create_s02_review_resolution(
        IMAGE_ID,
        "p0",
        corrected_path,
        reviewer="kevin",
        decision="corrected",
        note="added one reviewed boundary pixel",
        work_root=work,
        images_root=images,
    )
    with pytest.raises(ReviewResolutionError, match="config hash is stale"):
        apply_s02_review_resolution(
            work_root=work,
            image_id=IMAGE_ID,
            instance_id="p0",
            output_dir=work / "instances/p0/s02" / IMAGE_ID,
            config_hash="c" * 64,
            person_bbox_xyxy=(2, 1, 8, 11),
            full_size=(10, 12),
        )


def test_resolve_s02_cli_seals_only_a_queued_review(tmp_path: Path) -> None:
    work, images, model_mask = _fixture(tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "review",
            "resolve-s02",
            IMAGE_ID,
            "p0",
            "--mask",
            str(model_mask),
            "--reviewer",
            "kevin",
            "--decision",
            "confirmed_valid",
            "--note",
            "visually complete",
            "--work-root",
            str(work),
            "--images-root",
            str(images),
        ],
    )
    assert result.exit_code == 0, result.output
    assert Path(json.loads(result.output)["resolution"]).is_file()
