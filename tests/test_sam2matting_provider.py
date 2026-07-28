from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.providers.contracts import (
    AlphaMatteProposal,
    MaskProposal,
    MattingRefiner,
    ProviderIdentity,
)
from maskfactory.providers.sam2matting import (
    SAM2MATTING_CHECKPOINT_REVISION,
    SAM2MATTING_CHECKPOINT_SHA256,
    SAM2MATTING_SOURCE_REVISION,
    SAM2MattingError,
    SAM2MattingProvider,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider(
    tmp_path: Path,
    *,
    mutate=None,
    returncode: int = 0,
    fallback: MattingRefiner | None = None,
) -> tuple[SAM2MattingProvider, Path, np.ndarray]:
    image_path = tmp_path / "input.png"
    Image.new("RGB", (8, 6), (80, 100, 120)).save(image_path)
    prior = np.zeros((6, 8), dtype=np.bool_)
    prior[1:5, 2:7] = True
    alpha = np.zeros((6, 8), dtype=np.float32)
    alpha[1:5, 2:7] = np.linspace(0.1, 1.0, 20, dtype=np.float32).reshape(4, 5)

    def execute(argv, timeout):
        prior_path = Path(argv[argv.index("--prior-mask") + 1])
        output_path = Path(argv[argv.index("--output") + 1])
        np.save(output_path, alpha, allow_pickle=False)
        report = {
            "provider": "sam2matting_base_plus",
            "source_revision": SAM2MATTING_SOURCE_REVISION,
            "checkpoint_revision": SAM2MATTING_CHECKPOINT_REVISION,
            "checkpoint": {"sha256": SAM2MATTING_CHECKPOINT_SHA256},
            "image": {"sha256": _sha256(image_path), "shape": [6, 8]},
            "prior_mask": {
                "sha256": _sha256(prior_path),
                "payload_sha256": hashlib.sha256(prior.astype(np.uint8).tobytes()).hexdigest(),
            },
            "semantic_authority": False,
            "threshold": 0.5,
            "repeats": 2,
            "deterministic": True,
            "alpha_shape": list(alpha.shape),
            "alpha_sha256": hashlib.sha256(alpha.tobytes()).hexdigest(),
            "output_npy_sha256": _sha256(output_path),
        }
        if mutate is not None:
            mutate(report)
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout="runtime log\n" + json.dumps(report) + "\n",
            stderr="fixture failure" if returncode else "",
        )

    provider = SAM2MattingProvider(
        runtime_python="python",
        source_root="/models/sam2matting/source",
        checkpoint_path="/models/sam2matting/checkpoint.pt",
        fallback=fallback,
        executor=execute,
    )
    return provider, image_path, prior


def test_sam2matting_refines_alpha_and_binary_without_semantic_authority(
    tmp_path: Path,
) -> None:
    provider, image_path, prior = _provider(tmp_path)
    assert isinstance(provider, MattingRefiner)
    matte = provider.refine_matte(image_path, prior_mask=prior)
    mask = provider.refine_mask(image_path, prior_mask=prior)
    assert isinstance(matte, AlphaMatteProposal)
    assert matte.alpha.dtype == np.float32
    assert matte.alpha.shape == prior.shape
    assert ((matte.alpha > 0) & (matte.alpha < 1)).any()
    assert isinstance(mask, MaskProposal)
    assert mask.mask.dtype == np.bool_
    assert mask.mask.shape == prior.shape
    assert provider.identity.role == "boundary_refiner"
    assert provider.identity.model_family == "sam2matting"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report.update(source_revision="drift"), "source provenance"),
        (
            lambda report: report["checkpoint"].update(sha256="0" * 64),
            "checkpoint SHA-256",
        ),
        (lambda report: report.update(semantic_authority=True), "semantic authority"),
        (lambda report: report.update(deterministic=False), "determinism proof"),
        (lambda report: report.update(threshold=0.25), "threshold provenance"),
    ],
)
def test_sam2matting_fails_closed_on_provenance_or_authority_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    provider, image_path, prior = _provider(tmp_path, mutate=mutation)
    with pytest.raises(SAM2MattingError, match=message):
        provider.refine_matte(image_path, prior_mask=prior)


@pytest.mark.parametrize(
    ("prior", "message"),
    [
        (np.zeros((6, 8), dtype=np.uint8), "2-D boolean"),
        (np.zeros((5, 8), dtype=np.bool_), "geometry"),
        (np.zeros((6, 8), dtype=np.bool_), "nondegenerate"),
        (np.ones((6, 8), dtype=np.bool_), "nondegenerate"),
    ],
)
def test_sam2matting_rejects_invalid_prior_geometry(
    tmp_path: Path, prior: np.ndarray, message: str
) -> None:
    provider, image_path, _ = _provider(tmp_path)
    with pytest.raises(SAM2MattingError, match=message):
        provider.refine_matte(image_path, prior_mask=prior)


def test_sam2matting_failure_uses_explicit_boundary_fallback(tmp_path: Path) -> None:
    identity = ProviderIdentity(
        "incumbent_matter", "boundary_refiner", "incumbent", "source", "runtime"
    )

    class Fallback:
        def __init__(self) -> None:
            self.identity = identity

        def refine_matte(self, image_path: Path, *, prior_mask: np.ndarray) -> AlphaMatteProposal:
            return AlphaMatteProposal(
                prior_mask.astype(np.float32),
                self.identity,
                "incumbent-fingerprint",
            )

    provider, image_path, prior = _provider(tmp_path, returncode=7, fallback=Fallback())
    proposal = provider.refine_matte(image_path, prior_mask=prior)
    assert proposal.provider.provider_key == "incumbent_matter"
    assert proposal.prompt_fingerprint == "incumbent-fingerprint"


def test_sam2matting_requires_explicit_threshold_and_timeout() -> None:
    kwargs = {
        "runtime_python": "python",
        "source_root": "/source",
        "checkpoint_path": "/checkpoint",
    }
    with pytest.raises(ValueError, match="threshold"):
        SAM2MattingProvider(**kwargs, threshold=1.0)
    with pytest.raises(ValueError, match="timeout"):
        SAM2MattingProvider(**kwargs, timeout_seconds=0)
