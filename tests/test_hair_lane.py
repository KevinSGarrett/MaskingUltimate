from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.io.png_strict import read_mask
from maskfactory.lanes.hair import (
    WslVitMatteProvider,
    apply_hair_shoulder_zorder,
    build_face_protected,
    build_matting_artifacts,
    create_head_crop,
    fuse_hair_face,
    refine_hair_with_sam2,
    render_hairline_panel,
)
from maskfactory.stages.s07_sam2 import SamCandidate


def test_head_crop_uses_1_8_and_falls_back_when_hair_exceeds_it(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (300, 240), "white").save(source)
    hair = np.zeros((240, 300), dtype=bool)
    hair[50:110, 110:180] = True
    cropped = create_head_crop(
        source,
        head_bbox_xyxy=(110, 50, 180, 120),
        hair_prior=hair,
        output_dir=tmp_path / "crop",
    )
    assert not cropped.full_frame_fallback
    assert cropped.bbox_xyxy[2] - cropped.bbox_xyxy[0] == 126
    assert Image.open(cropped.path).size == (1024, 1024)
    hair[10:20, 10:20] = True
    fallback = create_head_crop(
        source,
        head_bbox_xyxy=(110, 50, 180, 120),
        hair_prior=hair,
        output_dir=tmp_path / "fallback",
    )
    assert fallback.full_frame_fallback
    assert fallback.bbox_xyxy == (0, 0, 300, 240)
    assert Image.open(fallback.path).format == "PNG"
    assert Image.open(fallback.path).size == (300, 240)


def test_hair_face_fusion_uses_50pct_rule_and_sam2_face_background_negatives() -> None:
    shape = (100, 100)
    sapiens_hair = np.zeros(shape, dtype=np.float32)
    bisenet_hair = np.zeros(shape, dtype=np.float32)
    sapiens_hair[10:50, 20:80] = 0.49
    bisenet_hair[10:50, 20:50] = 0.50
    face = np.zeros(shape, dtype=bool)
    face[45:80, 30:70] = True
    scalp = np.zeros(shape, dtype=bool)
    scalp[20:55, 30:70] = True
    draft = fuse_hair_face(
        sapiens_hair_probability=sapiens_hair,
        sapiens_face=face,
        bisenet_hair_probability=bisenet_hair,
        bisenet_face=face,
        scalp_skin_seed=scalp,
    )
    assert draft.hair_binary[20, 30]
    assert not draft.hair_binary[20, 60]
    assert not (draft.face & draft.hair_binary).any()
    assert not (draft.scalp_skin & (draft.face | draft.hair_binary)).any()

    class Provider:
        def __init__(self):
            self.plan = None

        def predict(self, embedding, plan, *, multimask_output):
            self.plan = plan
            return [SamCandidate(np.where(draft.hair_binary, 1.0, -1.0), 0.9)]

    background = ~(draft.hair_binary | draft.face | draft.scalp_skin)
    provider = Provider()
    refined = refine_hair_with_sam2(
        provider, "embedding", draft, background=background, model="sam2"
    )
    assert refined.mask.any()
    assert len(provider.plan.negative_points) >= 2


def test_matting_trigger_trimap_alpha_and_optional_lace_path(tmp_path: Path) -> None:
    shape = (100, 100)
    image = np.zeros((*shape, 3), dtype=np.uint8)
    hair = np.zeros(shape, dtype=bool)
    hair[20:80, 20:80] = True

    def alpha_provider(source, trimap):
        return np.where(trimap == 255, 255, np.where(trimap == 128, 128, 0)).astype(np.uint8)

    artifacts = build_matting_artifacts(
        image,
        hair,
        person_bbox_area=10_000,
        output_dir=tmp_path / "matting",
        alpha_provider=alpha_provider,
    )
    assert artifacts.triggered
    assert set(np.unique(read_mask(artifacts.trimap_path))) == {0, 128, 255}
    assert read_mask(artifacts.alpha_path).dtype == np.uint8
    lace = build_matting_artifacts(
        image,
        hair,
        person_bbox_area=10_000,
        output_dir=tmp_path / "matting",
        alpha_provider=alpha_provider,
        prefix="lace_or_sheer",
    )
    assert lace.triggered and lace.binary_path.name == "lace_or_sheer_binary.png"
    tiny = np.zeros(shape, dtype=bool)
    tiny[0:2, 0:2] = True
    assert not build_matting_artifacts(
        image,
        tiny,
        person_bbox_area=10_000,
        output_dir=tmp_path,
        alpha_provider=alpha_provider,
    ).triggered


def test_vitmatte_provider_enforces_known_trimap_and_native_geometry(
    tmp_path: Path, monkeypatch
) -> None:
    checkpoint = tmp_path / "vitmatte.pth"
    checkpoint.write_bytes(b"fixture")

    def windows_path(value: str) -> Path:
        assert value.startswith("/mnt/c/")
        return Path("C:/" + value.removeprefix("/mnt/c/"))

    def fake_run(command, **kwargs):
        trimap_path = windows_path(command[command.index("--trimap") + 1])
        output_path = windows_path(command[command.index("--output") + 1])
        trimap = np.asarray(Image.open(trimap_path))
        alpha = np.where(trimap == 255, 255, np.where(trimap == 128, 160, 0)).astype(np.uint8)
        Image.fromarray(alpha, mode="L").save(output_path)

        class Process:
            returncode = 0
            stderr = ""
            stdout = '{"shape":[32,24],"mode":"L"}\n'

        return Process()

    monkeypatch.setattr("maskfactory.lanes.hair.subprocess.run", fake_run)
    provider = WslVitMatteProvider(checkpoint, tmp_path / "work")
    image = np.zeros((32, 24, 3), dtype=np.uint8)
    trimap = np.zeros((32, 24), dtype=np.uint8)
    trimap[4:28, 4:20] = 128
    trimap[10:22, 8:16] = 255
    alpha = provider(image, trimap)
    assert alpha.shape == trimap.shape
    assert set(np.unique(alpha)) == {0, 160, 255}
    assert not alpha[trimap == 0].any()
    assert np.all(alpha[trimap == 255] == 255)


def test_face_protection_hair_shoulder_ownership_and_hairline_panel(tmp_path: Path) -> None:
    shape = (100, 100)
    details = {}
    for index, name in enumerate(
        ("left_eye", "right_eye", "mouth", "nose", "left_brow", "right_brow", "jawline")
    ):
        mask = np.zeros(shape, dtype=bool)
        mask[30 + index : 32 + index, 40:45] = True
        details[name] = mask
    protected = build_face_protected(details, shape=shape)
    assert protected[36, 38]  # two-pixel jawline dilation beyond the detail mask
    hair = np.zeros(shape, dtype=bool)
    hair[10:60, 20:80] = True
    left = np.zeros(shape, dtype=bool)
    right = np.zeros(shape, dtype=bool)
    left[50:80, 20:50] = True
    right[50:80, 50:80] = True
    carved, states = apply_hair_shoulder_zorder(
        hair, {"left_shoulder": left, "right_shoulder": right}
    )
    assert not (carved["left_shoulder"] & hair).any()
    assert states == {"left_shoulder": "partially_visible", "right_shoulder": "partially_visible"}
    panel = render_hairline_panel(
        Image.new("RGB", (100, 100), "gray"), hair, protected, tmp_path / "hairline.png"
    )
    assert Image.open(panel).size == (2560, 512)
