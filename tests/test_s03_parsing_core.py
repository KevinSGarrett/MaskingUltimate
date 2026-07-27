from pathlib import Path

import numpy as np
import pytest

from maskfactory.stages.s03_parsing import ModelParsing, ParsingError, remap_priors, run_parsing


def _provider(labels: np.ndarray):
    probabilities = np.zeros((2, *labels.shape), dtype=np.float32)
    probabilities[0][labels == 0] = 1.0
    probabilities[1][labels == 1] = 1.0

    def run(_image: np.ndarray, *, scale: float = 1.0) -> ModelParsing:
        assert scale == 1.0
        return ModelParsing(labels=labels, probabilities=probabilities)

    return run


def test_s03_runs_two_deterministic_parsers_and_writes_bound_outputs(tmp_path: Path) -> None:
    labels = np.array([[0, 1], [1, 0]], dtype=np.uint8)
    mapping = {
        0: {"part_priors": (), "material_priors": ()},
        1: {"part_priors": ("head",), "material_priors": ("skin",)},
    }
    result = run_parsing(
        np.zeros((2, 2, 3), dtype=np.uint8),
        sapiens=_provider(labels),
        schp=_provider(labels),
        sapiens_map=mapping,
        schp_map=mapping,
        output_dir=tmp_path,
    )

    assert result.parsing_degraded is False
    # Empty background priors are intentionally not treated as compatible evidence.
    assert result.disagreement_pct == 50.0
    assert result.sapiens_path is not None and result.sapiens_path.is_file()
    assert result.schp_path.is_file()
    assert (tmp_path / "parsing_metrics.json").is_file()


def test_s03_remap_refuses_unknown_provider_classes() -> None:
    with pytest.raises(ParsingError, match="unmapped parser classes"):
        remap_priors(np.array([[2]], dtype=np.uint8), {0: {}, 1: {}})
