import subprocess
from pathlib import Path

import pytest

from maskfactory import dvc_runtime
from maskfactory.packager import _require_dvc


def test_dvc_resolver_prefers_explicit_and_refuses_missing(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "dvc.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setenv("MASKFACTORY_DVC_EXE", str(executable))
    assert dvc_runtime.resolve_dvc_executable(root=tmp_path) == executable.resolve()
    monkeypatch.setenv("MASKFACTORY_DVC_EXE", str(tmp_path / "missing.exe"))
    with pytest.raises(dvc_runtime.DvcRuntimeError, match="does not exist"):
        dvc_runtime.resolve_dvc_executable(root=tmp_path)


def test_dvc_resolver_finds_workspace_local_pinned_runtime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MASKFACTORY_DVC_EXE", raising=False)
    monkeypatch.setattr(dvc_runtime.shutil, "which", lambda _name: None)
    executable = tmp_path / ".tools/dvc-venv/Scripts/dvc.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    assert dvc_runtime.resolve_dvc_executable(root=tmp_path) == executable


def test_run_dvc_uses_repository_local_config_and_cache(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".dvc").mkdir()
    (tmp_path / ".dvc/config").write_text("[core]\n", encoding="utf-8")
    executable = tmp_path / "dvc.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(dvc_runtime, "resolve_dvc_executable", lambda **_kwargs: executable)
    captured = {}

    def fake_run(command, **kwargs):
        captured.update({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(dvc_runtime.subprocess, "run", fake_run)
    result = dvc_runtime.run_dvc(("version",), root=tmp_path, timeout=17)
    assert result.returncode == 0
    assert captured["command"] == [str(executable), "version"]
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["timeout"] == 17
    assert captured["env"]["DVC_NO_ANALYTICS"] == "true"
    assert Path(captured["env"]["DVC_SYSTEM_CONFIG_DIR"]).relative_to(tmp_path) == Path(
        ".dvc/runtime_config/system"
    )
    assert Path(captured["env"]["DVC_GLOBAL_CONFIG_DIR"]).relative_to(tmp_path) == Path(
        ".dvc/runtime_config/global"
    )
    assert Path(captured["env"]["DVC_SITE_CACHE_DIR"]).relative_to(tmp_path) == Path(
        ".dvc/site-cache"
    )
    assert (tmp_path / ".dvc/site-cache/repo").is_dir()


def test_run_dvc_normalizes_subprocess_timeout(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".dvc").mkdir()
    (tmp_path / ".dvc/config").write_text("[core]\n", encoding="utf-8")
    executable = tmp_path / "dvc.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(dvc_runtime, "resolve_dvc_executable", lambda **_kwargs: executable)
    monkeypatch.setattr(
        dvc_runtime.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        ),
    )
    with pytest.raises(dvc_runtime.DvcRuntimeError, match="failed to execute"):
        dvc_runtime.run_dvc(("push",), root=tmp_path, timeout=1)


def test_packager_dvc_preflight_surfaces_runtime_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "maskfactory.packager.run_dvc",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "no credentials"),
    )
    with pytest.raises(RuntimeError, match="no credentials"):
        _require_dvc()


def test_dvc_bootstrap_script_matches_environment_lock() -> None:
    script = Path("tools/bootstrap_dvc.ps1").read_text(encoding="utf-8")
    lock = Path("env/requirements.lock.txt").read_text(encoding="utf-8")
    for requirement in (
        "dvc==3.67.1",
        "fsspec==2026.4.0",
    ):
        assert requirement in script
        assert requirement in lock
    assert "dvc-s3" not in script
    assert "s3fs" not in script


def test_gitignore_keeps_dvc_descriptors_publishable() -> None:
    rules = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/data/*" in rules
    assert "!/data/.gitignore" in rules
    assert "!/data/packages.dvc" in rules
    assert "/datasets/*" in rules
    assert "!/datasets/.gitignore" in rules
    assert "!/datasets/*.dvc" in rules
    assert "/data/" not in rules
    assert "/datasets/" not in rules
