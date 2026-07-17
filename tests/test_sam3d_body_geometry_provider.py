from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from maskfactory.providers.adapters import GeometryProviderAdapter
from maskfactory.providers.contracts import BoxProposal, GeometryProvider, ProviderIdentity
from maskfactory.providers.sam3d_body import (
    GeometryProviderWithOomFallback,
    Sam3dBodyGeometryError,
    Sam3dBodyGeometryProvider,
    sam3d_body_identity,
)


def _box() -> BoxProposal:
    return BoxProposal((10.0, 20.0, 110.0, 220.0), 0.99, "person", "p1")


def _output(box=(10.0, 20.0, 110.0, 220.0)):
    return {
        "bbox": np.asarray(box, dtype=np.float32),
        "focal_length": np.asarray(1200.0),
        "pred_vertices": np.asarray([[0.0, 0.0, 1.0], [0.5, 1.0, 1.5]]),
        "pred_keypoints_3d": np.asarray([[0.0, 0.0, 1.0], [0.5, 0.5, 1.5]]),
        "pred_keypoints_2d": np.asarray([[25.0, 40.0], [75.0, 160.0]]),
        "pred_cam_t": np.asarray([0.0, 0.0, 2.5]),
    }


def _identity(key: str, family: str | None = None) -> ProviderIdentity:
    return ProviderIdentity(
        key,
        "geometry_provider",
        family or key,
        "source-commit",
        "runtime-fingerprint",
    )


def test_exact_lock_identity_and_provider_contract() -> None:
    identity = sam3d_body_identity()
    assert identity.provider_key == "sam3d_body"
    assert identity.source_commit == "b5c765a0d89d789985e186d396315e7590887b94"
    provider = Sam3dBodyGeometryProvider(lambda *_args, **_kwargs: (_output(),))
    assert isinstance(provider, GeometryProvider)


def test_explicit_person_box_maps_native_frames_and_exact_provenance(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture-image")
    seen = {}

    def backend(path, *, bboxes):
        seen["path"] = path
        seen["bboxes"] = bboxes.copy()
        return (_output(),)

    provider = Sam3dBodyGeometryProvider(backend)
    first = provider.infer_geometry(image, person_box=_box())
    second = provider.infer_geometry(image, person_box=_box())
    assert seen["path"] == image
    assert np.array_equal(seen["bboxes"], np.asarray([_box().bbox_xyxy], np.float32))
    assert first["person_instance_key"] == "p1"
    assert first["coordinate_frames"] == {
        "input_box": "full_image_pixels_xyxy",
        "keypoints_2d": "full_image_pixels_xy_upstream_sam3d_body",
        "vertices_3d": "upstream_sam3d_body_native_camera_frame_unconverted",
        "keypoints_3d": "upstream_sam3d_body_native_camera_frame_unconverted",
        "camera_translation": "upstream_sam3d_body_native_camera_frame_unconverted",
        "implicit_axis_conversion": False,
    }
    assert first["provenance"]["selection"] == "explicit_single_requested_bbox"
    assert first["provenance"]["may_author_gold"] is False
    assert first["provenance"]["output_sha256"] == second["provenance"]["output_sha256"]


@pytest.mark.parametrize(
    ("box", "mutator", "message"),
    [
        (BoxProposal((1, 2, 9, 12), 0.9, "person"), None, "instance key"),
        (_box(), lambda value: value.update(bbox=[20, 20, 120, 220]), "does not own"),
        (_box(), lambda value: value.update(pred_vertices=[[np.nan, 0, 1]]), "non-finite"),
        (_box(), lambda value: value.update(pred_cam_t=[0, 1]), "camera translation"),
    ],
)
def test_identity_and_geometry_drift_fail_closed(
    tmp_path: Path, box: BoxProposal, mutator, message: str
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    output = _output()
    if mutator is not None:
        mutator(output)
    provider = Sam3dBodyGeometryProvider(lambda *_args, **_kwargs: (output,))
    with pytest.raises(Sam3dBodyGeometryError, match=message):
        provider.infer_geometry(image, person_box=box)


def test_multiple_upstream_people_reject_instead_of_guessing(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    provider = Sam3dBodyGeometryProvider(lambda *_args, **_kwargs: (_output(), _output()))
    with pytest.raises(Sam3dBodyGeometryError, match="exactly one result"):
        provider.infer_geometry(image, person_box=_box())


def test_only_real_oom_falls_back_to_densepose(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    challenger = GeometryProviderAdapter(
        _identity("sam3d_body"),
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("CUDA out of memory while allocating tensor")
        ),
    )
    fallback = GeometryProviderAdapter(
        _identity("densepose_r50_fpn_s1x", "densepose"),
        lambda _path, *, person_box: {
            "provider": "densepose_r50_fpn_s1x",
            "person_instance_key": person_box.instance_key,
        },
    )
    router = GeometryProviderWithOomFallback(challenger, fallback)
    result = router.infer_geometry(image, person_box=_box())
    assert result["provider"] == "densepose_r50_fpn_s1x"
    assert result["routing"] == {
        "attempted_provider": "sam3d_body",
        "used_provider": "densepose_r50_fpn_s1x",
        "fallback_reason": "out_of_memory",
        "fallback_exception_type": "RuntimeError",
        "production_route_changed": False,
    }


def test_non_oom_failure_never_silently_falls_back(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    challenger = GeometryProviderAdapter(
        _identity("sam3d_body"),
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("invalid output")),
    )
    fallback = GeometryProviderAdapter(
        _identity("densepose_r50_fpn_s1x", "densepose"),
        lambda *_args, **_kwargs: pytest.fail("non-OOM must not invoke fallback"),
    )
    router = GeometryProviderWithOomFallback(challenger, fallback)
    with pytest.raises(RuntimeError, match="invalid output"):
        router.infer_geometry(image, person_box=_box())
