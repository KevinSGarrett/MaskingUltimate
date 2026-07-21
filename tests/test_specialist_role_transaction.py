from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.models.ontology_contract import V1_ONTOLOGY_VERSION, class_names_sha256
from maskfactory.models.registry import (
    CHAMPION_HAND_CLASS_NAMES,
    ModelRegistryError,
    load_specialist_promotion_transaction,
    production_specialist_serving_smoke,
    promote_model_role,
    rollback_model_role,
)
from maskfactory.providers import matrix_promotion
from maskfactory.validation import validate_document
from test_model_registry import (
    _benchmark_certificate,
    _governed_trained_entry,
    _registry_document,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    models_root = tmp_path / "models"
    models_root.mkdir(parents=True)
    checkpoint = models_root / "hand.pth"
    incumbent_checkpoint = models_root / "incumbent.pth"
    config = models_root / "hand.py"
    checkpoint.write_bytes(b"candidate-hand")
    incumbent_checkpoint.write_bytes(b"incumbent-hand")
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    identities = {
        "source_tree_sha256": "1" * 64,
        "checkpoint_sha256": _sha(checkpoint.read_bytes()),
        "runtime_lock_sha256": "2" * 64,
        "license_evidence_sha256": "3" * 64,
    }
    common = {
        "version_tag": "pytest-v1",
        "verified": True,
        "inference_config": "models/hand.py",
        "inference_config_sha256": _sha(config.read_bytes()),
        "class_names": list(CHAMPION_HAND_CLASS_NAMES),
        "class_names_sha256": class_names_sha256(list(CHAMPION_HAND_CLASS_NAMES)),
        "ontology_version": V1_ONTOLOGY_VERSION,
    }
    incumbent = _governed_trained_entry(
        **common,
        key="incumbent_hand",
        file="models/incumbent.pth",
        sha256=_sha(incumbent_checkpoint.read_bytes()),
        role="champion_hand",
        lifecycle_state="promoted",
        artifact_hashes={"checkpoint_sha256": _sha(incumbent_checkpoint.read_bytes())},
    )
    candidate = _governed_trained_entry(
        **common,
        key="candidate_hand",
        file="models/hand.pth",
        sha256=identities["checkpoint_sha256"],
        role="challenger_hand",
        lifecycle_state="benchmarked",
        artifact_hashes={**identities, "inference_config_sha256": _sha(config.read_bytes())},
        benchmark_certificate=_benchmark_certificate("champion_hand"),
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(_registry_document([incumbent, candidate]), indent=2), encoding="utf-8"
    )
    history = tmp_path / "champion_history.jsonl"
    matrix_bundle = tmp_path / "matrix_bundle"
    matrix_bundle.mkdir()
    packet = {
        "candidate_key": "candidate_hand",
        "target_role": "hand_finger_segmentation",
        "identity_hashes": identities,
        "rollback_evidence": {"incumbent_provider": "incumbent_hand"},
        "sha256": "5" * 64,
    }
    certificate = {
        "certificate_id": "a" * 24,
        "certificate_sha256": "6" * 64,
        "role_bindings": [
            {
                "role": "hand_finger_segmentation",
                "candidate_key": "candidate_hand",
                "incumbent_provider": "incumbent_hand",
                "prerequisite_sha256": packet["sha256"],
            }
        ],
    }
    bundle = {
        "certificate": certificate,
        "summary": {"certificate_sha256": certificate["certificate_sha256"]},
        "specialist_packets": {"hand_finger_segmentation": packet},
        "bundle_root": str(matrix_bundle),
    }
    monkeypatch.setattr(
        matrix_promotion,
        "load_and_verify_matrix_promotion_bundle",
        lambda _root: copy.deepcopy(bundle),
    )

    def smoke(_registry: Path, _models: Path, role: str, expected_key: str) -> dict:
        return {
            "result": "pass",
            "smoke": "pytest_fixed_image_inference",
            "role": role,
            "model_key": expected_key,
            "checkpoint_sha256": (
                identities["checkpoint_sha256"]
                if expected_key == "candidate_hand"
                else incumbent["sha256"]
            ),
        }

    return {
        "models_root": models_root,
        "registry": registry,
        "history": history,
        "matrix_bundle": matrix_bundle,
        "bundle": bundle,
        "smoke": smoke,
    }


def _promote(fixture: dict) -> dict:
    return promote_model_role(
        "candidate_hand",
        "champion_hand",
        matrix_bundle_root=fixture["matrix_bundle"],
        registry_path=fixture["registry"],
        models_root=fixture["models_root"],
        history_path=fixture["history"],
        smoke_runner=fixture["smoke"],
        promoted_at="2026-07-15T19:00:00Z",
    )


def test_specialist_promotion_and_one_command_rollback_are_hash_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    original = json.loads(fixture["registry"].read_text(encoding="utf-8"))
    record = _promote(fixture)
    assert not validate_document(record, "specialist_champion_transaction")
    assert record["matrix_certificate_sha256"] == "6" * 64
    assert record["specialist_packet_sha256"] == "5" * 64
    assert record["sha256"] == _sha(
        json.dumps(
            {key: value for key, value in record.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    promoted = json.loads(fixture["registry"].read_text(encoding="utf-8"))
    roles = {row["key"]: (row["role"], row["lifecycle_state"]) for row in promoted["models"]}
    assert roles == {
        "incumbent_hand": ("challenger_hand", "benchmarked"),
        "candidate_hand": ("champion_hand", "promoted"),
    }
    loaded = load_specialist_promotion_transaction(
        record["transaction_id"], history_path=fixture["history"]
    )
    rollback = rollback_model_role(
        loaded,
        registry_path=fixture["registry"],
        models_root=fixture["models_root"],
        history_path=fixture["history"],
        smoke_runner=fixture["smoke"],
        rolled_back_at="2026-07-15T19:05:00Z",
    )
    assert rollback["promotion_transaction_id"] == record["transaction_id"]
    assert not validate_document(rollback, "specialist_champion_rollback")
    assert json.loads(fixture["registry"].read_text(encoding="utf-8")) == original
    with pytest.raises(ModelRegistryError, match="already rolled back"):
        load_specialist_promotion_transaction(
            record["transaction_id"], history_path=fixture["history"]
        )
    rows = [
        json.loads(line) for line in fixture["history"].read_text(encoding="utf-8").splitlines()
    ]
    rows[-1]["sha256"] = "0" * 64
    fixture["history"].write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    with pytest.raises(ModelRegistryError, match="rollback record hash mismatch"):
        load_specialist_promotion_transaction(
            record["transaction_id"], history_path=fixture["history"]
        )


def test_default_specialist_smoke_uses_production_slot_and_fixed_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    closed: list[bool] = []

    class Slot:
        class_names = CHAMPION_HAND_CLASS_NAMES

        def __call__(self, image: np.ndarray, labels: tuple[str, ...]) -> dict[str, np.ndarray]:
            return {label: np.zeros(image.shape[:2], dtype=bool) for label in labels}

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        "maskfactory.serve.providers.load_production_mmseg_slot",
        lambda *_args, **_kwargs: Slot(),
    )
    result = production_specialist_serving_smoke(
        fixture["registry"],
        fixture["models_root"],
        "champion_hand",
        "incumbent_hand",
    )
    assert result["result"] == "pass"
    assert result["smoke"] == "production_fixed_image_specialist_inference"
    assert result["requested_label"] == "left_hand_base"
    assert len(result["output_mask_sha256"]) == 64
    assert closed == [True]


def test_missing_matrix_bundle_and_stale_signed_identities_cannot_mutate_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    before = fixture["registry"].read_bytes()
    with pytest.raises(ModelRegistryError, match="verified matrix bundle"):
        promote_model_role(
            "candidate_hand",
            "champion_hand",
            registry_path=fixture["registry"],
            models_root=fixture["models_root"],
            history_path=fixture["history"],
        )
    fixture["bundle"]["specialist_packets"]["hand_finger_segmentation"]["identity_hashes"][
        "runtime_lock_sha256"
    ] = ("9" * 64)
    monkeypatch.setattr(
        matrix_promotion,
        "load_and_verify_matrix_promotion_bundle",
        lambda _root: copy.deepcopy(fixture["bundle"]),
    )
    with pytest.raises(ModelRegistryError, match="artifact hashes"):
        _promote(fixture)
    assert fixture["registry"].read_bytes() == before
    assert not fixture["history"].exists()


def test_failed_smoke_and_intervening_registry_change_leave_current_role_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    before = fixture["registry"].read_bytes()

    def failed_smoke(*_args) -> dict:
        return {"result": "fail"}

    fixture["smoke"] = failed_smoke
    with pytest.raises(ModelRegistryError, match="passing result"):
        _promote(fixture)
    assert fixture["registry"].read_bytes() == before
    assert not fixture["history"].exists()

    fixture = _fixture(tmp_path / "second", monkeypatch)
    record = _promote(fixture)
    document = json.loads(fixture["registry"].read_text(encoding="utf-8"))
    document["models"][0]["version_tag"] = "intervening-change"
    fixture["registry"].write_text(json.dumps(document), encoding="utf-8")
    changed = fixture["registry"].read_bytes()
    with pytest.raises(ModelRegistryError, match="changed after promotion"):
        rollback_model_role(
            record,
            registry_path=fixture["registry"],
            models_root=fixture["models_root"],
            history_path=fixture["history"],
            smoke_runner=fixture["smoke"],
        )
    assert fixture["registry"].read_bytes() == changed


def test_cli_promotes_and_rolls_back_by_transaction_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    import maskfactory.models.registry as registry_module

    monkeypatch.setattr(registry_module, "production_specialist_serving_smoke", fixture["smoke"])
    common = [
        "--registry",
        str(fixture["registry"]),
        "--models-root",
        str(fixture["models_root"]),
        "--history",
        str(fixture["history"]),
    ]
    runner = CliRunner()
    promoted = runner.invoke(
        main,
        [
            "models",
            "promote-specialist",
            "candidate_hand",
            "--role",
            "champion_hand",
            "--matrix-bundle",
            str(fixture["matrix_bundle"]),
            *common,
        ],
    )
    assert promoted.exit_code == 0, promoted.output
    transaction_id = json.loads(promoted.output)["transaction_id"]
    rolled_back = runner.invoke(
        main,
        ["models", "rollback-specialist", transaction_id, *common],
    )
    assert rolled_back.exit_code == 0, rolled_back.output
    assert json.loads(rolled_back.output)["promotion_transaction_id"] == transaction_id
    duplicate = runner.invoke(
        main,
        ["models", "rollback-specialist", transaction_id, *common],
    )
    assert duplicate.exit_code != 0
    assert "already rolled back" in duplicate.output


def test_concurrent_specialist_promotions_serialize_to_one_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def attempt() -> tuple[str, str]:
        try:
            return "pass", _promote(fixture)["transaction_id"]
        except ModelRegistryError as exc:
            return "fail", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), range(2)))
    assert [status for status, _detail in results].count("pass") == 1
    assert [status for status, _detail in results].count("fail") == 1
    assert (
        sum(1 for line in fixture["history"].read_text(encoding="utf-8").splitlines() if line) == 1
    )
    document = json.loads(fixture["registry"].read_text(encoding="utf-8"))
    champions = [row for row in document["models"] if row["role"] == "champion_hand"]
    assert [row["key"] for row in champions] == ["candidate_hand"]
