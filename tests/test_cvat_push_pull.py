import io
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.cvat_bridge.labelmap import encode_mask_rle
from maskfactory.cvat_bridge.project import project_label_spec
from maskfactory.cvat_bridge.pull import pull_images
from maskfactory.cvat_bridge.push import push_images
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.png_strict import read_mask, write_label_map
from test_manifest_schema import valid_manifest


class FakeCvat:
    def __init__(self) -> None:
        self.next_task = 100
        self.tasks = {}
        self.uploads = {}

    def paginated(self, path: str):
        assert path.startswith("/api/users?")
        return [{"id": 7, "username": "kevin"}]

    def request(self, method: str, path: str, *, payload=None, **_kwargs):
        if method == "POST" and path == "/api/tasks":
            task_id = self.next_task
            self.next_task += 1
            self.tasks[task_id] = {"create": payload}
            return {"id": task_id}
        if method == "PUT" and path.endswith("/annotations"):
            task_id = int(path.split("/")[3])
            self.tasks[task_id]["annotations"] = payload
            return payload
        if method == "GET" and path.endswith("/annotations"):
            task_id = int(path.split("/")[3])
            return self.tasks[task_id]["annotations"]
        if method == "POST" and path.endswith("/backup/export"):
            task_id = int(path.split("/")[3])
            return {"rq_id": f"backup-{task_id}"}
        if method == "GET" and path.startswith("memory://backup/"):
            return b"PK\x03\x04fixture-backup"
        raise AssertionError((method, path, payload))

    def multipart(self, method: str, path: str, *, fields, files, **_kwargs):
        assert method == "POST" and path.endswith("/data")
        task_id = int(path.split("/")[3])
        self.uploads[task_id] = {"fields": fields, "files": files}
        return {"rq_id": f"upload-{task_id}"}

    def wait_request(self, request_id: str, **_kwargs):
        if request_id.startswith("backup-"):
            return {"status": "finished", "result_url": "memory://backup/task.zip"}
        return {"status": "finished"}


