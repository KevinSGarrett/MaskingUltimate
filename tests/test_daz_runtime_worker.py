from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import maskfactory.daz.worker as daz_worker
from maskfactory.daz import (
    DazPolicyError,
    WindowObservation,
    build_daz_command,
    deploy_script_bundle,
    load_daz_runtime_profile,
    prepare_job_files,
    read_terminal_result,
    stage_recipe,
)
from maskfactory.gpu import GpuLock, GpuLockBusyError
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIG = ROOT / "configs" / "daz" / "runtime.yaml"
SCHEMAS = ROOT / "src" / "maskfactory" / "schemas"


def _recipe(job_id: str = "job_0001", operation: str = "runtime_probe") -> dict:
    return {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "recipe_id": f"recipe_{job_id}",
        "created_at": datetime.now(UTC).isoformat(),
        "bundle_version": "1.0.0",
        "operation": operation,
        "requires_gpu": operation != "runtime_probe",
        "content_directories": [
            r"F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library",
            r"F:\DAZ\03_content\libraries\MaskFactory_User_Library",
        ],
        "payload": {},
    }


def _result(recipe: dict, artifact: Path | None = None) -> dict:
    artifacts = []
    if artifact is not None:
        data = artifact.read_bytes()
        artifacts.append(
            {
                "path": str(artifact),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    return {
        "schema_version": "1.0.0",
        "job_id": recipe["job_id"],
        "recipe_id": recipe["recipe_id"],
        "bundle_version": recipe["bundle_version"],
        "instance_name": "MaskFactoryDAZ",
        "status": "success",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "reason": "fixture_passed",
        "artifacts": artifacts,
        "runtime": {
            "daz_version": "6.0.1.39",
            "content_directories": list(recipe["content_directories"]),
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_daz_runtime_recipe_and_result_schemas_are_closed_and_compile():
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    assert profile.instance_name == "MaskFactoryDAZ"
    assert profile.process_lifetime == "process_per_job"
    assert profile.safety["persistent_worker"] is False
    assert profile.safety["click_dialogs"] is False
    for name, document in (
        ("daz_runtime", profile.document),
        ("daz_scene_recipe", _recipe()),
        ("daz_worker_result", _result(_recipe())),
    ):
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert validate_document(document, name) == ()
    invalid = _recipe()
    invalid["surprise"] = True
    assert validate_document(invalid, "daz_scene_recipe")[0].validator == "additionalProperties"


def test_script_bundle_deployment_is_versioned_replayable_and_drift_refusing(tmp_path: Path):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    versions = tmp_path / "versions"
    active = tmp_path / "active"
    app_profile = tmp_path / "profile"
    first = deploy_script_bundle(
        profile,
        repository_root=ROOT,
        bundle_versions=versions,
        active_bundle=active,
        app_profile=app_profile,
    )
    assert first["deployed"] is True
    target = versions / "1.0.0"
    assert (target / "worker_main.dsa").is_file()
    pointer = json.loads((active / "active_bundle.json").read_text(encoding="utf-8"))
    assert pointer["bundle_version"] == "1.0.0"
    assert (
        json.loads((app_profile / "profile.json").read_text(encoding="utf-8"))["instance_name"]
        == "MaskFactoryDAZ"
    )
    replay = deploy_script_bundle(
        profile,
        repository_root=ROOT,
        bundle_versions=versions,
        active_bundle=active,
        app_profile=app_profile,
    )
    assert replay["deployed"] is False
    (target / "worker_main.dsa").write_text("drift", encoding="utf-8")
    with pytest.raises(DazPolicyError, match="drift"):
        deploy_script_bundle(
            profile,
            repository_root=ROOT,
            bundle_versions=versions,
            active_bundle=active,
            app_profile=app_profile,
        )


def test_script_bundle_refuses_recorded_manifest_tamper(tmp_path: Path):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    versions = tmp_path / "versions"
    deploy_script_bundle(
        profile,
        repository_root=ROOT,
        bundle_versions=versions,
        active_bundle=tmp_path / "active",
        app_profile=tmp_path / "profile",
    )
    manifest = versions / "1.0.0" / "bundle_manifest.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["files"]["worker_main.dsa"]["bytes"] += 1
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DazPolicyError, match="drift"):
        deploy_script_bundle(
            profile,
            repository_root=ROOT,
            bundle_versions=versions,
            active_bundle=tmp_path / "active",
            app_profile=tmp_path / "profile",
        )


def test_recipe_and_result_protocol_never_accepts_partial_or_wrong_hash(tmp_path: Path):
    recipe = _recipe()
    files = prepare_job_files(tmp_path / "jobs", recipe["job_id"])
    stage_recipe(files, recipe)
    assert json.loads(files.recipe.read_text(encoding="utf-8")) == recipe
    files.partial_result.write_text('{"state":"still_running"}', encoding="utf-8")
    assert read_terminal_result(files, recipe, allowed_artifact_roots=(tmp_path,)) is None

    artifact = tmp_path / "renders" / "rgb.png"
    artifact.parent.mkdir()
    artifact.write_bytes(b"fixture-render")
    files.terminal_result.write_text(json.dumps(_result(recipe, artifact)), encoding="utf-8")
    accepted = read_terminal_result(files, recipe, allowed_artifact_roots=(tmp_path / "renders",))
    assert accepted is not None and accepted["status"] == "success"
    artifact.write_bytes(b"tampered")
    with pytest.raises(DazPolicyError, match="hash/size mismatch"):
        read_terminal_result(files, recipe, allowed_artifact_roots=(tmp_path / "renders",))


def test_result_protocol_refuses_runtime_path_drift_and_empty_render_success(tmp_path: Path):
    recipe = _recipe()
    files = prepare_job_files(tmp_path, recipe["job_id"])
    result = _result(recipe)
    result["runtime"]["content_directories"][0] = r"C:\Users\kevin\Documents\DAZ"
    files.terminal_result.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(DazPolicyError, match="content-directory mismatch"):
        read_terminal_result(files, recipe, allowed_artifact_roots=(tmp_path,))

    render_recipe = _recipe(operation="render_scene")
    render_files = prepare_job_files(tmp_path, "job_0002")
    render_recipe["job_id"] = "job_0002"
    render_recipe["recipe_id"] = "recipe_job_0002"
    render_files.terminal_result.write_text(json.dumps(_result(render_recipe)), encoding="utf-8")
    with pytest.raises(DazPolicyError, match="no artifacts"):
        read_terminal_result(render_files, render_recipe, allowed_artifact_roots=(tmp_path,))


def test_job_paths_recipe_identity_and_immutable_recipe_fail_closed(tmp_path: Path):
    with pytest.raises(DazPolicyError, match="unsafe"):
        prepare_job_files(tmp_path, "../escape")
    recipe = _recipe()
    files = prepare_job_files(tmp_path, recipe["job_id"])
    stage_recipe(files, recipe)
    changed = dict(recipe)
    changed["payload"] = {"changed": True}
    with pytest.raises(DazPolicyError, match="immutable"):
        stage_recipe(files, changed)


def test_launch_command_is_named_hidden_promptless_and_has_three_script_arguments(tmp_path: Path):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    recipe = _recipe()
    files = prepare_job_files(tmp_path, recipe["job_id"])
    command = build_daz_command(
        Path(r"C:\Program Files\DAZ 3D\DAZStudio6\DAZStudio.exe"),
        profile,
        files,
        entrypoint=tmp_path / "worker_main.dsa",
    )
    assert command[1:8] == [
        "-instanceName",
        "MaskFactoryDAZ",
        "-noDefaultScene",
        "-noPrompt",
        "-logSize",
        "100m",
        "-scriptArg",
    ]
    assert command.count("-scriptArg") == 3
    assert command[-1].endswith("worker_main.dsa")


@pytest.mark.parametrize("wrong_field", ["executable", "entrypoint"])
def test_worker_refuses_unpinned_executable_or_entrypoint_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_field: str
):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    executable = tmp_path / "DAZStudio.exe"
    entrypoint = tmp_path / "worker_main.dsa"
    executable.write_bytes(b"fixture executable")
    entrypoint.write_text("// fixture entrypoint", encoding="utf-8")
    recipe = _recipe()
    files = prepare_job_files(tmp_path / "jobs", recipe["job_id"])
    executable_hash = _sha256(executable)
    entrypoint_hash = _sha256(entrypoint)
    if wrong_field == "executable":
        executable_hash = "0" * 64
    else:
        entrypoint_hash = "0" * 64
    monkeypatch.setattr(
        daz_worker.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("hash drift must block process launch"),
    )
    with pytest.raises(DazPolicyError, match="hash does not match"):
        daz_worker.run_daz_job(
            executable=executable,
            profile=profile,
            files=files,
            recipe=recipe,
            entrypoint=entrypoint,
            expected_executable_sha256=executable_hash,
            expected_entrypoint_sha256=entrypoint_hash,
            allowed_artifact_roots=(tmp_path,),
            process_inventory=lambda: (),
        )


def test_shared_gpu_lease_blocks_second_daz_owner_without_deleting_lock(tmp_path: Path):
    path = tmp_path / "gpu.lock"
    with GpuLock(path, purpose="pipeline"):
        with pytest.raises(GpuLockBusyError):
            GpuLock(path, purpose="daz_render", image_id="job_0001").acquire()
        assert path.is_file()


def test_run_daz_job_acquires_shared_gpu_lease_before_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    lock_path = tmp_path / "gpu.lock"
    control_state = tmp_path / "runtime_state.json"
    control_state.write_text(
        json.dumps({"enabled": True, "paused": False, "drain": False, "stop_requested": False}),
        encoding="utf-8",
    )
    runtime_paths = replace(
        profile.runtime_paths,
        control_state=control_state,
        job_partial_root=tmp_path,
    )
    profile = replace(
        profile,
        runtime_paths=runtime_paths,
        gpu_lease={**profile.gpu_lease, "path": str(lock_path)},
        safety={**profile.safety, "minimum_render_free_gib": 0},
    )
    executable = tmp_path / "DAZStudio.exe"
    entrypoint = tmp_path / "worker_main.dsa"
    executable.write_bytes(b"fixture")
    entrypoint.write_text("// fixture", encoding="utf-8")
    recipe = _recipe(operation="render_scene")
    files = prepare_job_files(tmp_path / "jobs", recipe["job_id"])
    launched = False

    def forbidden_popen(*_args, **_kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("process must not launch while GPU is leased")

    monkeypatch.setattr(daz_worker.subprocess, "Popen", forbidden_popen)
    with GpuLock(lock_path, purpose="pipeline"):
        with pytest.raises(GpuLockBusyError):
            daz_worker.run_daz_job(
                executable=executable,
                profile=profile,
                files=files,
                recipe=recipe,
                entrypoint=entrypoint,
                expected_executable_sha256=_sha256(executable),
                expected_entrypoint_sha256=_sha256(entrypoint),
                allowed_artifact_roots=(tmp_path,),
                process_inventory=lambda: (),
            )
    assert launched is False


def test_worker_refuses_unmanaged_daz_before_any_probe_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    executable = tmp_path / "DAZStudio.exe"
    entrypoint = tmp_path / "worker_main.dsa"
    executable.write_bytes(b"fixture")
    entrypoint.write_text("// fixture", encoding="utf-8")
    recipe = _recipe()
    files = prepare_job_files(tmp_path / "jobs", recipe["job_id"])
    launched = False

    def forbidden_popen(*_args, **_kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("unmanaged DAZ must block launch")

    monkeypatch.setattr(daz_worker.subprocess, "Popen", forbidden_popen)
    with pytest.raises(DazPolicyError, match="unmanaged"):
        daz_worker.run_daz_job(
            executable=executable,
            profile=profile,
            files=files,
            recipe=recipe,
            entrypoint=entrypoint,
            expected_executable_sha256=_sha256(executable),
            expected_entrypoint_sha256=_sha256(entrypoint),
            allowed_artifact_roots=(tmp_path,),
            process_inventory=lambda: (1234,),
        )
    assert launched is False


def test_render_refuses_disabled_control_state_before_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    control_state = tmp_path / "runtime_state.json"
    control_state.write_text(
        json.dumps({"enabled": False, "paused": True, "drain": True, "stop_requested": False}),
        encoding="utf-8",
    )
    profile = replace(
        profile,
        runtime_paths=replace(profile.runtime_paths, control_state=control_state),
    )
    executable = tmp_path / "DAZStudio.exe"
    entrypoint = tmp_path / "worker_main.dsa"
    executable.write_bytes(b"fixture")
    entrypoint.write_text("// fixture", encoding="utf-8")
    recipe = _recipe(operation="render_scene")
    files = prepare_job_files(tmp_path / "jobs", recipe["job_id"])
    monkeypatch.setattr(
        daz_worker.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("disabled render must not launch"),
    )
    with pytest.raises(DazPolicyError, match="not enabled"):
        daz_worker.run_daz_job(
            executable=executable,
            profile=profile,
            files=files,
            recipe=recipe,
            entrypoint=entrypoint,
            expected_executable_sha256=_sha256(executable),
            expected_entrypoint_sha256=_sha256(entrypoint),
            allowed_artifact_roots=(tmp_path,),
            process_inventory=lambda: (),
        )


class _FakeProcess:
    pid = 4242

    def __init__(self) -> None:
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        del timeout
        self.exit_code = -9
        return self.exit_code


def test_watchdog_quarantines_dialog_without_clicking_and_records_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    recipe = _recipe()
    files = prepare_job_files(tmp_path, recipe["job_id"])
    process = _FakeProcess()

    def terminate(candidate):
        candidate.exit_code = -9

    monkeypatch.setattr(daz_worker, "_terminate_process_tree", terminate)
    observation = WindowObservation(4242, "Missing File", "#32770")
    outcome = daz_worker._watch_process(
        process,
        profile=profile,
        files=files,
        recipe=recipe,
        allowed_artifact_roots=(tmp_path,),
        timeout_seconds=60,
        started_monotonic=daz_worker.time.monotonic(),
        popup_detector=lambda _pid, _patterns: observation,
    )
    assert outcome.status == "quarantined"
    evidence = json.loads(files.watchdog_evidence.read_text(encoding="utf-8"))
    assert evidence["dialog"] == {
        "pid": 4242,
        "title": "Missing File",
        "class_name": "#32770",
    }
    assert evidence["action"] == "process_tree_terminated_without_ui_input"


def test_watchdog_timeout_terminates_process_tree_and_never_accepts_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = load_daz_runtime_profile(RUNTIME_CONFIG)
    recipe = _recipe()
    files = prepare_job_files(tmp_path, recipe["job_id"])
    files.partial_result.write_text('{"state":"rendering"}', encoding="utf-8")
    process = _FakeProcess()

    def terminate(candidate):
        candidate.exit_code = -9

    monkeypatch.setattr(daz_worker, "_terminate_process_tree", terminate)
    outcome = daz_worker._watch_process(
        process,
        profile=profile,
        files=files,
        recipe=recipe,
        allowed_artifact_roots=(tmp_path,),
        timeout_seconds=1,
        started_monotonic=daz_worker.time.monotonic() - 2,
        popup_detector=lambda _pid, _patterns: None,
    )
    assert outcome.status == "failed" and outcome.reason == "timeout"
    assert json.loads(files.watchdog_evidence.read_text(encoding="utf-8"))["reason"] == "timeout"


def test_popup_observation_is_metadata_only_value():
    observation = WindowObservation(pid=123, title="Missing File", class_name="#32770")
    assert observation.title == "Missing File"
    assert not hasattr(observation, "click")
