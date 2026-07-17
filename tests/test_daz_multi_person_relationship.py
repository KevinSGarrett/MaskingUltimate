from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.daz.multi_person_relationship import (
    MultiPersonRelationshipError,
    build_multi_person_relationship_record,
    load_multi_person_relationship_policy,
    publish_multi_person_relationship_record,
    validate_multi_person_relationship_policy,
    validate_multi_person_relationship_record,
)
from maskfactory.daz.scenes import (
    build_p_index_assignment,
    load_duo_recipe_policy,
    load_p_index_assignment_policy,
    select_duo_recipe,
)
from maskfactory.validation import ArtifactValidationError
from test_daz_p_index_assignment import _observation
from test_daz_relationship_pass import (
    _arrays,
    _execution,
    _observations,
    _write_fixture,
)
from test_daz_relationship_pass import (
    _evaluate as _evaluate_relationship,
)
from test_daz_relationship_pass import (
    _fixture as _relationship_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "multi_person_relationship.yaml"
DUO_POLICY = ROOT / "configs" / "daz" / "duo_recipe_selection.yaml"
P_INDEX_POLICY = ROOT / "configs" / "daz" / "p_index_assignment.yaml"


def _rehash(document: dict, id_field: str, hash_field: str, prefix: str) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = hashlib.sha256(
        json.dumps(
            content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    document[id_field] = f"{prefix}_{digest[:24]}"
    document[hash_field] = digest


def _source_report(tmp_path: Path, family: str) -> dict:
    fixture = list(_relationship_fixture(tmp_path))
    observations = None
    if family == "overlap_no_contact":
        arrays = _arrays()
        arrays["contact_pairs"].fill(0)
        fixture[4].update(_write_fixture(tmp_path, arrays))
        fixture[6] = _execution(fixture[3], fixture[4], fixture[5])
        observations = _observations(contact=False)
    elif family == "no_contact":
        arrays = _arrays()
        arrays["instance"][:, 32:] = 0
        arrays["instance"][6:42, 36:60] = 2
        arrays["depth"] = np.full(arrays["instance"].shape, np.inf, dtype=np.float32)
        arrays["depth"][arrays["instance"] == 1] = 1.0
        arrays["depth"][arrays["instance"] == 2] = 1.5
        arrays["contact_pairs"].fill(0)
        arrays["front_owner"].fill(0)
        arrays["boundary_pairs"].fill(0)
        fixture[4].update(_write_fixture(tmp_path, arrays))
        fixture[6] = _execution(fixture[3], fixture[4], fixture[5])
        observations = [
            {
                "pair": [1, 2],
                "minimum_surface_distance_mm": 12.0,
                "maximum_penetration_mm": 0.0,
                "minimum_normal_dot": 0.8,
                "contact_regions": [],
                "depth_samples": [],
            }
        ]
    report = _evaluate_relationship(tuple(fixture), observations)
    assert report["summary"]["passed"] is True
    return report


def _assignment(tmp_path: Path, selection: dict, report: dict) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    width, height = report["instance_codec"]["resolution"]
    raster = np.zeros((height, width), dtype=np.uint16)
    raster[:, : width // 2] = 1
    raster[8 : height - 8, width // 2 :] = 2
    construction = tmp_path / "construction.png"
    Image.fromarray(raster).save(construction, format="PNG")
    observation = _observation(selection)
    observation.update(
        {
            "scene_id": report["scene_id"],
            "scene_state_sha256": report["scene_state_sha256"],
            "resolution": [width, height],
            "crop": [0, 0, width, height],
        }
    )
    return build_p_index_assignment(
        selection,
        observation,
        construction,
        load_p_index_assignment_policy(P_INDEX_POLICY),
    )


def _bundle(tmp_path: Path, family: str) -> dict:
    report = _source_report(tmp_path / "relationship", family)
    duo_policy = load_duo_recipe_policy(DUO_POLICY)
    selection = select_duo_recipe(
        duo_policy,
        selection_seed=23,
        anatomy_family="MF",
        relationship_family=family,
    )
    assignment = _assignment(tmp_path, selection, report)
    return {
        "relationship_report": report,
        "assignment": assignment,
        "duo_selection": selection,
        "policy": load_multi_person_relationship_policy(POLICY),
        "duo_policy": duo_policy,
    }


def test_policy_is_closed_and_cannot_raise_authority() -> None:
    policy = load_multi_person_relationship_policy(POLICY)
    validate_multi_person_relationship_policy(policy)
    assert policy["requirements"]["exact_reciprocal_directed_records"] is True
    assert policy["authority"]["can_raise_truth_tier"] is False
    invalid = copy.deepcopy(policy)
    invalid["authority"]["can_mutate_gold"] = True
    with pytest.raises(MultiPersonRelationshipError, match="policy_identity_invalid"):
        validate_multi_person_relationship_policy(invalid)


@pytest.mark.parametrize(
    ("family", "contact", "occlusion", "directed_count"),
    [
        ("no_contact", False, "none", 0),
        ("overlap_no_contact", False, "mixed", 4),
        ("contact_support", True, "mixed", 6),
    ],
)
def test_relationship_fixtures_project_exact_reciprocal_p_index_records(
    tmp_path: Path,
    family: str,
    contact: bool,
    occlusion: str,
    directed_count: int,
) -> None:
    record = build_multi_person_relationship_record(**_bundle(tmp_path, family))
    validate_multi_person_relationship_record(record)
    assert record["relationship_family"] == family
    assert record["pair_records"][0]["pair"] == ["p0", "p1"]
    assert record["pair_records"][0]["contact"] is contact
    assert record["pair_records"][0]["occlusion_direction"] == occlusion
    assert record["summary"]["directed_relationship_count"] == directed_count
    relations = {
        (row["source_p_index"], row["target_p_index"], row["type"])
        for row in record["directed_relationships"]
    }
    if occlusion != "none":
        assert ("p0", "p1", "occludes") in relations
        assert ("p1", "p0", "occluded_by") in relations
    if contact:
        assert {("p0", "p1", "contact"), ("p1", "p0", "contact")} <= relations


def test_coherently_rehashed_nonreciprocal_source_report_is_rejected(tmp_path: Path) -> None:
    arguments = _bundle(tmp_path, "contact_support")
    report = copy.deepcopy(arguments["relationship_report"])
    report["directed_relationships"] = [
        row
        for row in report["directed_relationships"]
        if not (
            row["source_instance_id"] == 2
            and row["target_instance_id"] == 1
            and row["type"] == "contact"
        )
    ]
    _rehash(report, "report_id", "report_sha256", "drpr")
    arguments["relationship_report"] = report
    with pytest.raises(MultiPersonRelationshipError, match="source_reciprocity_invalid"):
        build_multi_person_relationship_record(**arguments)


def test_recipe_family_mismatch_and_assignment_rebinding_are_rejected(tmp_path: Path) -> None:
    overlap = _bundle(tmp_path / "family", "overlap_no_contact")
    contact_selection = select_duo_recipe(
        overlap["duo_policy"],
        selection_seed=23,
        anatomy_family="MF",
        relationship_family="contact_support",
    )
    overlap["duo_selection"] = contact_selection
    overlap["assignment"] = _assignment(
        tmp_path / "family" / "contact-assignment",
        contact_selection,
        overlap["relationship_report"],
    )
    with pytest.raises(MultiPersonRelationshipError, match="family_mismatch"):
        build_multi_person_relationship_record(**overlap)

    rebound = _bundle(tmp_path / "rebound", "contact_support")
    rebound["relationship_report"] = copy.deepcopy(rebound["relationship_report"])
    rebound["relationship_report"]["scene_state_sha256"] = "0" * 64
    _rehash(rebound["relationship_report"], "report_id", "report_sha256", "drpr")
    with pytest.raises(MultiPersonRelationshipError, match="lineage_mismatch"):
        build_multi_person_relationship_record(**rebound)


def test_record_schema_semantics_and_publication_fail_closed(tmp_path: Path) -> None:
    record = build_multi_person_relationship_record(
        **_bundle(tmp_path / "bundle", "contact_support")
    )
    unknown = copy.deepcopy(record)
    unknown["unknown"] = True
    with pytest.raises(ArtifactValidationError, match="Additional properties"):
        validate_multi_person_relationship_record(unknown)
    nonreciprocal = copy.deepcopy(record)
    nonreciprocal["directed_relationships"].pop()
    _rehash(nonreciprocal, "record_id", "record_sha256", "dmrr")
    with pytest.raises(MultiPersonRelationshipError, match="reciprocity_invalid"):
        validate_multi_person_relationship_record(nonreciprocal)
    target, published = publish_multi_person_relationship_record(record, tmp_path / "records")
    assert published is True
    assert publish_multi_person_relationship_record(record, tmp_path / "records") == (
        target,
        False,
    )
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(MultiPersonRelationshipError, match="publication_conflict"):
        publish_multi_person_relationship_record(record, tmp_path / "records")


def test_cli_builds_and_replays_immutable_relationship_record(tmp_path: Path) -> None:
    arguments = _bundle(tmp_path / "bundle", "contact_support")
    paths = {}
    for name in ("relationship_report", "assignment", "duo_selection"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(arguments[name]), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "records"
    command = [
        "daz",
        "recipes",
        "build-multi-person-relationships",
        "--relationship-report",
        str(paths["relationship_report"]),
        "--assignment",
        str(paths["assignment"]),
        "--duo-selection",
        str(paths["duo_selection"]),
        "--policy",
        str(POLICY),
        "--duo-policy",
        str(DUO_POLICY),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_multi_person_relationship_record_built"
    assert payload["data"]["summary"]["reciprocal_relationships_exact"] is True
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
