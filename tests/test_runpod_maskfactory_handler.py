from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="network-volume compatibility-link semantics require native Linux",
)


def load_handler_module():
    sys.modules.setdefault("runpod", SimpleNamespace(serverless=SimpleNamespace()))
    path = Path("deploy/runpod_serverless/maskfactory/handler.py")
    spec = importlib.util.spec_from_file_location("maskfactory_serverless_handler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_allowed_root_accepts_path_resolved_through_workspace_link(tmp_path: Path) -> None:
    module = load_handler_module()
    volume_root = tmp_path / "runpod-volume" / "maskfactory"
    volume_root.mkdir(parents=True)
    script = volume_root / "job.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    workspace_root = tmp_path / "workspace"
    workspace_root.symlink_to(tmp_path / "runpod-volume", target_is_directory=True)
    module.ALLOWED_ROOTS = (workspace_root / "maskfactory",)

    assert module._under_allowed_root(script.resolve(strict=True))
    assert not module._under_allowed_root(tmp_path.resolve(strict=True))
