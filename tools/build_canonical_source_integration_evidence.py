#!/usr/bin/env python3
"""Build acceptance-grade evidence for MF-P6-20.02.

The builder operates from a clean committed Git tree.  It inventories the
exact tree, reconstructs a clean export, imports every tracked MaskFactory
module with user-site and bytecode disabled, builds and installs the package,
meta-validates tracked JSON schemas, and emits the seven Section-02 artifacts.
It never advances tracker state.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import jsonschema

SCHEMA_VERSION = "maskfactory_canonical_source_integration.v1"
ITEM_ID = "MF-P6-20.02"
REQUIRED_ARTIFACTS = (
    "canonical_tree_manifest.json",
    "required_path_reconciliation.json",
    "module_import_inventory.json",
    "generated_artifact_manifest.json",
    "repo_hygiene_scan.json",
    "clean_tree_hash.txt",
)
MODEL_BINARY_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".engine",
    ".onnx",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
    ".tflite",
}
HIGH_CONFIDENCE_SECRET_PATTERNS = {
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
}
GENERATED_PATTERNS = (
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "build/",
    "dist/",
    "*.egg-info/",
)
CLASSIFICATION_PREFIXES = (
    ("src/maskfactory/", "PRODUCT_OR_AUTONOMY_SOURCE"),
    ("tests/", "TEST_SOURCE"),
    ("configs/", "CONFIGURATION_AUTHORITY"),
    ("schemas/", "SCHEMA_AUTHORITY"),
    ("Plan/", "PLAN_ITEM_INSTRUCTION_TRACKER_AUTHORITY"),
    ("tools/", "OPERATING_OR_VERIFICATION_TOOL"),
    (".github/", "CI_WORKFLOW_AUTHORITY"),
    ("runtime_artifacts/", "TRACKED_ACCEPTANCE_EVIDENCE"),
    ("qa/", "TRACKED_QA_EVIDENCE"),
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        stdout = completed.stdout.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout:\n{stdout[-4000:]}\nstderr:\n{stderr[-4000:]}"
        )
    return completed


def git_text(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo).stdout.decode("utf-8").strip()


def read_git_blobs(repo: Path, oids: Iterable[str]) -> dict[str, bytes]:
    unique = sorted(set(oids))
    completed = run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input_bytes=("\n".join(unique) + "\n").encode("ascii"),
    )
    stream = io.BytesIO(completed.stdout)
    result: dict[str, bytes] = {}
    for requested_oid in unique:
        header = stream.readline().rstrip(b"\n").split()
        if len(header) != 3 or header[1] != b"blob":
            raise RuntimeError(f"expected blob for {requested_oid}, got {b' '.join(header)!r}")
        size = int(header[2])
        payload = stream.read(size)
        separator = stream.read(1)
        if len(payload) != size or separator != b"\n":
            raise RuntimeError(f"malformed cat-file stream for {requested_oid}")
        result[requested_oid] = payload
    return result


def load_tree(repo: Path, ref: str) -> tuple[str, list[dict[str, Any]], dict[str, bytes]]:
    tree_oid = git_text(repo, "rev-parse", f"{ref}^{{tree}}")
    raw = run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", ref],
        cwd=repo,
    ).stdout
    entries: list[dict[str, Any]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        mode, object_type, oid = header.decode("ascii").split()
        if object_type != "blob":
            raise RuntimeError(f"unexpected tree object type {object_type}")
        entries.append(
            {
                "mode": mode,
                "oid": oid,
                "path": path_bytes.decode("utf-8", errors="strict"),
            }
        )
    blobs = read_git_blobs(repo, (entry["oid"] for entry in entries))
    return tree_oid, entries, blobs


def classify_path(path: str) -> str:
    for prefix, classification in CLASSIFICATION_PREFIXES:
        if path.startswith(prefix):
            return classification
    if path in {"pyproject.toml", "uv.lock"} or path.startswith("env/"):
        return "PACKAGE_OR_ENVIRONMENT_AUTHORITY"
    if path.startswith(".codex-ops/"):
        return "REPOSITORY_CONTROL_AUTHORITY"
    return "OTHER_TRACKED_PROJECT_FILE"


def module_name(path: str) -> str | None:
    prefix = "src/maskfactory/"
    if not path.startswith(prefix) or not path.endswith(".py"):
        return None
    relative = path[len("src/") : -len(".py")]
    parts = relative.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def isolated_imports(
    python: Path,
    source_root: Path,
    modules: list[str],
) -> dict[str, Any]:
    script = r"""
import importlib
import json
import pathlib
import sys

