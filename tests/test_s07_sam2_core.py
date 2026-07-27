import numpy as np

from maskfactory.stages.s05_geometry import PromptPlan
from maskfactory.stages.s07_sam2 import SamCandidate, build_embedding, refine_part


class _Provider:
    def __init__(self) -> None:
        self.models: list[str] = []

    def embed(self, _image: np.ndarray, *, model: str, precision: str) -> str:
        assert precision == "fp16"
        self.models.append(model)
        if model == "sam2.1_hiera_large":
            raise RuntimeError("CUDA out of memory")
        return "embedding"

    def predict(self, _embedding: str, _plan: PromptPlan, *, multimask_output: bool):
        assert multimask_output is True
        logits = np.full((50, 50), -1.0, dtype=np.float32)
        logits[10:40, 10:40] = 1.0
        return [SamCandidate(logits, 0.9)]


def test_s07_reuses_fallback_embedding_and_selects_prior_aligned_mask() -> None:
    provider = _Provider()
    embedding, model = build_embedding(provider, np.zeros((50, 50, 3), dtype=np.uint8))
    plan = PromptPlan("torso", (10, 10, 40, 40), ((25, 25),), (), "high")
    prior = np.zeros((50, 50), dtype=bool)
    prior[10:40, 10:40] = True

    result = refine_part(provider, embedding, plan, prior, model=model)

    assert provider.models == ["sam2.1_hiera_large", "sam2.1_hiera_base_plus"]
    assert result.model == "sam2.1_hiera_base_plus"
    assert result.mask.dtype == bool
    assert np.array_equal(result.mask, prior)
    assert result.sam2_low_conf is False
