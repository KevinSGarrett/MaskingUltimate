from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.providers.contracts import ConceptDetector, InteractiveSegmenter, MaskProposal
from maskfactory.providers.sam31_shadow import (
    SHADOW_AUTHORITY,
    Sam31ConceptDetector,
    Sam31InteractiveSegmenter,
    Sam31ShadowError,
)

ROOT = Path(__file__).resolve().parents[1]


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.fromarray(np.zeros((12, 16, 3), dtype=np.uint8), "RGB").save(path)
    return path


def test_official_discovery_emits_strict_shadow_candidates_with_exact_provenance(
    tmp_path: Path,
) -> None:
    source = _image(tmp_path)
    exemplar = tmp_path / "exemplar.png"
    exemplar.write_bytes(source.read_bytes())
    mask = np.zeros((12, 16), dtype=bool)
    mask[2:8, 3:10] = True
    detector = Sam31ConceptDetector(
        lambda path, *, concepts, exemplars: (
            {
                "kind": "box",
                "confidence": 0.8,
                "label": concepts[0],
                "instance_key": "person-0-box",
                "value": (3, 2, 10, 8),
            },
            {
                "kind": "mask",
                "confidence": 0.9,
                "label": concepts[0],
                "instance_key": "person-0-mask",
                "value": mask,
            },
        )
    )
    results = detector.discover(source, concepts=("person",), exemplars=(exemplar,))
    assert isinstance(detector, ConceptDetector)
    assert detector.identity.provider_key == "sam3_1"
    assert detector.identity.model_family == "sam3"
    assert detector.authority == SHADOW_AUTHORITY
    assert len(results) == 2
    assert isinstance(results[1], MaskProposal)
    assert results[1].provider == detector.identity
    assert len(results[1].prompt_fingerprint) == 64


def test_official_discovery_allows_absent_concept_but_rejects_unrequested_label(
    tmp_path: Path,
) -> None:
    source = _image(tmp_path)
    detector = Sam31ConceptDetector(lambda *args, **kwargs: ())
    assert detector.discover(source, concepts=("visible left hand",)) == ()

    detector = Sam31ConceptDetector(
        lambda *args, **kwargs: (
            {
                "kind": "box",
                "confidence": 0.8,
                "label": "unrequested concept",
                "instance_key": "foreign",
                "value": (1, 1, 4, 4),
            },
        )
    )
    with pytest.raises(Sam31ShadowError, match="was not requested"):
        detector.discover(source, concepts=("visible left hand",))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows[0].update(instance_key=rows[1]["instance_key"]), "instance identity"),
        (lambda rows: rows[1].update(value=np.zeros((12, 16), dtype=np.uint8)), "boolean mask"),
        (lambda rows: rows[0].update(value=(-1, 0, 5, 5)), "outside image geometry"),
        (lambda rows: rows[1].update(kind="polygon"), "kind is invalid"),
    ],
)
def test_discovery_rejects_duplicate_identity_format_geometry_and_unknown_kind(
    tmp_path: Path, mutation, message: str
) -> None:
    source = _image(tmp_path)
    mask = np.zeros((12, 16), dtype=bool)
    mask[1:4, 1:4] = True
    rows = [
        {
            "kind": "box",
            "confidence": 0.8,
            "label": "person",
            "instance_key": "a",
            "value": (1, 1, 4, 4),
        },
        {"kind": "mask", "confidence": 0.8, "label": "person", "instance_key": "b", "value": mask},
    ]
    mutation(rows)
    detector = Sam31ConceptDetector(lambda *args, **kwargs: rows)
    with pytest.raises((Sam31ShadowError, ValueError), match=message):
        detector.discover(source, concepts=("person",))


def _segmenter(output: np.ndarray) -> Sam31InteractiveSegmenter:
    return Sam31InteractiveSegmenter(
        lambda image: {"shape": image.shape},
        lambda embedding, *, prompt: ((output, 0.95),),
    )


def _prompt() -> dict:
    return {
        "positive_points": ((4, 4),),
        "negative_points": ((7, 7),),
        "box_xyxy": (2, 2, 8, 8),
        "mask_prompt": None,
    }


def test_refinement_enforces_polarity_geometry_containment_and_shadow_identity() -> None:
    image = np.zeros((12, 16, 3), dtype=np.uint8)
    mask = np.zeros((12, 16), dtype=bool)
    mask[3:6, 3:6] = True
    segmenter = _segmenter(mask)
    embedding = segmenter.embed(image)
    proposals = segmenter.refine(embedding, prompt=_prompt())
    assert isinstance(segmenter, InteractiveSegmenter)
    assert segmenter.authority == SHADOW_AUTHORITY
    assert proposals[0].mask.dtype == np.bool_
    assert proposals[0].mask.shape == image.shape[:2]
    assert proposals[0].provider == segmenter.identity
    assert len(proposals[0].prompt_fingerprint) == 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda mask, prompt: mask.__setitem__((4, 4), False), "polarity"),
        (lambda mask, prompt: mask.__setitem__((7, 7), True), "polarity"),
        (lambda mask, prompt: mask.__setitem__((1, 1), True), "containment"),
        (lambda mask, prompt: prompt.update(positive_points=((99, 4),)), "outside image"),
        (lambda mask, prompt: prompt.update(box_xyxy=(-1, 0, 8, 8)), "outside image"),
    ],
)
def test_refinement_rejects_polarity_and_geometry_failures(mutation, message: str) -> None:
    image = np.zeros((12, 16, 3), dtype=np.uint8)
    mask = np.zeros((12, 16), dtype=bool)
    mask[3:6, 3:6] = True
    prompt = _prompt()
    mutation(mask, prompt)
    segmenter = _segmenter(mask)
    with pytest.raises(Sam31ShadowError, match=message):
        segmenter.refine(segmenter.embed(image), prompt=prompt)


def test_foreign_embedding_empty_prompt_and_runtime_lock_drift_fail(tmp_path: Path) -> None:
    image = np.zeros((12, 16, 3), dtype=np.uint8)
    mask = np.zeros((12, 16), dtype=bool)
    mask[3:6, 3:6] = True
    first = _segmenter(mask)
    second = _segmenter(mask)
    foreign = copy.copy(first.embed(image))
    object.__setattr__(foreign, "runtime_lock_sha256", "0" * 64)
    with pytest.raises(Sam31ShadowError, match="foreign"):
        second.refine(foreign, prompt=_prompt())

    empty = _prompt()
    empty.update(positive_points=(), box_xyxy=None, mask_prompt=None)
    with pytest.raises(Sam31ShadowError, match="positive prompt"):
        first.refine(first.embed(image), prompt=empty)

    lock = json.loads((ROOT / "env/sam31_runtime.lock.json").read_text(encoding="utf-8"))
    lock["runtime"]["requirements_lock_sha256"] = "0" * 64
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(Sam31ShadowError, match="requirements identity is stale"):
        Sam31ConceptDetector(lambda *args, **kwargs: (), lock_path=lock_path)
