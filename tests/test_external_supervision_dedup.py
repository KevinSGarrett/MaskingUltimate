import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from PIL import Image

from maskfactory.external_supervision_dedup import (
    ExternalDedupError,
    build_external_split_dedup_evidence,
    find_hamming_pairs,
)
from maskfactory.external_supervision_evidence import seal_payload
from maskfactory.external_supervision_hash_manifest import (
    build_source_hash_manifest,
    publish_source_hash_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT
    / "src"
    / "maskfactory"
    / "schemas"
    / "external_supervision_split_dedup_evidence.schema.json"
)


def _image_bytes(seed: int) -> bytes:
    y, x = np.mgrid[:32, :32]
    pixels = np.stack(
        ((x * 7 + seed) % 256, (y * 11 + seed) % 256, ((x + y) * 5 + seed) % 256),
        axis=2,
    ).astype(np.uint8)
    from io import BytesIO

    output = BytesIO()
    Image.fromarray(pixels).save(output, format="PNG")
    return output.getvalue()


def _write_jpeg(path: Path, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    y, x = np.mgrid[:32, :32]
    pixels = np.stack(
        ((x * 7 + seed) % 256, (y * 11 + seed) % 256, ((x + y) * 5 + seed) % 256),
        axis=2,
    ).astype(np.uint8)
    Image.fromarray(pixels).save(path, format="JPEG", quality=95)


def _fixture(tmp_path: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    roots = {
        "celebamask_hq": tmp_path / "celeb",
        "lapa": tmp_path / "lapa",
        "lv_mhp_v1": tmp_path / "lv",
    }
    celeb_image = roots["celebamask_hq"] / "CelebA-HQ-img" / "0001.jpg"
    _write_jpeg(celeb_image, 1)
    lapa_train = roots["lapa"] / "train" / "images" / "a.jpg"
    lapa_val = roots["lapa"] / "val" / "images" / "b.jpg"
    lapa_test = roots["lapa"] / "test" / "images" / "c.jpg"
    lapa_train.parent.mkdir(parents=True, exist_ok=True)
    lapa_val.parent.mkdir(parents=True, exist_ok=True)
    lapa_test.parent.mkdir(parents=True, exist_ok=True)
    lapa_train.write_bytes(celeb_image.read_bytes())
    lapa_val.write_bytes(celeb_image.read_bytes())
    _write_jpeg(lapa_test, 55)
    lv_content = roots["lv_mhp_v1"] / "LV-MHP-v1"
    _write_jpeg(lv_content / "images" / "0001.jpg", 99)
    (lv_content / "train_list.txt").write_text("0001.jpg\n", encoding="utf-8")
    (lv_content / "test_list.txt").write_text("", encoding="utf-8")

    manifest_paths: dict[str, Path] = {}
    for source, root in roots.items():
        manifest = build_source_hash_manifest(source=source, source_root=root)
        path = tmp_path / "manifests" / f"{source}.json"
        publish_source_hash_manifest(manifest, path)
        manifest_paths[source] = path
    return roots, manifest_paths


def test_exact_and_perceptual_groups_are_deterministic_and_schema_valid(tmp_path: Path):
    roots, manifests = _fixture(tmp_path)
    first = build_external_split_dedup_evidence(manifest_paths=manifests, source_roots=roots)
    second = build_external_split_dedup_evidence(manifest_paths=manifests, source_roots=roots)

    assert first == second
    assert first["record_count"] == 5
    assert first["duplicate_record_count"] >= 2
    assert first["cross_source_exact_group_count"] == 1
    assert first["upstream_split_conflict_group_count"] == 1
    duplicated = [
        record
        for record in first["records"]
        if record["source_sha256"] == first["records"][0]["source_sha256"]
    ]
    assert len({record["split_group_id"] for record in duplicated}) == 1
    assert first["seal_sha256"] == seal_payload(first)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_segmented_hamming_index_matches_brute_force():
    values = (0, 1, 3, 7, 15, 0xFFFF0000FFFF0000, 0xFFFF0000FFFF0001)
    expected = tuple(
        (left, right)
        for left in range(len(values))
        for right in range(left + 1, len(values))
        if (values[left] ^ values[right]).bit_count() <= 3
    )
    assert find_hamming_pairs(values, threshold=3) == expected


def test_manifest_hash_drift_fails_closed(tmp_path: Path):
    roots, manifests = _fixture(tmp_path)
    image = roots["lapa"] / "train" / "images" / "a.jpg"
    image.write_bytes(_image_bytes(7))
    with pytest.raises(ExternalDedupError, match="source image hash drift"):
        build_external_split_dedup_evidence(manifest_paths=manifests, source_roots=roots)


def test_missing_canonical_source_fails_closed(tmp_path: Path):
    roots, manifests = _fixture(tmp_path)
    manifests.pop("lapa")
    with pytest.raises(ExternalDedupError, match="all three canonical"):
        build_external_split_dedup_evidence(manifest_paths=manifests, source_roots=roots)


def test_unlisted_lv_mhp_image_fails_closed(tmp_path: Path):
    roots, manifests = _fixture(tmp_path)
    split_list = roots["lv_mhp_v1"] / "LV-MHP-v1" / "train_list.txt"
    split_list.write_text("", encoding="utf-8")
    with pytest.raises(ExternalDedupError, match="absent from upstream split lists"):
        build_external_split_dedup_evidence(manifest_paths=manifests, source_roots=roots)
