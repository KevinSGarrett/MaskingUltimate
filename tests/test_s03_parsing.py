import json
import os
from pathlib import Path

import numpy as np
import pytest

from maskfactory.io.png_strict import read_mask
from maskfactory.stages.s03_parsing import (
    ModelParsing,
    ParsingError,
    WslParserProvider,
    remap_priors,
    run_parsing,
    suppress_co_subject_parsing,
)

SAPIENS_MAP = {
    0: {"part_priors": ["background"], "material_priors": []},
    1: {"part_priors": ["hair"], "material_priors": ["hair_material"]},
}
SCHP_MAP = {
    0: {"part_priors": ["background"], "material_priors": []},
    1: {"part_priors": ["hair"], "material_priors": ["hair_material"]},
}


def _output(labels: np.ndarray) -> ModelParsing:
    probabilities = np.stack((labels == 0, labels == 1)).astype(np.float32)
    return ModelParsing(labels, probabilities)


def test_s03_writes_both_parsers_confidences_and_disagreement(tmp_path: Path) -> None:
    labels_a = np.array([[0, 1], [1, 1]], dtype=np.uint8)
    labels_b = np.array([[0, 1], [0, 1]], dtype=np.uint8)
    calls = []

    def sapiens(image: np.ndarray, *, scale: float) -> ModelParsing:
        calls.append(("sapiens", scale))
        return _output(labels_a)

    def schp(image: np.ndarray, *, scale: float) -> ModelParsing:
        calls.append(("schp", scale))
        return _output(labels_b)

    result = run_parsing(
        np.zeros((2, 2, 3), dtype=np.uint8),
        sapiens=sapiens,
        schp=schp,
        sapiens_map=SAPIENS_MAP,
        schp_map=SCHP_MAP,
        output_dir=tmp_path,
    )

    assert calls == [("schp", 1.0), ("sapiens", 1.0)]
    assert result.disagreement_pct == 25.0
    assert not result.parsing_degraded
    assert len(result.sapiens_confidence_paths) == 2
    assert len(result.schp_confidence_paths) == 2
    assert np.array_equal(read_mask(result.sapiens_path), labels_a)
    metrics = json.loads((tmp_path / "parsing_metrics.json").read_text())
    assert metrics["sapiens_schp_disagreement_pct"] == 25.0


def test_co_subject_pixels_are_removed_from_both_parsers_before_geometry(
    tmp_path: Path,
) -> None:
    labels = np.ones((4, 4), dtype=np.uint8)
    run_parsing(
        np.zeros((4, 4, 3), dtype=np.uint8),
        sapiens=lambda image, scale=1.0: _output(labels),
        schp=lambda image, scale=1.0: _output(labels),
        sapiens_map=SAPIENS_MAP,
        schp_map=SCHP_MAP,
        output_dir=tmp_path,
    )
    protected = np.zeros((6, 6), dtype=bool)
    protected[1, 1] = True
    protected[2, 2] = True
    target = np.zeros_like(protected)
    target[2:5, 2:5] = True
    result = suppress_co_subject_parsing(
        tmp_path,
        other_person_protected_full=protected,
        target_silhouette_full=target,
        context_bbox_xyxy=(1, 1, 5, 5),
    )
    assert result == {"suppressed_px": 2, "ambiguous_px": 1, "careful_review": True}
    for stem in ("sapiens_28", "schp_atr"):
        indexed = read_mask(tmp_path / f"{stem}.png")
        assert indexed[0, 0] == indexed[1, 1] == 0
        assert read_mask(tmp_path / f"{stem}_confidence/class_00.png")[1, 1] == 255
        assert read_mask(tmp_path / f"{stem}_confidence/class_01.png")[1, 1] == 0
    ambiguity = read_mask(tmp_path / "ambiguous_do_not_use.png") > 0
    assert ambiguity.sum() == 1 and ambiguity[1, 1]
    metrics = json.loads((tmp_path / "parsing_metrics.json").read_text())
    assert metrics["parsing_degraded"] and metrics["co_subject_ambiguous_px"] == 1


def test_s03_oom_retries_half_resolution_then_uses_schp_only(tmp_path: Path) -> None:
    scales = []

    def sapiens(image: np.ndarray, *, scale: float) -> ModelParsing:
        scales.append(scale)
        raise RuntimeError("CUDA out of memory")

    result = run_parsing(
        np.zeros((2, 2, 3), dtype=np.uint8),
        sapiens=sapiens,
        schp=lambda image, scale=1.0: _output(np.zeros((2, 2), dtype=np.uint8)),
        sapiens_map=SAPIENS_MAP,
        schp_map=SCHP_MAP,
        output_dir=tmp_path,
    )

    assert scales == [1.0, 0.5]
    assert result.parsing_degraded
    assert result.sapiens_path is None
    assert result.disagreement_pct is None
    assert result.schp_path.exists()


def test_s03_half_resolution_retry_can_recover(tmp_path: Path) -> None:
    def sapiens(image: np.ndarray, *, scale: float) -> ModelParsing:
        if scale == 1.0:
            raise MemoryError
        return _output(np.zeros((2, 2), dtype=np.uint8))

    result = run_parsing(
        np.zeros((2, 2, 3), dtype=np.uint8),
        sapiens=sapiens,
        schp=lambda image, scale=1.0: _output(np.zeros((2, 2), dtype=np.uint8)),
        sapiens_map=SAPIENS_MAP,
        schp_map=SCHP_MAP,
        output_dir=tmp_path,
    )

    assert result.sapiens_scale == 0.5
    assert not result.parsing_degraded


