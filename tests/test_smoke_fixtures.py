import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_file_backed_model_has_a_real_fixture_and_expected_output_hash() -> None:
    registry = json.loads((ROOT / "models" / "model_registry.json").read_text(encoding="utf-8"))
    expectations = json.loads(
        (ROOT / "qa" / "fixtures" / "smoke" / "model_expectations.json").read_text(encoding="utf-8")
    )["models"]
    file_backed = {entry["key"]: entry for entry in registry["models"] if not entry.get("managed")}

    assert set(expectations) == set(file_backed)
    for key, expected in expectations.items():
        registered = file_backed[key]["smoke_test"]
        assert expected == {
            "image": registered["image"],
            "output_sha256": registered["output_sha256"],
        }
        assert (ROOT / expected["image"]).is_file()
        assert len(expected["output_sha256"]) == 64
        int(expected["output_sha256"], 16)