request = json.load(sys.stdin)
root = pathlib.Path(request["root"]).resolve()
sys.path.insert(0, str(root))
rows = []
for name in request["modules"]:
    try:
        module = importlib.import_module(name)
        raw_origin = getattr(module, "__file__", None)
        origin = str(pathlib.Path(raw_origin).resolve()) if raw_origin else None
        under_root = bool(origin and pathlib.Path(origin).is_relative_to(root))
        rows.append({
            "module": name,
            "status": "PASS" if under_root else "FAIL",
            "origin": origin,
            "origin_under_expected_root": under_root,
            "error_type": None,
            "error": None,
        })
    except BaseException as exc:
        rows.append({
            "module": name,
            "status": "FAIL",
            "origin": None,
            "origin_under_expected_root": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
print(json.dumps(rows, sort_keys=True))
"""
    request = canonical_json_bytes({"root": str(source_root), "modules": modules})
    completed = run(
        [str(python), "-I", "-B", "-c", script],
        cwd=source_root.parent,
        input_bytes=request,
        check=False,
    )
    if completed.returncode and not completed.stdout:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace")[-4000:])
    rows = json.loads(completed.stdout.decode("utf-8"))
    failures = [row for row in rows if row["status"] != "PASS"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "module_count": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "rows": rows,
    }


def safe_extract_git_archive(payload: bytes, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive.getmembers():
            target = (root / member.name).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"archive member escapes root: {member.name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"archive link is not accepted: {member.name}")
        archive.extractall(root)


def validate_schemas(entries: list[dict[str, Any]], blobs: dict[str, bytes]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        path = entry["path"]
        if not path.endswith(".schema.json"):
            continue
        try:
            document = json.loads(blobs[entry["oid"]].decode("utf-8-sig"))
            validator = jsonschema.validators.validator_for(document)
            validator.check_schema(document)
            rows.append(
                {
                    "path": path,
                    "status": "PASS",
                    "validator": validator.__name__,
                    "error": None,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "path": path,
                    "status": "FAIL",
                    "validator": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    failures = [row for row in rows if row["status"] != "PASS"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "schema_count": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "rows": rows,
    }


def build_and_inspect_package(
    repo: Path,
    ref: str,
    commit_epoch: str,
    modules: list[str],
) -> dict[str, Any]:
    archive = run(["git", "archive", "--format=tar", ref], cwd=repo).stdout
    with tempfile.TemporaryDirectory(prefix="maskfactory-section02-") as raw_tmp:
        temporary = Path(raw_tmp)
        export = temporary / "export"
        export.mkdir()
        safe_extract_git_archive(archive, export)
        output = temporary / "dist"
        output.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "SOURCE_DATE_EPOCH": commit_epoch,
            }
        )
        build = run(
            [
                sys.executable,
                "-I",
                "-B",
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--sdist",
                "--outdir",
                str(output),
            ],
            cwd=export,
            env=environment,
        )
        wheels = sorted(output.glob("*.whl"))
        sdists = sorted(output.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("build did not produce exactly one wheel and one sdist")
        wheel = wheels[0]
        sdist = sdists[0]
        install_root = temporary / "installed"
        install = run(
            [
                sys.executable,
                "-I",
                "-B",
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--disable-pip-version-check",
                "--target",
                str(install_root),
                str(wheel),
            ],
            cwd=temporary,
            env=environment,
        )
        source_imports = isolated_imports(Path(sys.executable), export / "src", modules)
        installed_imports = isolated_imports(Path(sys.executable), install_root, modules)
        pyproject = tomllib.loads((export / "pyproject.toml").read_text("utf-8"))
        declared_package_data = (
            pyproject.get("tool", {})
            .get("setuptools", {})
            .get("package-data", {})
            .get("maskfactory", [])
        )
        source_schema_paths = sorted(
            path.relative_to(export / "src").as_posix()
            for path in (export / "src" / "maskfactory" / "schemas").glob("*.json")
        )
        with zipfile.ZipFile(wheel) as archive_zip:
            wheel_paths = sorted(archive_zip.namelist())
        wheel_schema_paths = sorted(
            path
            for path in wheel_paths
            if path.startswith("maskfactory/schemas/") and path.endswith(".json")
        )
        missing_package_data = sorted(set(source_schema_paths) - set(wheel_schema_paths))
        unexpected_package_data = sorted(set(wheel_schema_paths) - set(source_schema_paths))
        entry_points = [
            path for path in wheel_paths if path.endswith(".dist-info/entry_points.txt")
        ]
        package_status = (
            "PASS"
            if source_imports["status"] == "PASS"
            and installed_imports["status"] == "PASS"
            and not missing_package_data
            and not unexpected_package_data
            and len(entry_points) == 1
            else "FAIL"
        )
        return {
            "status": package_status,
            "git_archive_sha256": sha256_bytes(archive),
            "build_command": "python -I -B -m build --no-isolation --wheel --sdist",
            "build_exit_code": build.returncode,
            "build_stderr_tail": build.stderr.decode("utf-8", errors="replace")[-2000:],
            "wheel": {
                "name": wheel.name,
                "bytes": wheel.stat().st_size,
                "sha256": sha256_file(wheel),
                "entry_count": len(wheel_paths),
            },
            "sdist": {
                "name": sdist.name,
                "bytes": sdist.stat().st_size,
                "sha256": sha256_file(sdist),
            },
            "install_exit_code": install.returncode,
            "declared_package_data": declared_package_data,
            "source_schema_count": len(source_schema_paths),
            "wheel_schema_count": len(wheel_schema_paths),
            "missing_package_data": missing_package_data,
            "unexpected_package_data": unexpected_package_data,
            "entry_point_metadata": entry_points,
            "source_imports": source_imports,
            "installed_imports": installed_imports,
            "temporary_export_retained": False,
        }


def scan_generated_cache_files(repo: Path) -> list[str]:
    rows: list[str] = []
    for root_name in ("src", "tests", "tools"):
        root = repo / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file() and (path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts):
                rows.append(path.relative_to(repo).as_posix())
    return sorted(rows)


def scan_hygiene(
    entries: list[dict[str, Any]],
    blobs: dict[str, bytes],
    pre_generation_status: list[str],
    cache_files: list[str],
) -> dict[str, Any]:
    tracked_model_binaries: list[str] = []
    tracked_dataset_payloads: list[str] = []
    tracked_environment_files: list[str] = []
    secret_candidates: list[dict[str, str]] = []
    runtime_evidence_extensions: Counter[str] = Counter()
    runtime_evidence_bytes = 0
    for entry in entries:
        path = entry["path"]
        suffix = PurePosixPath(path).suffix.lower()
        payload = blobs[entry["oid"]]
        if suffix in MODEL_BINARY_SUFFIXES:
            tracked_model_binaries.append(path)
        if path.startswith(("data/", "datasets/")) and not (
            path.endswith(".dvc") or path.endswith(".gitignore")
        ):
            tracked_dataset_payloads.append(path)
        if PurePosixPath(path).name in {".env", ".env.local", ".env.production"}:
            tracked_environment_files.append(path)
        if path.startswith("runtime_artifacts/"):
            runtime_evidence_extensions[suffix or "<none>"] += 1
            runtime_evidence_bytes += len(payload)
        for pattern_name, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            if pattern.search(payload):
                secret_candidates.append({"path": path, "pattern": pattern_name})
    failures = (
        tracked_model_binaries
        + tracked_dataset_payloads
        + tracked_environment_files
        + [row["path"] for row in secret_candidates]
        + pre_generation_status
        + cache_files
    )
    return {
        "status": "PASS" if not failures else "FAIL",
        "pre_generation_status_rows": pre_generation_status,
        "tracked_model_binaries": tracked_model_binaries,
        "tracked_dataset_payloads": tracked_dataset_payloads,
        "tracked_environment_files": tracked_environment_files,
        "high_confidence_secret_candidates": secret_candidates,
        "generated_python_cache_files": cache_files,
        "tracked_runtime_evidence": {
            "classification": "TRACKED_ACCEPTANCE_EVIDENCE_NOT_RUNTIME_AUTHORITY",
            "file_count": sum(runtime_evidence_extensions.values()),
            "logical_bytes": runtime_evidence_bytes,
            "extension_counts": dict(sorted(runtime_evidence_extensions.items())),
            "limitation": (
                "Tracked evidence does not prove current runtime health and cannot "
                "advance MF-P6-20.04 without its independent lifecycle receipt."
            ),
        },
    }


def requirement_rows(paths: set[str], authority_matrix_ok: bool) -> list[dict[str, Any]]:
    requirements: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("package_metadata", ("pyproject.toml",)),
        ("product_package", ("src/maskfactory/__init__.py",)),
        ("product_cli", ("src/maskfactory/cli.py",)),
        ("model_registry_source", ("src/maskfactory/models/registry.py",)),
        ("recovered_benchmark_source", ("src/maskfactory/models/benchmark.py",)),
        ("autonomy_source", ("src/maskfactory/autonomy/controller.py",)),
        ("steward_source", ("src/maskfactory/steward/supervisor.py",)),
        ("service_source", ("src/maskfactory/serve/api.py",)),
        ("tracker_authority", ("Plan/Tracker/tracker.py", "Plan/Tracker/tracker.json")),
        (
            "ultimate_e2e_item_and_instruction",
            (
                "Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md",
                "Plan/Instructions/18_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md",
            ),
        ),
        (
            "recovery_attribution_receipt",
            (".codex-ops/HISTORICAL_STASH_AUTHORITY_BINDING_20260728T212749Z.json",),
        ),
    )
    rows: list[dict[str, Any]] = []
    for name, required_paths in requirements:
        missing = sorted(set(required_paths) - paths)
        rows.append(
            {
                "requirement": name,
                "required_paths": list(required_paths),
                "missing_paths": missing,
                "status": "PASS" if not missing else "FAIL",
            }
        )
    rows.append(
        {
            "requirement": "historical_stash_row_authority",
            "required_paths": [],
            "missing_paths": [],
            "status": "PASS" if authority_matrix_ok else "FAIL",
        }
    )
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def canonical_path_key(path: str | Path) -> str:
    """Return a separator- and case-normalized absolute path identity."""
    return os.path.normcase(os.path.normpath(os.path.realpath(os.fspath(path))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--created-utc", required=True)
    parser.add_argument("--authority-matrix", type=Path, required=True)
    parser.add_argument("--authority-matrix-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError(f"output directory already exists: {output_dir}")
    if canonical_path_key(git_text(repo, "rev-parse", "--show-toplevel")) != canonical_path_key(
        repo
    ):
        raise RuntimeError("repo argument is not the Git top level")
    pre_generation_status = [
        line
        for line in git_text(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
        if line
    ]
    if pre_generation_status:
        raise RuntimeError(
            f"canonical evidence requires a clean worktree, got {len(pre_generation_status)} rows"
        )
    head = git_text(repo, "rev-parse", "HEAD")
    branch = git_text(repo, "branch", "--show-current")
    tree_oid, entries, blobs = load_tree(repo, "HEAD")
    commit_epoch = git_text(repo, "show", "-s", "--format=%ct", "HEAD")
    authority_matrix_sha = sha256_file(args.authority_matrix)
    authority_matrix_ok = authority_matrix_sha.lower() == args.authority_matrix_sha256.lower()
    if not authority_matrix_ok:
        raise RuntimeError("authority matrix hash mismatch")

    manifest_rows = [
        {
            "path": entry["path"],
            "mode": entry["mode"],
            "git_blob_oid": entry["oid"],
            "bytes": len(blobs[entry["oid"]]),
            "sha256": sha256_bytes(blobs[entry["oid"]]),
            "classification": classify_path(entry["path"]),
        }
        for entry in entries
    ]
    classification_counts = Counter(row["classification"] for row in manifest_rows)
    canonical_manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": args.created_utc,
        "item_id": ITEM_ID,
        "commit_oid": head,
        "tree_oid": tree_oid,
        "branch": branch,
        "tracked_file_count": len(manifest_rows),
        "tracked_logical_bytes": sum(row["bytes"] for row in manifest_rows),
        "classification_counts": dict(sorted(classification_counts.items())),
        "rows": manifest_rows,
    }

    paths = {entry["path"] for entry in entries}
    requirement_checks = requirement_rows(paths, authority_matrix_ok)
    required_path_reconciliation = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": args.created_utc,
        "item_id": ITEM_ID,
        "commit_oid": head,
        "historical_stash_authority": {
            "path": str(args.authority_matrix),
            "sha256": authority_matrix_sha,
            "expected_rows": 4008,
            "status": "PASS",
        },
        "checks": requirement_checks,
        "status": (
            "PASS" if all(row["status"] == "PASS" for row in requirement_checks) else "FAIL"
        ),
    }

    modules = sorted(name for entry in entries if (name := module_name(entry["path"])) is not None)
    package = build_and_inspect_package(repo, "HEAD", commit_epoch, modules)
    module_import_inventory = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": args.created_utc,
        "item_id": ITEM_ID,
        "commit_oid": head,
        "module_count": len(modules),
        "source_imports": package["source_imports"],
        "installed_imports": package["installed_imports"],
        "bytecode_disabled": True,
        "user_site_disabled": True,
        "status": (
            "PASS"
            if package["source_imports"]["status"] == "PASS"
            and package["installed_imports"]["status"] == "PASS"
            else "FAIL"
        ),
    }

    cache_files = scan_generated_cache_files(repo)
    generated_artifact_manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": args.created_utc,
        "item_id": ITEM_ID,
        "generated_patterns": list(GENERATED_PATTERNS),
        "regeneration_commands": {
            "tracker_dashboard": "python Plan/Tracker/tracker.py report",
            "tracker_state": "python Plan/Tracker/tracker.py rebuild",
            "python_bytecode": "not retained; imports and tests use PYTHONDONTWRITEBYTECODE=1",
            "build_outputs": "python -I -B -m build --no-isolation --wheel --sdist",
        },
        "repository_python_cache_files_before_generation": cache_files,
        "status": "PASS" if not cache_files else "FAIL",
    }
    hygiene = scan_hygiene(entries, blobs, pre_generation_status, cache_files)
    schema_validation = validate_schemas(entries, blobs)
    repo_hygiene_scan = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": args.created_utc,
        "item_id": ITEM_ID,
        "commit_oid": head,
        "tree_oid": tree_oid,
        "hygiene": hygiene,
        "schema_validation": schema_validation,
        "package_validation": {
            key: value
            for key, value in package.items()
            if key not in {"source_imports", "installed_imports"}
        },
        "status": (
            "PASS"
            if hygiene["status"] == "PASS"
            and schema_validation["status"] == "PASS"
            and package["status"] == "PASS"
            else "FAIL"
        ),
    }

    output_dir.mkdir(parents=True)
    artifacts = {
        "canonical_tree_manifest.json": canonical_manifest,
        "required_path_reconciliation.json": required_path_reconciliation,
        "module_import_inventory.json": module_import_inventory,
        "generated_artifact_manifest.json": generated_artifact_manifest,
        "repo_hygiene_scan.json": repo_hygiene_scan,
    }
    for name, document in artifacts.items():
        write_json(output_dir / name, document)
    (output_dir / "clean_tree_hash.txt").write_text(
        f"commit {head}\ntree {tree_oid}\n", encoding="utf-8", newline="\n"
    )
    artifact_bindings = {
        name: {
            "bytes": (output_dir / name).stat().st_size,
            "sha256": sha256_file(output_dir / name),
        }
        for name in REQUIRED_ARTIFACTS
    }
    overall_status = (
        "PASS"
        if required_path_reconciliation["status"] == "PASS"
        and module_import_inventory["status"] == "PASS"
        and generated_artifact_manifest["status"] == "PASS"
        and repo_hygiene_scan["status"] == "PASS"
        else "FAIL"
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": args.created_utc,
        "item_id": ITEM_ID,
        "result": overall_status,
        "claim_tier": ("PRODUCTION_EVIDENCE_PASS" if overall_status == "PASS" else "IN_PROGRESS"),
        "validated_source_commit": head,
        "validated_source_tree": tree_oid,
        "branch": branch,
        "pre_generation_status_rows": 0,
        "artifacts": artifact_bindings,
        "acceptance_checks": {
            "one_canonical_tree": required_path_reconciliation["status"],
            "zero_required_untracked_source": ("PASS" if not pre_generation_status else "FAIL"),
            "isolated_source_imports": package["source_imports"]["status"],
            "isolated_installed_imports": package["installed_imports"]["status"],
            "schema_meta_validation": schema_validation["status"],
            "package_build_install_data": package["status"],
            "secret_model_dataset_hygiene": hygiene["status"],
            "generated_cache_absence": generated_artifact_manifest["status"],
            "historical_path_reconciliation": ("PASS" if authority_matrix_ok else "FAIL"),
        },
        "package": repo_hygiene_scan["package_validation"],
        "limitations": [
            "This receipt proves MF-P6-20.02 canonical source integration only.",
            "It does not grant runtime health, visual, campaign, release, or ComfyUI adoption credit.",
            "Repository-wide Ruff/Black debt remains governed by MF-P6-20.03 and is not reported as passing here.",
        ],
        "rollback": {
            "pre_change_checkpoint": "C:\\MaskFactory_TierA_Backups\\section02_acceptance_before_change_20260728T214114Z",
            "manifest_sha256": "67e56a07d389b68c2e20f0e34f85c671c5783055c6e8fe0f9788b6c8311382c5",
            "source_commit_remotely_protected_before_tracker_completion": False,
        },
        "receipt_commit_rule": (
            "Commit these artifacts and governed tracker update after the validated "
            "source commit, push non-forced, then prove local main equals origin/main."
        ),
    }
    write_json(output_dir / "section_acceptance_receipt.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
