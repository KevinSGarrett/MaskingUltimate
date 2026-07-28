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
    AlphaMatteSequenceProposal,
    MattingRefiner,
    ProviderIdentity,
    TemporalMattingRefiner,
)
from maskfactory.providers.matanyone2 import (
    MATANYONE2_BACKBONE_SHA256S,
    MATANYONE2_CHECKPOINT_REVISION,
    MATANYONE2_CHECKPOINT_SHA256,
    MATANYONE2_CONFIG_SHA256,
    MATANYONE2_SOURCE_REVISION,
    STATIC_ROUTE,
    TEMPORAL_ROUTE,
    MatAnyone2CapabilityError,
    MatAnyone2Provider,
    MatAnyone2RuntimeError,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider(
    tmp_path: Path,
    *,
    mutate=None,
    returncode: int = 0,
    static_fallback: MattingRefiner | None = None,
    temporal_fallback: TemporalMattingRefiner | None = None,
) -> tuple[MatAnyone2Provider, tuple[Path, Path], np.ndarray, list[tuple[tuple[str, ...], int]]]:
    frame0 = tmp_path / "frame0.png"
    frame1 = tmp_path / "frame1.png"
    Image.new("RGB", (8, 6), (80, 100, 120)).save(frame0)
    Image.new("RGB", (8, 6), (82, 101, 121)).save(frame1)
    mask = np.zeros((6, 8), dtype=np.bool_)
    mask[1:5, 2:7] = True
    calls: list[tuple[tuple[str, ...], int]] = []

    def execute(argv, timeout):
        argv = tuple(str(value) for value in argv)
        calls.append((argv, timeout))
        route = argv[argv.index("--route") + 1]
        initial_mask_path = Path(argv[argv.index("--initial-mask") + 1])
        output_path = Path(argv[argv.index("--output") + 1])
        frame_start = argv.index("--frames") + 1
        frame_end = argv.index("--initial-mask")
        frame_paths = tuple(Path(value) for value in argv[frame_start:frame_end])
        alpha = np.zeros((len(frame_paths), 6, 8), dtype=np.float32)
        for index in range(len(frame_paths)):
            alpha[index, 1:5, 2:7] = np.linspace(
                0.1 + index * 0.01, 1.0, 20, dtype=np.float32
            ).reshape(4, 5)
        np.savez_compressed(output_path, alphas=alpha)
        report = {
            "provider": "matanyone2",
            "source_revision": MATANYONE2_SOURCE_REVISION,
            "checkpoint_revision": MATANYONE2_CHECKPOINT_REVISION,
            "checkpoint_sha256": MATANYONE2_CHECKPOINT_SHA256,
            "config_sha256": MATANYONE2_CONFIG_SHA256,
            "backbone_sha256s": dict(MATANYONE2_BACKBONE_SHA256S),
            "route": route,
            "frame_count": len(frame_paths),
            "frame_sha256s": [_sha256(path) for path in frame_paths],
            "initial_mask_sha256": _sha256(initial_mask_path),
            "semantic_authority": False,
            "repeats": 2,
            "deterministic": True,
            "alpha_shape": list(alpha.shape),
            "alpha_sha256": hashlib.sha256(alpha.tobytes()).hexdigest(),
            "output_npz_sha256": _sha256(output_path),
        }
        if mutate is not None:
            mutate(report)
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout="runtime log\n" + json.dumps(report) + "\n",
            stderr="fixture process failure" if returncode else "",
        )

    provider = MatAnyone2Provider(
        runtime_python="python",
        source_root="/models/matanyone2/source",
        model_dir="/models/matanyone2/checkpoint",
        torch_home="/models/matanyone2/torch_home",
        static_fallback=static_fallback,
        temporal_fallback=temporal_fallback,
        executor=execute,
    )
    return provider, (frame0, frame1), mask, calls


def test_matanyone2_static_and_temporal_routes_are_exact_and_nonsemantic(tmp_path: Path) -> None:
    provider, frames, mask, calls = _provider(tmp_path)
    assert isinstance(provider, MattingRefiner)
    assert isinstance(provider, TemporalMattingRefiner)

    static = provider.refine_matte(frames[0], prior_mask=mask)
    temporal = provider.refine_sequence(frames, initial_mask=mask)

    assert isinstance(static, AlphaMatteProposal)
    assert static.alpha.shape == mask.shape
    assert ((static.alpha > 0) & (static.alpha < 1)).any()
    assert isinstance(temporal, AlphaMatteSequenceProposal)
    assert temporal.alphas.shape == (2, *mask.shape)
    assert temporal.route == TEMPORAL_ROUTE
    assert provider.identity.role == "temporal_matting_refiner"
    assert provider.identity.model_family == "matanyone2"
    assert [call[0][call[0].index("--route") + 1] for call in calls] == [
        STATIC_ROUTE,
        TEMPORAL_ROUTE,
    ]


