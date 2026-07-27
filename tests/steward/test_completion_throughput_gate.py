from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACKER_MODULE_PATH = PROJECT_ROOT / "Plan" / "Tracker" / "tracker.py"
REGISTRY_PATH = PROJECT_ROOT / "Plan" / "Tracker" / "completion_track_registry.json"
REGISTRY_SCHEMA_PATH = (
    PROJECT_ROOT / "Plan" / "Tracker" / "completion_track_registry.schema.json"
)


@pytest.fixture(scope="module")
def tracker_module():
    spec = importlib.util.spec_from_file_location(
        "maskfactory_completion_gate_tracker", TRACKER_MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _with_canonical_self_hash(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    canonical = json.dumps(
        {key: value for key, value in result.items() if key != "sha256"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    result["sha256"] = hashlib.sha256(canonical).hexdigest()
    return result


def test_v1_2_migration_preserves_prior_profile_evidence_and_adds_product_gates():
    registry = _load_json(REGISTRY_PATH)

    assert registry["schema_version"] == "1.2.0"
    assert registry["migration"] == {
        "from_schema_version": "1.1.0",
        "from_registry_sha256": (
            "330301009cdabc34a7d8c80e4f73c4c44051c74037c07e89d5538c976289df1a"
        ),
        "migration_kind": "additive_whole_product_integration_gate",
        "preserves_profile_required_item_ids": True,
        "preserves_existing_item_evidence": True,
    }
    core_profile = next(
        row
        for row in registry["profiles"]
        if row["profile_id"] == "core_autonomous_runtime"
    )
    assert core_profile["required_item_ids"][0] == "MF-P6-07.01"
    assert core_profile["required_item_ids"][42] == "MF-P6-12.06"
    assert core_profile["required_item_ids"][-12:] == [
        "MF-P6-20.01",
        "MF-P6-20.02",
        "MF-P6-20.03",
        "MF-P6-20.04",
        "MF-P6-21.01",
        "MF-P6-21.02",
        "MF-P6-21.03",
        "MF-P6-21.04",
        "MF-P6-22.01",
        "MF-P6-22.02",
        "MF-P6-22.03",
        "MF-P6-22.04",
    ]
    assert not any(
        item_id.startswith(
            (
                "MF-P6-13.",
                "MF-P6-14.",
                "MF-P6-15.",
                "MF-P6-16.",
                "MF-P6-17.",
                "MF-P6-18.",
                "MF-P6-19.",
            )
        )
        for item_id in core_profile["required_item_ids"]
    )


def test_prior_core_evidence_cannot_satisfy_new_throughput_gate(tracker_module):
    data = _load_json(tracker_module.TRACKER_JSON)
    simulated = copy.deepcopy(data)

    for item_id in tracker_module.completion_profile_dependency_closure(
        simulated, "core_autonomous_runtime"
    ):
        simulated["items"][item_id]["status"] = "complete"
    for item_id in tracker_module.SELF_HOSTED_AUTONOMY_THROUGHPUT_ITEM_IDS:
        simulated["items"][item_id]["status"] = "open"

    assert (
        tracker_module.compute_completion_profile_status(
            simulated, "core_autonomous_runtime"
        )
        != "complete"
    )
    assert (
        tracker_module.SELF_HOSTED_AUTONOMY_THROUGHPUT_GATE["incomplete_claim"]
        == "SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE"
    )


def test_throughput_gate_does_not_block_optional_accuracy_profile(tracker_module):
    data = _load_json(tracker_module.TRACKER_JSON)
    simulated = copy.deepcopy(data)

    for item_id in tracker_module.completion_profile_dependency_closure(
        simulated, "independent_real_accuracy"
    ):
        simulated["items"][item_id]["status"] = "complete"
    for item_id in tracker_module.SELF_HOSTED_AUTONOMY_THROUGHPUT_ITEM_IDS:
        simulated["items"][item_id]["status"] = "open"

    assert (
        tracker_module.compute_completion_profile_status(
            simulated, "independent_real_accuracy"
        )
        == "complete"
    )


def test_registry_and_schema_are_closed_and_valid():
    registry = _load_json(REGISTRY_PATH)
    schema = _load_json(REGISTRY_SCHEMA_PATH)
    validator = Draft202012Validator(schema)

    assert list(validator.iter_errors(registry)) == []
    drifted = copy.deepcopy(registry)
    drifted["throughput_gates"][0]["unreviewed_override"] = True
    assert list(validator.iter_errors(drifted))


def test_tracker_validation_rejects_throughput_gate_drift(
    tracker_module, monkeypatch, tmp_path
):
    registry = _load_json(REGISTRY_PATH)
    registry["throughput_gates"][0]["required_item_ids"].pop()
    drifted_path = tmp_path / "completion_track_registry.json"
    drifted_path.write_text(
        json.dumps(_with_canonical_self_hash(registry), indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tracker_module, "COMPLETION_TRACK_REGISTRY_JSON", drifted_path)

    problems = tracker_module.validate_completion_track_registry(
        _load_json(tracker_module.TRACKER_JSON)
    )

    assert any(
        "throughput gate differs from tracker.py" in problem for problem in problems
    )