def _setup(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    image_id = "img_a3f9c2e17b04"
    packages = tmp_path / "packages"
    package = packages / image_id / "instances" / "p0"
    package.mkdir(parents=True)
    source = np.zeros((48, 64, 3), dtype=np.uint8)
    source[8:40, 10:50] = (120, 80, 220)
    Image.fromarray(source).save(package / "source.png")
    overlay = package / "overlays" / "all_parts.png"
    overlay.parent.mkdir(parents=True)
    Image.fromarray(source).save(overlay)
    heat = package / "overlays" / "disagreement_heatmap.png"
    Image.fromarray(source).save(heat)
    part = np.zeros((48, 64), dtype=np.uint16)
    material = np.zeros((48, 64), dtype=np.uint8)
    part[12:35, 15:27] = 18
    material[12:35, 15:27] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    manifest = valid_manifest()
    manifest["source"].update({"source_width": 64, "source_height": 48})
    manifest["parts"]["left_forearm"]["visibility"] = "visible"
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    labels = []
    for index, spec in enumerate(project_label_spec()):
        labels.append(
            {
                **spec,
                "id": index + 1,
                "attributes": [
                    {**attribute, "id": index * 3 + offset + 1}
                    for offset, attribute in enumerate(spec["attributes"])
                ],
            }
        )
    mapping = {
        "schema_version": "1.0.0",
        "project_id": 1,
        "labels": {
            label["name"]: {
                "cvat_id": label["id"],
                "color": label["color"],
                "attributes": {
                    attribute["name"]: attribute["id"] for attribute in label["attributes"]
                },
            }
            for label in labels
        },
    }
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    config = tmp_path / "cvat.yaml"
    config.write_text(
        "api_url: http://localhost:8080\n"
        "project:\n"
        "  assignee: kevin\n"
        "  jobs_per_task: 10\n"
        f"  label_mapping_file: '{mapping_path.as_posix()}'\n",
        encoding="utf-8",
    )
    return packages, package, config, image_id


def test_push_then_pull_unedited_is_pixel_identical_and_retains_context_backup(
    tmp_path: Path,
) -> None:
    packages, package, config, image_id = _setup(tmp_path)
    records = tmp_path / "tasks"
    before = read_mask(package / "masks" / "left_forearm.png")
    client = FakeCvat()
    task_ids = push_images(
        client,
        (image_id,),
        config_path=config,
        packages_root=packages,
        task_records=records,
    )
    assert task_ids == (100,)
    assert client.tasks[100]["create"]["segment_size"] == 1
    assert client.tasks[100]["create"]["assignee_id"] == 7
    shapes = client.tasks[100]["annotations"]["shapes"]
    assert any(shape["type"] == "mask" for shape in shapes)
    archive = next(iter(client.uploads[100]["files"].values()))[1]
    with zipfile.ZipFile(io.BytesIO(archive)) as uploaded:
        names = uploaded.namelist()
    assert any("related_images/" in name and "all_parts_overlay" in name for name in names)
    assert any("related_images/" in name and "disagreement_heatmap" in name for name in names)

    assert pull_images(client, (image_id,), config_path=config, task_records=records) == (100,)
    after = read_mask(package / "masks" / "left_forearm.png")
    assert np.array_equal(after, before)
    assert (package / "annotations" / "cvat_task_backup.zip").read_bytes().startswith(b"PK")
    qa = json.loads((package / "qa" / "cvat_pull_format.json").read_text(encoding="utf-8"))
    assert qa["trigger"] == "cvat_pull"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["parts"]["left_forearm"]["status"] == "human_corrected"


def test_two_people_create_two_instance_tasks_plus_overview_and_pull_routes_by_instance(
    tmp_path: Path,
) -> None:
    packages, p0, config, image_id = _setup(tmp_path)
    p1 = p0.parent / "p1"
    shutil.copytree(p0, p1)
    for package, other in ((p0, "p1"), (p1, "p0")):
        path = package / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["interperson"] = [
            {
                "other_instance_id": f"{image_id}_{other}",
                "relationship": "contact",
                "contact_band_file": "masks_regions/interperson_contact_boundary.png",
            }
        ]
        path.write_text(json.dumps(manifest), encoding="utf-8")
    records = tmp_path / "tasks"
    client = FakeCvat()
    task_ids = push_images(
        client,
        (image_id,),
        config_path=config,
        packages_root=packages,
        task_records=records,
    )
    assert task_ids == (100, 101, 102)
    assert [client.tasks[task]["create"]["name"] for task in task_ids] == [
        f"MaskFactory_review_{image_id}_p0",
        f"MaskFactory_review_{image_id}_p1",
        f"MaskFactory_overview_{image_id}",
    ]
    assert "SOP-6" in client.tasks[100]["create"]["description"]
    assert "reciprocal contact bands" in client.tasks[102]["create"]["description"]
    assert client.tasks[102]["annotations"]["shapes"] == []
    overview_bytes = next(iter(client.uploads[102]["files"].values()))[1]
    with Image.open(io.BytesIO(overview_bytes)) as overview:
        assert overview.size == (128, 48)

    p0_before = read_mask(p0 / "masks/left_forearm.png")
    corrected = np.zeros_like(p0_before)
    corrected[4:12, 5:15] = 255
    left_forearm_id = next(
        shape["label_id"]
        for shape in client.tasks[101]["annotations"]["shapes"]
        if shape["type"] == "mask"
    )
    target_shape = next(
        shape
        for shape in client.tasks[101]["annotations"]["shapes"]
        if shape["label_id"] == left_forearm_id
    )
    target_shape["points"] = encode_mask_rle(corrected)
    assert pull_images(client, (image_id,), config_path=config, task_records=records) == (100, 101)
    assert np.array_equal(read_mask(p0 / "masks/left_forearm.png"), p0_before)
    assert np.array_equal(read_mask(p1 / "masks/left_forearm.png"), corrected)
    p1_baseline = read_mask(p1 / "annotations/draft_baseline/label_map_part.png")
    assert np.array_equal(p1_baseline, read_mask(p0 / "label_map_part.png"))
    assert not np.array_equal(p1_baseline, read_mask(p1 / "label_map_part.png"))
    assert (p0 / "annotations/cvat_task_backup.zip").is_file()
    assert (p1 / "annotations/cvat_task_backup.zip").is_file()
    overview_record = json.loads((records / "task_102.json").read_text())
    assert overview_record["job_type"] == "image_overview"