def test_remap_rejects_unknown_and_output_validation_is_strict(tmp_path: Path) -> None:
    with pytest.raises(ParsingError, match="unmapped"):
        remap_priors(np.array([[2]], dtype=np.uint8), SAPIENS_MAP)
    with pytest.raises(ParsingError, match="shape mismatch"):
        run_parsing(
            np.zeros((2, 2, 3), dtype=np.uint8),
            sapiens=lambda image, scale=1.0: _output(np.zeros((2, 2), dtype=np.uint8)),
            schp=lambda image, scale=1.0: _output(np.zeros((1, 1), dtype=np.uint8)),
            sapiens_map=SAPIENS_MAP,
            schp_map=SCHP_MAP,
            output_dir=tmp_path,
        )


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_wsl_parser_provider_validates_probabilities_and_restores_half_scale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "sapiens.pt2"
    checkpoint.write_bytes(b"fixture")

    def windows_path(wsl_path: str) -> Path:
        assert wsl_path.startswith("/mnt/c/")
        return Path("C:/" + wsl_path.removeprefix("/mnt/c/"))

    def fake_run(command, **kwargs):
        parser = command[command.index("--parser") + 1]
        input_path = windows_path(command[command.index("--image") + 1])
        output_path = windows_path(command[command.index("--output") + 1])
        from PIL import Image

        with Image.open(input_path) as opened:
            width, height = opened.size
        classes = 28 if parser == "sapiens" else 18
        probabilities = np.zeros((classes, height, width), dtype=np.float32)
        probabilities[0] = 0.75
        probabilities[1] = 0.25
        np.savez_compressed(
            output_path,
            labels=probabilities.argmax(axis=0).astype(np.uint8),
            probabilities=probabilities,
        )

        class Process:
            returncode = 0
            stderr = ""
            stdout = (
                json.dumps(
                    {
                        "protocol_version": 1,
                        "parser": parser,
                        "class_count": classes,
                        "labels_shape": [height, width],
                        "probabilities_shape": [classes, height, width],
                        "model_revision": WslParserProvider.SAPIENS_REVISION,
                        "precision": "bf16",
                        "model_input": [1024, 768],
                        "tile_count": 1,
                        "tile_size": 1536,
                        "tile_overlap": 128,
                        "device": "NVIDIA fixture",
                    }
                )
                + "\n"
            )

        return Process()

    monkeypatch.setattr("maskfactory.stages.s03_parsing.subprocess.run", fake_run)
    provider = WslParserProvider("sapiens", checkpoint, tmp_path / "work")
    output = provider(np.zeros((8, 6, 3), dtype=np.uint8), scale=0.5)
    assert output.labels.shape == (8, 6)
    assert output.probabilities.shape == (28, 8, 6)
    assert np.allclose(output.probabilities.sum(axis=0), 1)
    assert np.all(output.labels == 0)
    assert not list((tmp_path / "work").iterdir())


@pytest.mark.parametrize("fault", ["mass", "argmax", "label_dtype"])
def test_s03_refuses_incoherent_probability_archives(tmp_path: Path, fault: str) -> None:
    labels = np.zeros((2, 2), dtype=np.uint8)
    probabilities = np.zeros((2, 2, 2), dtype=np.float32)
    probabilities[0] = 1.0
    if fault == "mass":
        probabilities[0] = 0.5
    elif fault == "argmax":
        labels[:] = 1
    elif fault == "label_dtype":
        labels = labels.astype(np.float32)

    with pytest.raises(ParsingError, match="sum to one|argmax|integer"):
        run_parsing(
            np.zeros((2, 2, 3), dtype=np.uint8),
            sapiens=lambda image, scale=1.0: ModelParsing(labels, probabilities),
            schp=lambda image, scale=1.0: _output(np.zeros((2, 2), dtype=np.uint8)),
            sapiens_map=SAPIENS_MAP,
            schp_map=SCHP_MAP,
            output_dir=tmp_path,
        )


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_wsl_schp_provider_requires_pinned_companion_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "schp.pth"
    checkpoint.write_bytes(b"fixture")

    def fake_run(command, **kwargs):
        output_arg = command[command.index("--output") + 1]
        output_path = Path("C:/" + output_arg.removeprefix("/mnt/c/"))
        probabilities = np.zeros((18, 4, 5), dtype=np.float32)
        probabilities[0] = 1
        labels = np.zeros((4, 5), dtype=np.uint8)
        np.savez_compressed(output_path, labels=labels, probabilities=probabilities)

        class Process:
            returncode = 0
            stderr = ""
            stdout = (
                json.dumps(
                    {
                        "protocol_version": 1,
                        "parser": "schp_atr",
                        "class_count": 18,
                        "labels_shape": [4, 5],
                        "probabilities_shape": [18, 4, 5],
                        "model_revision": WslParserProvider.SCHP_REVISION,
                        "precision": "fp32",
                        "model_input": [512, 512],
                        "dataset": "atr",
                        "tile_count": 1,
                        "device": "NVIDIA fixture",
                    }
                )
                + "\n"
            )

        return Process()

    monkeypatch.setattr("maskfactory.stages.s03_parsing.subprocess.run", fake_run)
    provider = WslParserProvider("schp_atr", checkpoint, tmp_path / "work")

    result = provider(np.zeros((4, 5, 3), dtype=np.uint8))

    assert result.labels.shape == (4, 5)
    assert result.probabilities.shape == (18, 4, 5)
    assert not list((tmp_path / "work").iterdir())
