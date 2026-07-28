#!/usr/bin/env python3
"""Build and exercise an exact installed MaskFactory service release.

The runner is deliberately fail closed.  It accepts only a clean, published
source commit, builds from ``git archive``, installs the resulting wheel into a
new environment, starts one loopback-only child service, checks health/models
and the expected no-champion refusal, owns shutdown, and proves that its child,
port, and GPU-process snapshot did not leak.  It also revalidates the immutable
distinct-pod persistent-restore evidence required by MF-P6-20.04.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Mapping


class LifecycleEvidenceError(RuntimeError):
    """The lifecycle run cannot support an acceptance claim."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if check and process.returncode:
        detail = (process.stderr or process.stdout)[-4000:]
        raise LifecycleEvidenceError(
            f"command failed ({process.returncode}): {command!r}\n{detail}"
        )
    return process


def _git(repo_root: Path, *arguments: str) -> str:
    return _run(["git", *arguments], cwd=repo_root).stdout.strip()


def validate_persistent_restore(repo_root: Path) -> dict[str, Any]:
    prior_path = (
        repo_root / "qa/live_verification/runpod_package_persistence_and_restore_20260722.json"
    )
    replacement_path = (
        repo_root
        / "runtime_artifacts/runpod_package_pod_replacement_restore_20260725T205000Z"
        / "POD_REPLACEMENT_RESTORE_RECEIPT.json"
    )
    verifier_path = replacement_path.parent / "verify_exact_package_restore.py"
    descriptor_path = repo_root / "data/packages.dvc"
    for path in (prior_path, replacement_path, verifier_path, descriptor_path):
        if not path.is_file():
            raise LifecycleEvidenceError(f"persistent-restore input is missing: {path}")

    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    replacement = json.loads(replacement_path.read_text(encoding="utf-8"))
    prior_sha = sha256_file(prior_path)
    if replacement.get("status") != "RUNTIME_PASS_POD_REPLACEMENT_RESTORE":
        raise LifecycleEvidenceError("replacement-pod restore status is not passing")
    if replacement.get("prior_proof", {}).get("sha256") != prior_sha:
        raise LifecycleEvidenceError("replacement receipt does not bind the exact prior proof")
    prior_platform = prior.get("platform", {})
    current_pod = replacement.get("current_pod", {})
    if current_pod.get("id") == prior_platform.get("pod_id"):
        raise LifecycleEvidenceError("restore did not use a distinct Pod")
    if current_pod.get("network_volume_id") != prior_platform.get("network_volume_id"):
        raise LifecycleEvidenceError("replacement Pod used a different network volume")

    exact = replacement.get("exact_package", {})
    descriptor_sha = sha256_file(descriptor_path)
    if exact.get("descriptor_sha256") != descriptor_sha:
        raise LifecycleEvidenceError("current package descriptor bytes differ from restore proof")
    if replacement.get("replay_verifier", {}).get("sha256") != sha256_file(verifier_path):
        raise LifecycleEvidenceError("replacement restore verifier bytes drifted")
    results = replacement.get("replay_verifier", {}).get("result")
    if (
        not isinstance(results, dict)
        or not results
        or not all(value is True for value in results.values())
    ):
        raise LifecycleEvidenceError("replacement restore verifier has a non-passing result")

    return {
        "status": "PASS",
        "prior_receipt": {
            "path": prior_path.relative_to(repo_root).as_posix(),
            "sha256": prior_sha,
            "status": prior.get("status"),
            "pod_id": prior_platform.get("pod_id"),
            "network_volume_id": prior_platform.get("network_volume_id"),
        },
        "replacement_receipt": {
            "path": replacement_path.relative_to(repo_root).as_posix(),
            "sha256": sha256_file(replacement_path),
            "pod_id": current_pod.get("id"),
            "network_volume_id": current_pod.get("network_volume_id"),
            "result_checks": len(results),
        },
        "verifier": {
            "path": verifier_path.relative_to(repo_root).as_posix(),
            "sha256": sha256_file(verifier_path),
        },
        "descriptor": {
            "path": descriptor_path.relative_to(repo_root).as_posix(),
            "sha256": descriptor_sha,
            "restored_file_count": exact.get("restored_file_count"),
            "manifest_sha256": exact.get("manifest_sha256"),
            "archive_sha256": exact.get("archive_sha256"),
            "chunk_count": exact.get("chunk_count"),
        },
        "claim_limit": "Persistent transport/restore proof only; no model, mask, gold, or release authority.",
    }


