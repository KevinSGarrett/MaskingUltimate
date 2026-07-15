from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.providers.birefnet_variants import (
    BIREFNET_VARIANTS,
    AlphaMatteProposal,
    BiRefNetVariantError,
    BiRefNetVariantProvider,
)
from maskfactory.providers.contracts import (
    BoxProposal,
    MaskProposal,
    ProviderIdentity,
    SilhouetteProvider,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider(
    tmp_path: Path,
    variant: str,
    *,
    mutate=None,
    returncode: int = 0,
    fallback=None,
) -> tuple[BiRefNetVariantProvider, Path, BoxProposal]:
    image_path = tmp_path / "input.png"
    Image.new("RGB", (8, 6), (80, 100, 120)).save(image_path)
    person_box = BoxProposal((1, 1, 7, 6), 0.9, "person", "p1")
    confidence = np.zeros((6, 8), dtype=np.float32)
    confidence[1:6, 1:7] = np.linspace(0.1, 1.0, 30, dtype=np.float32).reshape(5, 6)

    def execute(argv, timeout):
        output_path = Path(argv[argv.index("--output") + 1])
        np.save(output_path, confidence, allow_pickle=False)
        config = BIREFNET_VARIANTS[variant]
        resolution = int(argv[argv.index("--resolution") + 1])
        report = {
            "variant": variant,
            "repo_revision": config["revision"],
            "checkpoint": {"sha256": config["checkpoint_sha256"]},
            "image": {"sha256": _sha256(image_path)},
            "person_box_xyxy": list(person_box.bbox_xyxy),
            "resolution": resolution or "native_divisible_by_32",
            "repeats": 2,
            "deterministic": True,
            "confidence_shape": list(confidence.shape),
            "confidence_sha256": hashlib.sha256(confidence.tobytes()).hexdigest(),
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

    provider = BiRefNetVariantProvider(
        variant,
        timeout_seconds=20,
        fallback=fallback,
        executor=execute,
    )
    return provider, image_path, person_box


@pytest.mark.parametrize(
    ("variant", "resolution"),
    [
        ("birefnet_dynamic", 0),
        ("birefnet_hr", 1024),
        ("birefnet_hr_matting", 1024),
    ],
)
def test_birefnet_variants_conform_to_silhouette_contract(
    tmp_path: Path, variant: str, resolution: int
) -> None:
    provider, image_path, person_box = _provider(tmp_path, variant)
    assert isinstance(provider, SilhouetteProvider)
    proposal = provider.infer_silhouette(image_path, person_box=person_box)
    assert isinstance(proposal, MaskProposal)
    assert proposal.mask.dtype == np.bool_
    assert proposal.mask.shape == (6, 8)
    assert 0 < proposal.confidence <= 1
    assert proposal.provider == provider.identity
    assert provider.identity.provider_key == variant
    assert provider.identity.model_family == "birefnet"
    assert provider.resolution == resolution


@pytest.mark.parametrize("variant", ["birefnet_dynamic", "birefnet_hr_matting"])
def test_birefnet_matting_variants_preserve_float_alpha(tmp_path: Path, variant: str) -> None:
    provider, image_path, person_box = _provider(tmp_path, variant)
    proposal = provider.infer_matte(image_path, person_box=person_box)
    assert isinstance(proposal, AlphaMatteProposal)
    assert proposal.alpha.dtype == np.float32
    assert ((proposal.alpha > 0) & (proposal.alpha < 1)).any()


def test_birefnet_hr_rejects_unadvertised_matting_contract(tmp_path: Path) -> None:
    provider, image_path, person_box = _provider(tmp_path, "birefnet_hr")
    with pytest.raises(BiRefNetVariantError, match="no governed matting output"):
        provider.infer_matte(image_path, person_box=person_box)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report.update(repo_revision="drift"), "revision mismatch"),
        (
            lambda report: report["checkpoint"].update(sha256="0" * 64),
            "checkpoint SHA-256 mismatch",
        ),
        (lambda report: report.update(deterministic=False), "determinism proof"),
        (lambda report: report.update(resolution=2048), "resolution provenance"),
    ],
)
def test_birefnet_provider_fails_closed_on_provenance_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    provider, image_path, person_box = _provider(tmp_path, "birefnet_hr_matting", mutate=mutation)
    with pytest.raises(BiRefNetVariantError, match=message):
        provider.infer_silhouette(image_path, person_box=person_box)


def test_birefnet_failure_uses_explicit_incumbent_fallback(tmp_path: Path) -> None:
    identity = ProviderIdentity(
        "birefnet_general", "silhouette_provider", "birefnet", "incumbent", "runtime"
    )

    class Fallback:
        def __init__(self, provider_identity: ProviderIdentity) -> None:
            self.identity = provider_identity

        def infer_silhouette(self, image_path: Path, *, person_box: BoxProposal) -> MaskProposal:
            return MaskProposal(
                np.ones((6, 8), dtype=np.bool_),
                0.8,
                self.identity,
                "incumbent-fingerprint",
            )

    provider, image_path, person_box = _provider(
        tmp_path,
        "birefnet_hr",
        returncode=7,
        fallback=Fallback(identity),
    )
    proposal = provider.infer_silhouette(image_path, person_box=person_box)
    assert proposal.provider.provider_key == "birefnet_general"
    assert proposal.prompt_fingerprint == "incumbent-fingerprint"


def test_birefnet_high_memory_resolution_is_explicit() -> None:
    assert BiRefNetVariantProvider("birefnet_hr", resolution=2048).resolution == 2048
    with pytest.raises(ValueError, match="Dynamic"):
        BiRefNetVariantProvider("birefnet_dynamic", resolution=1024)
