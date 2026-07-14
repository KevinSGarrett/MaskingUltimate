import copy
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.cvat_bridge.labelmap import encode_mask_rle
from maskfactory.cvat_bridge.v2_common import (
    V2_ATTRIBUTE_NAMES,
    CvatV2Error,
    V2CvatLabelMap,
    mapping_from_document,
    v2_alias_help,
)
from maskfactory.cvat_bridge.v2_project import init_v2_project, v2_project_label_spec
from maskfactory.cvat_bridge.v2_pull import parse_v2_frame, pull_v2_images
from maskfactory.cvat_bridge.v2_push import push_v2_images
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology_v2 import build_ontology_v2
from maskfactory.ontology_v2_manifest import migrate_v1_manifest_document, v2_manifest_issues


class FakeCvatV2:
    def __init__(self, labels: list[dict] | None = None, *, existing_project: bool = False) -> None:
        self.next_task = 200
        self.tasks: dict[int, dict] = {}
        self.uploads: dict[int, dict] = {}
        self.project_posts: list[dict] = []
        self.existing_project = existing_project
        self.labels = labels or _live_labels()

    def paginated(self, path: str):
        if path.startswith("/api/projects?"):
            return (
                [{"id": 88, "name": "MaskFactory_body_parts_v2_pilot"}]
                if self.existing_project
                else []
            )
        if path.startswith("/api/labels?"):
            return self.labels
        if path.startswith("/api/users?"):
            return [{"id": 7, "username": "kevin"}]
        raise AssertionError(path)

    def request(self, method: str, path: str, *, payload=None, **_kwargs):
        if method == "POST" and path == "/api/projects":
            self.project_posts.append(payload)
            return {"id": 88, "name": payload["name"], "labels": self.labels}
        if method == "GET" and path == "/api/projects/88":
            return {
                "id": 88,
                "name": "MaskFactory_body_parts_v2_pilot",
                "labels": self.labels,
            }
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
            return {"rq_id": "v2-backup"}
        if method == "GET" and path == "memory://v2-backup.zip":
            return b"PK\x03\x04v2-backup"
        raise AssertionError((method, path, payload))

    def multipart(self, method: str, path: str, *, fields, files, **_kwargs):
        assert method == "POST" and path.endswith("/data")
        task_id = int(path.split("/")[3])
        self.uploads[task_id] = {"fields": fields, "files": files}
        return {"rq_id": "v2-upload"}

    def wait_request(self, request_id: str, **_kwargs):
        if request_id == "v2-backup":
            return {"status": "finished", "result_url": "memory://v2-backup.zip"}
        return {"status": "finished"}


def _live_labels() -> list[dict]:
    labels = []
    for index, specification in enumerate(v2_project_label_spec()):
        labels.append(
            {
                **specification,
                "id": index + 1000,
                "attributes": [
                    {**attribute, "id": index * 3 + offset + 5000}
                    for offset, attribute in enumerate(specification["attributes"])
                ],
            }
        )
    return labels


def _config(tmp_path: Path) -> Path:
    document = yaml.safe_load(Path("configs/cvat_v2.yaml").read_text(encoding="utf-8"))
    document["project"]["label_mapping_file"] = str(tmp_path / "mapping.json")
    document["project"]["task_records_dir"] = str(tmp_path / "tasks")
    document["credentials"]["env_file"] = str(tmp_path / "missing.env")
    path = tmp_path / "cvat_v2.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _mapping(tmp_path: Path) -> Path:
    labels = _live_labels()
    mapping = V2CvatLabelMap(labels).as_document(
        project_id=88, project_name="MaskFactory_body_parts_v2_pilot"
    )
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path


