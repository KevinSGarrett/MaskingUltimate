from __future__ import annotations

import copy

import pytest

from maskfactory.ontology_v2_authority_pilot import canonical_sha256
from maskfactory.ontology_v2_resolution_workload import (
    OntologyV2ResolutionWorkloadError,
    build_resolution_workload,
    verify_resolution_workload,
)
from test_ontology_v2_authority_pilot import _manifest


def _pilot(tmp_path):
    pilot = _manifest(tmp_path)
    for index, image in enumerate(pilot["images"]):
        image["runpod_path"] = f"/workspace/assets/pilot/image-{index}.jpg"
        image["source_decoded_pixel_sha256"] = f"{index:064x}"
    pilot["self_sha256"] = canonical_sha256(pilot)
    return pilot


def test_resolution_workload_is_deterministic_complete_and_non_authoritative(tmp_path) -> None:
    pilot = _pilot(tmp_path)
    first = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)
    second = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)
    assert first == second
    result = verify_resolution_workload(first, pilot=pilot)
    assert result["status"] == "PASS_QUEUED_NO_AUTHORITY"
    assert first["work_unit_count"] == pilot["target_contract_count"]
    assert first["queued_count"] == first["work_unit_count"]
    assert {entry["authority"] for entry in first["entries"]} == {"none"}
    assert {entry["status"] for entry in first["entries"]} == {"queued"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(completion_claimed=True), "authority_boundary"),
        (lambda value: value["entries"][0].update(authority="gold"), "entry_state"),
        (lambda value: value["entries"][0].update(status="complete"), "entry_state"),
        (
            lambda value: value["entries"][0]["target_contract"].update(requested_state="visible"),
            "target_contract_hash",
        ),
        (
            lambda value: value["entries"].pop(),
            "counts",
        ),
    ],
)
def test_resolution_workload_fails_closed(tmp_path, mutate, message: str) -> None:
    pilot = _pilot(tmp_path)
    workload = copy.deepcopy(build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64))
    mutate(workload)
    workload["self_sha256"] = canonical_sha256(workload)
    with pytest.raises(OntologyV2ResolutionWorkloadError, match=message):
        verify_resolution_workload(workload, pilot=pilot)


def test_resolution_workload_rejects_different_pilot_population(tmp_path) -> None:
    pilot = _pilot(tmp_path)
    workload = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)
    changed = copy.deepcopy(pilot)
    changed["source_lineage"]["revision"] = "different-valid-pilot-revision"
    changed["self_sha256"] = canonical_sha256(changed)
    with pytest.raises(OntologyV2ResolutionWorkloadError, match="pilot_binding"):
        verify_resolution_workload(workload, pilot=changed)
