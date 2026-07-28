import importlib.util
import json
from pathlib import Path

import pytest


TOOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "build_canonical_polygon_calibration_admission.py"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("calibration_admission_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decisions_loader_requires_wrapper_object(tmp_path: Path) -> None:
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ValueError, match="decisions document .*'decisions' list"):
        _load_tool()._load_decisions(path)


def test_decisions_loader_requires_list_field(tmp_path: Path) -> None:
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps({"decisions": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="decisions document must contain a 'decisions' list"):
        _load_tool()._load_decisions(path)


def test_decisions_loader_returns_explicit_list(tmp_path: Path) -> None:
    path = tmp_path / "decisions.json"
    expected = [{"sample_id": "case-1"}]
    path.write_text(json.dumps({"decisions": expected}), encoding="utf-8")

    assert _load_tool()._load_decisions(path) == expected