def _nvidia_compute_snapshot() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-compute-apps=pid,process_name",
        "--format=csv,noheader,nounits",
    ]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc), "rows": []}
    rows = sorted(line.strip() for line in process.stdout.splitlines() if line.strip())
    return {
        "available": process.returncode == 0,
        "returncode": process.returncode,
        "rows": rows,
        "stderr": process.stderr.strip()[-500:],
    }


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request_json(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = int(response.status)
            payload = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = exc.read()
    if status != expected_status:
        raise LifecycleEvidenceError(f"{url} returned {status}, expected {expected_status}")
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise LifecycleEvidenceError(f"{url} returned non-JSON bytes") from exc
    return {"http_status": status, "body": body}


def _predict_body() -> tuple[bytes, str]:
    from PIL import Image

    image = io.BytesIO()
    Image.new("RGB", (8, 8), (127, 63, 31)).save(image, format="PNG")
    boundary = "maskfactory-lifecycle-boundary"
    fields = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="labels"\r\n\r\n'
            "left_forearm\r\n"
        ).encode(),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="image"; filename="probe.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + image.getvalue()
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(fields), f"multipart/form-data; boundary={boundary}"


CONTROLLER = r"""from __future__ import annotations
import json
import sys
import threading
from pathlib import Path
import uvicorn
import maskfactory
from maskfactory.serve.api import create_app, create_production_runtime

port = int(sys.argv[1])
runtime = create_production_runtime(
    registry_path=Path(sys.argv[2]),
    models_root=Path(sys.argv[3]),
    config_path=Path(sys.argv[4]),
    external_registry_path=Path(sys.argv[5]),
)
app = create_app(runtime)
server = uvicorn.Server(
    uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
)
thread = threading.Thread(target=server.run, name="maskfactory-owned-uvicorn")
thread.start()
command = sys.stdin.readline().strip()
if command != "STOP":
    raise SystemExit("owned controller did not receive STOP")
server.should_exit = True
thread.join(20)
if thread.is_alive():
    raise SystemExit("owned uvicorn thread did not stop")
print(json.dumps({
    "maskfactory_import": str(Path(maskfactory.__file__).resolve()),
    "runtime_final_health": runtime.health(),
    "server_started": server.started,
    "server_should_exit": server.should_exit,
}, sort_keys=True))
"""