def _v1_manifest(source_sha: str, mask_sha: str) -> dict:
    part_labels = [label for label in build_ontology_v2()["labels"] if label["map"] == "part"][:56]
    parts = {
        label["name"]: {
            "mask_type": label["mask_type"],
            "visibility": "n/a" if label["name"] == "background" else "not_visible",
            "mask_file": None,
            "mask_sha256": None,
            "mask_area_px": 0,
            "mask_bbox": None,
            "components": 0,
            "status": "n/a",
        }
        for label in part_labels
    }
    parts["left_forearm"].update(
        {
            "visibility": "visible",
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": mask_sha,
            "mask_area_px": 24,
            "mask_bbox": [2, 2, 8, 6],
            "components": 1,
            "status": "human_approved_gold",
        }
    )
    return {
        "schema_version": "1.0.0",
        "image_id": "img_a3f9c2e17b04",
        "mask_ontology_version": "body_parts_v1",
        "left_right_convention": "character_perspective",
        "workflow_status": "approved_gold",
        "workflow_updated_at": "2026-07-09T15:03:22Z",
        "source": {
            "source_file": "source.png",
            "source_sha256": source_sha,
            "parent_source_sha256": source_sha,
            "source_width": 16,
            "source_height": 12,
            "source_origin": "generated",
            "origin_note": "fixture",
            "ingested_at": "2026-07-09T14:03:22Z",
            "exif_stripped": True,
        },
        "person": {
            "primary_person_bbox": [0, 0, 16, 12],
            "person_count": 1,
            "view": "front",
            "pose_tags": ["standing"],
            "estimated_person_height_px": 12,
        },
        "interperson": [],
        "parts": parts,
        "inpaint_derivatives": [],
        "tooling": {
            "annotation_tool": "cvat",
            "annotation_tool_version": "2.24.0",
            "pipeline_version": "maskfactory-test",
            "model_versions_used": {},
            "config_hashes": {"ontology.yaml": "a" * 64},
        },
        "review": {
            "reviewer": "kevin",
            "approved_at": "2026-07-11T02:11:09Z",
            "second_review": {
                "required": False,
                "reviewer": None,
                "result": "not_required",
                "at": None,
            },
            "review_time_sec": 60,
        },
        "qa": {"qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 1.0},
        "files": {"source.png": source_sha, "masks/left_forearm.png": mask_sha},
    }


def _package(tmp_path: Path) -> tuple[Path, Path, str]:
    image_id = "img_a3f9c2e17b04"
    packages = tmp_path / "packages"
    package = packages / image_id / "instances" / "p0"
    (package / "masks").mkdir(parents=True)
    source = np.zeros((12, 16, 3), dtype=np.uint8)
    source[1:11, 1:15] = (120, 80, 220)
    Image.fromarray(source).save(package / "source.png")
    mask = np.zeros((12, 16), dtype=np.uint8)
    mask[2:6, 2:8] = 255
    write_binary_mask(package / "masks" / "left_forearm.png", mask, source_size=(16, 12))
    source_sha = sha256_file(package / "source.png")
    mask_sha = sha256_file(package / "masks" / "left_forearm.png")
    migrated = migrate_v1_manifest_document(_v1_manifest(source_sha, mask_sha))
    (package / "manifest.json").write_text(
        json.dumps(migrated, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return packages, package, image_id


def _attribute_ids(mapping_path: Path, name: str) -> dict[str, int]:
    document = json.loads(mapping_path.read_text())
    return {key: int(value) for key, value in document["labels"][name]["attributes"].items()}


def _set_tag_values(
    tag: dict, mapping_path: Path, name: str, *, state: str, complete: bool, notes: str = ""
) -> None:
    ids = _attribute_ids(mapping_path, name)
    values = {
        ids["visibility"]: state,
        ids["review_complete"]: "true" if complete else "false",
        ids["notes"]: notes,
    }
    for attribute in tag["attributes"]:
        attribute["value"] = values[int(attribute["spec_id"])]


def _complete_annotations(client: FakeCvatV2, mapping_path: Path, task_id: int) -> dict:
    annotations = copy.deepcopy(client.tasks[task_id]["annotations"])
    mapping_document = json.loads(mapping_path.read_text())
    _, mapping = mapping_from_document(mapping_document)
    for tag in annotations["tags"]:
        name = mapping.ontology_name(tag["label_id"])
        state = "visible" if name == "left_forearm" else "not_visible"
        notes = ""
        if name == "glans_penis":
            state, notes = "not_applicable", "human reviewed: anatomy not applicable"
        elif name == "penis_shaft":
            state, notes = "occluded_by_clothing", "human reviewed: garment owns covered pixels"
        elif name == "vulva":
            state, notes = (
                "ambiguous_do_not_use",
                "boundary cannot be defended at source resolution",
            )
        _set_tag_values(tag, mapping_path, name, state=state, complete=True, notes=notes)
    ambiguity = np.zeros((12, 16), dtype=np.uint8)
    ambiguity[8:10, 10:12] = 255
    annotations["shapes"].append(
        {
            "type": "mask",
            "frame": 0,
            "label_id": mapping.cvat_id("vulva"),
            "points": encode_mask_rle(ambiguity),
            "attributes": [],
        }
    )
    return annotations


def test_v2_project_is_65_canonical_part_labels_with_exact_state_attributes() -> None:
    specification = v2_project_label_spec()
    assert len(specification) == 65
    assert [entry["name"] for entry in specification[:2]] == ["background", "hair"]
    assert [entry["name"] for entry in specification[-9:]] == [
        "left_areola",
        "right_areola",
        "left_nipple",
        "right_nipple",
        "vulva",
        "penis_shaft",
        "glans_penis",
        "left_scrotal_region",
        "right_scrotal_region",
    ]
    assert all(entry["type"] == "any" for entry in specification)
    assert all(
        tuple(attribute["name"] for attribute in entry["attributes"]) == V2_ATTRIBUTE_NAMES
        for entry in specification
    )
    assert specification[0]["attributes"][0]["values"] == [
        "visible",
        "partially_visible",
        "occluded",
        "occluded_by_clothing",
        "cropped_out",
        "not_visible",
        "not_applicable",
        "unreviewed_for_v2",
        "ambiguous_do_not_use",
    ]
    assert not (set(v2_alias_help()) & {entry["name"] for entry in specification})


def test_init_v2_project_never_reuses_v1_and_persists_alias_help_only(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeCvatV2()
    result = init_v2_project(client, config_path=config)
    assert result["created"] is True and result["v1_project_untouched"] is True
    assert client.project_posts[0]["name"] == "MaskFactory_body_parts_v2_pilot"
    mapping = json.loads((tmp_path / "mapping.json").read_text())
    assert mapping["ontology_version"] == "body_parts_v2"
    assert len(mapping["labels"]) == 65
    assert mapping["aliases_help_only"]["vagina"]["canonical"] == "vulva"
    assert "vagina" not in mapping["labels"]

    existing = FakeCvatV2(existing_project=True)
    assert init_v2_project(existing, config_path=config)["created"] is False
    assert existing.project_posts == []

    unsafe = yaml.safe_load(config.read_text())
    unsafe["project"]["name"] = "MaskFactory_body_parts_v1"
    config.write_text(yaml.safe_dump(unsafe), encoding="utf-8")
    with pytest.raises(CvatV2Error, match="distinct from v1"):
        init_v2_project(FakeCvatV2(), config_path=config)


def test_v2_push_has_explicit_unreviewed_tags_doc18_sop_and_crop_presets(tmp_path: Path) -> None:
    config = _config(tmp_path)
    mapping_path = _mapping(tmp_path)
    packages, _package_root, image_id = _package(tmp_path)
    client = FakeCvatV2()
    assert push_v2_images(client, (image_id,), config_path=config, packages_root=packages) == (200,)
    task = client.tasks[200]
    description = task["create"]["description"]
    assert "Document 18" in description
    assert "Character perspective" in description
    assert "vagina -> vulva" in description
    assert "Aliases are search/help only" in description
    assert task["create"]["project_id"] == 88
    annotations = task["annotations"]
    assert len(annotations["tags"]) == 65
    assert len(annotations["shapes"]) == 1
    _, mapping = mapping_from_document(json.loads(mapping_path.read_text()))
    states = {}
    for tag in annotations["tags"]:
        name = mapping.ontology_name(tag["label_id"])
        ids = _attribute_ids(mapping_path, name)
        values = {int(value["spec_id"]): value["value"] for value in tag["attributes"]}
        states[name] = values[ids["visibility"]]
    for name in (
        "left_areola",
        "right_areola",
        "left_nipple",
        "right_nipple",
        "vulva",
        "penis_shaft",
        "glans_penis",
        "left_scrotal_region",
        "right_scrotal_region",
    ):
        assert states[name] == "unreviewed_for_v2"
    archive = next(iter(client.uploads[200]["files"].values()))[1]
    with zipfile.ZipFile(io.BytesIO(archive)) as uploaded:
        names = uploaded.namelist()
    assert any(name.endswith("chest_review_crop.png") for name in names)
    assert any(name.endswith("pelvic_review_crop.png") for name in names)
    record = json.loads((tmp_path / "tasks" / "task_200.json").read_text())
    assert record["ontology_version"] == "body_parts_v2"
    assert record["v1_tasks_mutated"] is False
    assert set(record["frames"][0]["review_crop_bboxes"]) == {"chest", "pelvic"}


def test_v2_pull_blocks_incomplete_then_applies_exact_review_without_gold(tmp_path: Path) -> None:
    config = _config(tmp_path)
    mapping_path = _mapping(tmp_path)
    packages, package, image_id = _package(tmp_path)
    client = FakeCvatV2()
    push_v2_images(client, (image_id,), config_path=config, packages_root=packages)
    before = (package / "manifest.json").read_bytes()
    (package / "manifest.json").write_bytes(before + b" ")
    with pytest.raises(CvatV2Error, match="changed after push"):
        pull_v2_images(client, (image_id,), config_path=config)
    (package / "manifest.json").write_bytes(before)
    with pytest.raises(CvatV2Error, match="not explicitly reviewed"):
        pull_v2_images(client, (image_id,), config_path=config)
    assert (package / "manifest.json").read_bytes() == before
    assert not (package / "annotations" / "cvat_v2").exists()

    client.tasks[200]["annotations"] = _complete_annotations(client, mapping_path, 200)
    assert pull_v2_images(client, (image_id,), config_path=config) == (200,)
    manifest = json.loads((package / "manifest.json").read_text())
    assert v2_manifest_issues(manifest) == ()
    assert manifest["reviewed_ontology_version"] == "body_parts_v2"
    assert manifest["workflow_status"] == "corrected"
    assert manifest["workflow_status"] != "approved_gold"
    assert all(
        entry["review_authority"]["ontology_version"] == "body_parts_v2"
        and entry["review_authority"]["reviewed"] is True
        for entry in manifest["parts"].values()
    )
    forearm = manifest["parts"]["left_forearm"]
    assert forearm["visibility"] == "visible"
    assert forearm["mask_area_px"] == 24
    assert forearm["mask_file"] == "annotations/cvat_v2/part_masks/left_forearm.png"
    assert (package / forearm["mask_file"]).is_file()
    assert manifest["parts"]["penis_shaft"]["visibility"] == "occluded_by_clothing"
    assert manifest["parts"]["penis_shaft"]["mask_file"] is None
    assert manifest["parts"]["glans_penis"]["visibility"] == "not_applicable"
    vulva = manifest["parts"]["vulva"]
    assert vulva["visibility"] == "ambiguous_do_not_use"
    assert vulva["mask_file"] is None and (package / vulva["ambiguity_file"]).is_file()
    audit = package / "annotations" / "cvat_v2" / "audit"
    assert (audit / "task_200_backup.zip").read_bytes().startswith(b"PK")
    assert (audit / "task_200_manifest_before.json").read_bytes() == before


def test_v2_pull_rejects_alias_unknown_state_missing_visible_and_null_state_mask(
    tmp_path: Path,
) -> None:
    labels = _live_labels()
    alias_labels = copy.deepcopy(labels)
    next(item for item in alias_labels if item["name"] == "vulva")["name"] = "vagina"
    with pytest.raises(CvatV2Error, match="aliases may be help text only"):
        V2CvatLabelMap(alias_labels)

    mapping_path = _mapping(tmp_path)
    _, mapping = mapping_from_document(json.loads(mapping_path.read_text()))
    config = _config(tmp_path)
    packages, _package_root, image_id = _package(tmp_path)
    client = FakeCvatV2()
    push_v2_images(client, (image_id,), config_path=config, packages_root=packages)
    complete = _complete_annotations(client, mapping_path, 200)

    unknown = copy.deepcopy(complete)
    unknown["shapes"].append(
        {
            "type": "mask",
            "frame": 0,
            "label_id": 999999,
            "points": [1, 0, 0, 0, 0],
            "attributes": [],
        }
    )
    with pytest.raises(CvatV2Error, match="unknown CVAT v2 label id"):
        parse_v2_frame(unknown, mapping, frame=0, shape=(12, 16))

    missing = copy.deepcopy(complete)
    missing["shapes"] = [
        shape for shape in missing["shapes"] if shape["label_id"] != mapping.cvat_id("left_forearm")
    ]
    with pytest.raises(CvatV2Error, match="visible mask absent"):
        parse_v2_frame(missing, mapping, frame=0, shape=(12, 16))

    null_with_mask = copy.deepcopy(complete)
    forearm_tag = next(
        tag for tag in null_with_mask["tags"] if tag["label_id"] == mapping.cvat_id("left_forearm")
    )
    _set_tag_values(
        forearm_tag,
        mapping_path,
        "left_forearm",
        state="not_visible",
        complete=True,
    )
    with pytest.raises(CvatV2Error, match="null-mask state contains mask"):
        parse_v2_frame(null_with_mask, mapping, frame=0, shape=(12, 16))

    bad_state = copy.deepcopy(complete)
    vulva_tag = next(
        tag for tag in bad_state["tags"] if tag["label_id"] == mapping.cvat_id("vulva")
    )
    _set_tag_values(
        vulva_tag,
        mapping_path,
        "vulva",
        state="fully_occluded",
        complete=True,
        notes="alias must be rejected",
    )
    with pytest.raises(CvatV2Error, match="non-canonical"):
        parse_v2_frame(bad_state, mapping, frame=0, shape=(12, 16))

    overlap = copy.deepcopy(complete)
    right_tag = next(
        tag for tag in overlap["tags"] if tag["label_id"] == mapping.cvat_id("right_forearm")
    )
    _set_tag_values(
        right_tag,
        mapping_path,
        "right_forearm",
        state="visible",
        complete=True,
    )
    left_shape = next(
        shape for shape in overlap["shapes"] if shape["label_id"] == mapping.cvat_id("left_forearm")
    )
    overlap["shapes"].append(
        {**copy.deepcopy(left_shape), "label_id": mapping.cvat_id("right_forearm")}
    )
    with pytest.raises(CvatV2Error, match="atomic masks overlap"):
        parse_v2_frame(overlap, mapping, frame=0, shape=(12, 16))
