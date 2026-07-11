import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "maskfactory" / "schemas" / "model_registry.schema.json"
REGISTRY_PATH = ROOT / "models" / "model_registry.json"


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_model_registry_schema_accepts_every_live_file_and_managed_model() -> None:
    data = registry()
    assert len(data["models"]) == 17
    assert list(validator().iter_errors(data)) == []


def test_model_registry_schema_refuses_unverified_checkpoint() -> None:
    data = copy.deepcopy(registry())
    file_backed = next(model for model in data["models"] if not model.get("managed"))
    file_backed["verified"] = False
    errors = list(validator().iter_errors(data))
    assert len(errors) == 1
    assert tuple(errors[0].absolute_path) == ("models", 0)


def test_model_registry_schema_refuses_fake_path_for_managed_model() -> None:
    data = copy.deepcopy(registry())
    managed = next(model for model in data["models"] if model.get("managed"))
    managed["file"] = "models/ollama/fake.gguf"
    errors = list(validator().iter_errors(data))
    assert len(errors) == 1
    assert tuple(errors[0].absolute_path) == ("models", 7)
