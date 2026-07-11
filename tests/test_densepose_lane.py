import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.lanes.prior3d import (
    SmplxV2Reservation,
    densepose_back_ratio,
    impossible_adjacency_evidence,
    surface_vote,
    uv_continuity,
)
from maskfactory.qa.semantic import SemanticInputs, run_semantic_qc
from maskfactory.stages.s08_5_densepose import (
    DensePoseError,
    DensePoseOutput,
    WslDensePoseProvider,
    run_densepose,
    write_densepose_iuv,
)


def _densepose(shape=(40, 50)) -> DensePoseOutput:
    index = np.zeros(shape, dtype=np.uint8)
    index[5:35, 5:25] = 1  # front torso
    index[5:35, 25:45] = 2  # back torso
    u = np.zeros(shape, dtype=np.uint8)
    v = np.zeros(shape, dtype=np.uint8)
    u[index > 0] = np.tile(np.arange(shape[1], dtype=np.uint8), (shape[0], 1))[index > 0]
    v[index > 0] = np.tile(np.arange(shape[0], dtype=np.uint8)[:, None], (1, shape[1]))[index > 0]
    return DensePoseOutput(index, u, v)


def test_densepose_provider_writes_strict_rgb_iuv_artifact(tmp_path: Path) -> None:
    output = _densepose()

    class Provider:
        def infer(self, image):
            return output

    path = run_densepose(Provider(), np.zeros((40, 50, 3), np.uint8), tmp_path / "work/s08_5")
    with Image.open(path) as image:
        assert image.mode == "RGB" and image.size == (50, 40)
        assert np.array_equal(np.asarray(image)[:, :, 0], output.part_index)
    bad_u = output.u.copy()
    bad_u[0, 0] = 1
    with pytest.raises(DensePoseError, match="background"):
        write_densepose_iuv(output.part_index, bad_u, output.v, tmp_path / "bad.png")


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_densepose_production_provider_validates_owned_full_canvas_iuv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = tmp_path / "source.png"
    Image.new("RGB", (50, 40), "white").save(image_path)
    checkpoint = tmp_path / "densepose.pkl"
    checkpoint.write_bytes(b"fixture")

    def windows_path(value: str) -> Path:
        assert value.startswith("/mnt/c/")
        return Path("C:/" + value.removeprefix("/mnt/c/"))

    def fake_run(command, **kwargs):
        output_path = windows_path(command[command.index("--output") + 1])
        dense = _densepose()
        iuv = np.stack((dense.part_index, dense.u, dense.v), axis=2)
        Image.fromarray(iuv, mode="RGB").save(output_path)

        class Process:
            returncode = 0
            stderr = ""
            stdout = '{"shape":[40,50],"selected_candidate_index":0}\n'

        return Process()

    monkeypatch.setattr("maskfactory.stages.s08_5_densepose.subprocess.run", fake_run)
    provider = WslDensePoseProvider(
        checkpoint=checkpoint,
        config_path="/pinned/densepose.yaml",
        image_path=image_path,
        target_bbox_xyxy=(0, 0, 50, 40),
        work_dir=tmp_path / "work",
    )
    output = provider.infer(np.zeros((40, 50, 3), dtype=np.uint8))
    assert output.part_index.shape == (40, 50)
    assert output.part_index.max() == 2
    assert not np.any((output.part_index == 0) & ((output.u != 0) | (output.v != 0)))


def test_surface_votes_feed_view_and_left_right_referees() -> None:
    dense = _densepose()
    front = dense.part_index == 1
    back = dense.part_index == 2
    assert surface_vote(front, dense).front_fraction == 1.0
    assert densepose_back_ratio(back, dense) == 1.0
    side_index = dense.part_index.copy()
    side_index[front] = 4  # configured left surface
    side = DensePoseOutput(side_index, dense.u, dense.v)
    assert surface_vote(front, side).side_vote == "left"


def test_uv_continuity_and_impossible_adjacency_evidence() -> None:
    dense = _densepose()
    connected = dense.part_index == 1
    assert not uv_continuity(connected, dense).occlusion_suspect
    split = connected.copy()
    split[:, 14:17] = False
    evidence = uv_continuity(split, dense)
    assert evidence.occlusion_suspect and evidence.disconnected_components == 2
    wrist = np.zeros((40, 50), bool)
    hand = np.zeros_like(wrist)
    wrist[10:15, 10:15] = True
    hand[30:35, 30:35] = True
    missing = impossible_adjacency_evidence(
        {"left_wrist": wrist, "left_hand_base": hand},
        {"left_wrist": ("left_hand_base",)},
    )
    assert missing == {"left_wrist": ("left_hand_base",)}


def test_densepose_activates_qc014_third_vote_and_qc024_surface_fixture() -> None:
    shape = (100, 100)
    left = np.zeros(shape, bool)
    left[20:40, 20:40] = True
    empty = np.zeros(shape, bool)
    silhouette = np.zeros(shape, bool)
    silhouette[10:50, 10:50] = True
    base = dict(
        atomic_parts={"left_forearm": left},
        silhouette=silhouette,
        protected=empty,
        skin_derived=left,
        clothing=empty,
        person_bbox_area=10_000,
        breast_skin=empty,
        material_skin=left,
        projected_allowed_region=silhouette,
        source_gray=np.zeros(shape, np.float32),
    )
    correct = SemanticInputs(
        **base,
        side_votes={"left_forearm": ("left", "right", "left")},
        densepose_front_fraction={"left_forearm": 0.9},
    )
    results = {result.qc_id: result for result in run_semantic_qc(correct)}
    assert results["QC-014"].passed and results["QC-024"].passed
    confused = SemanticInputs(
        **base,
        side_votes={"left_forearm": ("left", "right", "right")},
        densepose_front_fraction={"left_forearm": 0.1},
    )
    results = {result.qc_id: result for result in run_semantic_qc(confused)}
    assert not results["QC-014"].passed and not results["QC-024"].passed


def test_smplx_slot_is_explicit_unbuilt_v2_reservation() -> None:
    slot = SmplxV2Reservation()
    assert slot.status == "reserved_v2_not_built"
    with pytest.raises(NotImplementedError, match="reserved"):
        slot.fit(np.zeros((2, 2, 3)))