def _write_json(path: Path, document: dict[str, Any]) -> None:
    sealed = dict(document)
    sealed["self_sha256"] = canonical_sha256(sealed)
    path.write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_lifecycle(
    repo_root: Path,
    output_dir: Path,
    artifact_root: Path,
    *,
    source_commit: str,
) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    if output_dir.exists() or artifact_root.exists():
        raise LifecycleEvidenceError("output and artifact roots must not already exist")
    head = _git(repo_root, "rev-parse", "HEAD")
    resolved_source = _git(repo_root, "rev-parse", f"{source_commit}^{{commit}}")
    remote_main = _git(repo_root, "rev-parse", "origin/main")
    if resolved_source != head or head != remote_main:
        raise LifecycleEvidenceError("source must equal clean local and remote main")
    if _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise LifecycleEvidenceError("repository is dirty")
    source_tree = _git(repo_root, "rev-parse", f"{head}^{{tree}}")
    persistent = validate_persistent_restore(repo_root)

    output_dir.mkdir(parents=True)
    artifact_root.mkdir(parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="maskfactory_section03_lifecycle_"))
    launched: subprocess.Popen[str] | None = None
    port: int | None = None
    child_pid: int | None = None
    try:
        archive = artifact_root / f"maskfactory-{head[:12]}.zip"
        _run(
            ["git", "archive", "--format=zip", f"--output={archive}", head],
            cwd=repo_root,
        )
        export_root = temporary / "export"
        export_root.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(export_root)

        dist_root = temporary / "dist"
        dist_root.mkdir()
        build = _run(
            [
                "py",
                "-3.12",
                "-I",
                "-B",
                "-m",
                "build",
                "--wheel",
                "--sdist",
                "--outdir",
                str(dist_root),
                str(export_root),
            ],
            cwd=temporary,
            timeout=600,
        )
        wheels = list(dist_root.glob("*.whl"))
        sdists = list(dist_root.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise LifecycleEvidenceError("build did not produce exactly one wheel and one sdist")
        wheel = artifact_root / wheels[0].name
        sdist = artifact_root / sdists[0].name
        shutil.copy2(wheels[0], wheel)
        shutil.copy2(sdists[0], sdist)

        venv = temporary / "runtime_venv"
        _run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
            cwd=temporary,
            timeout=300,
        )
        venv_python = venv / "Scripts/python.exe"
        install = _run(
            [
                str(venv_python),
                "-I",
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--force-reinstall",
                str(wheel),
            ],
            cwd=temporary,
            timeout=300,
        )
        import_probe = _run(
            [
                str(venv_python),
                "-I",
                "-B",
                "-c",
                (
                    "import json,maskfactory; from pathlib import Path; "
                    "print(json.dumps({'path':str(Path(maskfactory.__file__).resolve()),"
                    "'version':maskfactory.__version__},sort_keys=True))"
                ),
            ],
            cwd=temporary,
        )
        import_record = json.loads(import_probe.stdout)
        import_path = Path(import_record["path"]).resolve(strict=True)
        if repo_root in import_path.parents or export_root in import_path.parents:
            raise LifecycleEvidenceError(
                "runtime imported ambient source instead of installed wheel"
            )
        if venv.resolve() not in import_path.parents:
            raise LifecycleEvidenceError("runtime import is outside the clean environment")

        controller_path = artifact_root / "owned_service_controller.py"
        controller_path.write_text(CONTROLLER, encoding="utf-8", newline="\n")
        pipeline = export_root / "configs/pipeline.yaml"
        external = export_root / "configs/external_sources.yaml"
        registry = export_root / "models/model_registry.json"
        models_root = export_root / "models"
        for path in (pipeline, external, registry, models_root):
            if not path.exists():
                raise LifecycleEvidenceError(f"clean export deployment input missing: {path}")

        port = _free_loopback_port()
        if _port_open(port):
            raise LifecycleEvidenceError("selected loopback port was already open")
        gpu_before = _nvidia_compute_snapshot()
        pip_freeze = _run(
            [str(venv_python), "-I", "-m", "pip", "freeze", "--all"],
            cwd=temporary,
        ).stdout
        pip_freeze_path = artifact_root / "runtime_pip_freeze.txt"
        pip_freeze_path.write_text(pip_freeze, encoding="utf-8", newline="\n")

        launched = subprocess.Popen(
            [
                str(venv_python),
                "-I",
                "-B",
                str(controller_path),
                str(port),
                str(registry),
                str(models_root),
                str(pipeline),
                str(external),
            ],
            cwd=temporary,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        child_pid = launched.pid
        deadline = time.monotonic() + 45
        health: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if launched.poll() is not None:
                stdout, stderr = launched.communicate()
                raise LifecycleEvidenceError(
                    f"owned service exited before health: {stdout[-1000:]} {stderr[-2000:]}"
                )
            try:
                health = _request_json(f"http://127.0.0.1:{port}/health")
                break
            except (OSError, LifecycleEvidenceError):
                time.sleep(0.25)
        if health is None:
            raise LifecycleEvidenceError("owned service did not become healthy")
        if health["body"].get("status") != "ok":
            raise LifecycleEvidenceError("owned service health is not ok")
        models = _request_json(f"http://127.0.0.1:{port}/models")
        if len(models["body"].get("models", [])) != 17:
            raise LifecycleEvidenceError("installed service did not expose 17 verified models")
        if models["body"].get("champions") or models["body"].get("configured_models"):
            raise LifecycleEvidenceError("local runtime unexpectedly claims configured champions")
        predict_body, content_type = _predict_body()
        predict = _request_json(
            f"http://127.0.0.1:{port}/predict",
            data=predict_body,
            headers={"Content-Type": content_type},
            expected_status=503,
        )
        if predict["body"].get("detail") != "champion prediction provider is not configured":
            raise LifecycleEvidenceError("missing-champion route did not fail closed exactly")

        try:
            import psutil

            owned_children = sorted(
                child.pid for child in psutil.Process(child_pid).children(recursive=True)
            )
            psutil_version = psutil.__version__
        except (ImportError, OSError) as exc:
            raise LifecycleEvidenceError(f"cannot inventory owned process tree: {exc}") from exc

        stdout, stderr = launched.communicate(input="STOP\n", timeout=30)
        returncode = launched.returncode
        launched = None
        if returncode != 0:
            raise LifecycleEvidenceError(
                f"owned service shutdown failed ({returncode}): {stdout[-1000:]} {stderr[-2000:]}"
            )
        controller_rows = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip().startswith("{") and line.strip().endswith("}")
        ]
        if len(controller_rows) != 1:
            raise LifecycleEvidenceError("owned controller emitted no unique terminal record")
        terminal = controller_rows[0]
        if terminal.get("runtime_final_health", {}).get("status") != "not_started":
            raise LifecycleEvidenceError("runtime did not execute its shutdown hook")
        if Path(terminal["maskfactory_import"]).resolve() != import_path:
            raise LifecycleEvidenceError("controller imported different MaskFactory bytes")

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and _port_open(port):
            time.sleep(0.1)
        if _port_open(port):
            raise LifecycleEvidenceError("owned loopback port leaked after shutdown")
        leaked_pids = []
        for pid in [child_pid, *owned_children]:
            try:
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                        leaked_pids.append(pid)
            except psutil.Error:
                pass
        if leaked_pids:
            raise LifecycleEvidenceError(f"owned processes leaked: {leaked_pids}")
        gpu_after = _nvidia_compute_snapshot()
        if gpu_before.get("rows") != gpu_after.get("rows"):
            raise LifecycleEvidenceError(
                "GPU compute-process snapshot changed during CPU-safe lifecycle"
            )

        artifacts = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (archive, wheel, sdist, controller_path, pip_freeze_path)
        }
        lifecycle = {
            "schema_version": "maskfactory.service_lifecycle_evidence.v1",
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "result": "PASS",
            "item_id": "MF-P6-20.04",
            "source": {
                "commit": head,
                "tree": source_tree,
                "branch": _git(repo_root, "branch", "--show-current"),
                "origin_main": remote_main,
                "status_rows": 0,
            },
            "clean_export": {
                "archive": artifacts[archive.name],
                "archive_name": archive.name,
                "wheel": artifacts[wheel.name],
                "wheel_name": wheel.name,
                "sdist": artifacts[sdist.name],
                "sdist_name": sdist.name,
                "build_command": "py -3.12 -I -B -m build --wheel --sdist",
                "build_exit_code": build.returncode,
                "build_stderr_tail": build.stderr[-1000:],
                "install_command": "<clean-venv-python> -I -m pip install --no-deps --force-reinstall <wheel>",
                "install_exit_code": install.returncode,
                "installed_import": import_record,
                "runtime_environment": artifacts[pip_freeze_path.name],
            },
            "deployment_inputs": {
                "registry_sha256": sha256_file(registry),
                "pipeline_sha256": sha256_file(pipeline),
                "external_registry_sha256": sha256_file(external),
                "verified_registry_models": len(models["body"]["models"]),
                "configured_champions": 0,
            },
            "process": {
                "owner": "this lifecycle runner",
                "pid": child_pid,
                "owned_descendants_at_health": owned_children,
                "returncode": returncode,
                "post_shutdown_leaked_pids": leaked_pids,
                "psutil_version": psutil_version,
            },
            "network": {
                "host": "127.0.0.1",
                "port": port,
                "wildcard_listener_requested": False,
                "pre_start_open": False,
                "post_shutdown_open": False,
            },
            "routes": {
                "health": health,
                "models": {
                    "http_status": models["http_status"],
                    "verified_model_count": len(models["body"]["models"]),
                    "champion_count": len(models["body"]["champions"]),
                },
                "predict_without_champions": predict,
            },
            "shutdown": terminal,
            "resources": {
                "gpu_work_performed": False,
                "shared_gpu_lease_acquired": False,
                "gpu_compute_before": gpu_before,
                "gpu_compute_after": gpu_after,
                "ports_leaked": 0,
                "processes_leaked": 0,
                "reservations_created": 0,
                "leases_created": 0,
            },
            "persistent_restore": persistent,
            "artifact_root": str(artifact_root),
            "artifacts": artifacts,
            "limitations": [
                "No champion checkpoints are present in this clean local deployment.",
                "The bounded predict route therefore proves exact fail-closed refusal, not GPU inference.",
                "Persistent restore proof is the immutable distinct-Pod package transport receipt.",
                "This receipt grants no visual, campaign, gold, champion, release, or ComfyUI-adoption credit.",
            ],
        }
        _write_json(output_dir / "service_lifecycle_evidence.json", lifecycle)
        return lifecycle
    finally:
        if launched is not None and launched.poll() is None:
            launched.terminate()
            try:
                launched.wait(timeout=10)
            except subprocess.TimeoutExpired:
                launched.kill()
                launched.wait(timeout=10)
        shutil.rmtree(temporary, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source-commit", default="HEAD")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        result = run_lifecycle(
            arguments.repo_root,
            arguments.output_dir,
            arguments.artifact_root,
            source_commit=arguments.source_commit,
        )
    except (LifecycleEvidenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"result": result["result"], "source": result["source"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