@pytest.mark.parametrize(
    ("route", "frame_indexes", "message"),
    [
        (STATIC_ROUTE, (0, 1), "requires exactly one frame"),
        (TEMPORAL_ROUTE, (0,), "requires at least two frames"),
        ("video_guess", (0, 1), "route is unsupported"),
    ],
)
def test_matanyone2_rejects_unsupported_route_selection_before_execution(
    tmp_path: Path, route: str, frame_indexes: tuple[int, ...], message: str
) -> None:
    provider, frames, mask, calls = _provider(tmp_path)
    with pytest.raises(MatAnyone2CapabilityError, match=message):
        provider.refine_route(
            tuple(frames[index] for index in frame_indexes),
            initial_mask=mask,
            route=route,
        )
    assert calls == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report.update(source_revision="drift"), "source provenance"),
        (lambda report: report.update(checkpoint_sha256="0" * 64), "model artifact"),
        (
            lambda report: report["backbone_sha256s"].update({"resnet50-19c8e357.pth": "0" * 64}),
            "model artifact",
        ),
        (lambda report: report.update(route=TEMPORAL_ROUTE), "route capability"),
        (lambda report: report.update(semantic_authority=True), "semantic authority"),
        (lambda report: report.update(deterministic=False), "determinism proof"),
    ],
)
def test_matanyone2_fails_closed_on_provenance_capability_or_authority_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    provider, frames, mask, _calls = _provider(tmp_path, mutate=mutation)
    with pytest.raises(MatAnyone2RuntimeError, match="no explicit fallback") as caught:
        provider.refine_matte(frames[0], prior_mask=mask)
    assert caught.value.__cause__ is not None
    assert message in str(caught.value.__cause__)


@pytest.mark.parametrize(
    ("mask_factory", "message"),
    [
        (lambda: np.zeros((6, 8), dtype=np.uint8), "2-D boolean"),
        (lambda: np.zeros((5, 8), dtype=np.bool_), "geometry"),
        (lambda: np.zeros((6, 8), dtype=np.bool_), "nondegenerate"),
        (lambda: np.ones((6, 8), dtype=np.bool_), "nondegenerate"),
    ],
)
def test_matanyone2_rejects_invalid_initial_mask_without_fallback(
    tmp_path: Path, mask_factory, message: str
) -> None:
    provider, frames, _mask, calls = _provider(tmp_path)
    with pytest.raises(MatAnyone2CapabilityError, match=message):
        provider.refine_matte(frames[0], prior_mask=mask_factory())
    assert calls == []


def test_matanyone2_rejects_mixed_frame_geometry_before_execution(tmp_path: Path) -> None:
    provider, frames, mask, calls = _provider(tmp_path)
    Image.new("RGB", (9, 6), (1, 2, 3)).save(frames[1])
    with pytest.raises(MatAnyone2CapabilityError, match="geometry must be identical"):
        provider.refine_sequence(frames, initial_mask=mask)
    assert calls == []


def test_matanyone2_preserves_exact_static_and_temporal_rollback(tmp_path: Path) -> None:
    static_identity = ProviderIdentity(
        "static_incumbent", "boundary_refiner", "incumbent_static", "source", "runtime"
    )
    temporal_identity = ProviderIdentity(
        "temporal_incumbent", "temporal_matting_refiner", "incumbent_temporal", "source", "runtime"
    )

    class StaticFallback:
        def __init__(self) -> None:
            self.identity = static_identity

        def refine_matte(self, image_path: Path, *, prior_mask: np.ndarray) -> AlphaMatteProposal:
            return AlphaMatteProposal(
                np.ascontiguousarray(prior_mask, dtype=np.float32),
                self.identity,
                "static-incumbent-fingerprint",
            )

    class TemporalFallback:
        def __init__(self) -> None:
            self.identity = temporal_identity

        def refine_sequence(
            self, frame_paths: tuple[Path, ...], *, initial_mask: np.ndarray
        ) -> AlphaMatteSequenceProposal:
            alphas = np.repeat(initial_mask[None].astype(np.float32), len(frame_paths), axis=0)
            return AlphaMatteSequenceProposal(
                alphas,
                self.identity,
                "temporal-incumbent-fingerprint",
                TEMPORAL_ROUTE,
            )

    provider, frames, mask, _calls = _provider(
        tmp_path,
        returncode=7,
        static_fallback=StaticFallback(),
        temporal_fallback=TemporalFallback(),
    )
    static = provider.refine_matte(frames[0], prior_mask=mask)
    temporal = provider.refine_sequence(frames, initial_mask=mask)
    assert static.provider == static_identity
    assert static.prompt_fingerprint == "static-incumbent-fingerprint"
    assert np.array_equal(static.alpha, mask.astype(np.float32))
    assert temporal.provider == temporal_identity
    assert temporal.prompt_fingerprint == "temporal-incumbent-fingerprint"
    assert np.array_equal(temporal.alphas, np.repeat(mask[None], 2, axis=0).astype(np.float32))


def test_matanyone2_runtime_failure_requires_explicit_route_fallback(tmp_path: Path) -> None:
    provider, frames, mask, _calls = _provider(tmp_path, returncode=9)
    with pytest.raises(MatAnyone2RuntimeError, match="no explicit fallback"):
        provider.refine_sequence(frames, initial_mask=mask)


def test_matanyone2_requires_positive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        MatAnyone2Provider(
            runtime_python="python",
            source_root="/source",
            model_dir="/model",
            torch_home="/torch",
            timeout_seconds=0,
        )
