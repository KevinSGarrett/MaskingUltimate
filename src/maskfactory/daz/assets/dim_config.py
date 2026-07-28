"""Atomic, credential-preserving DAZ Install Manager path configuration."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .dim_manifest import DimManifestError

DOWNLOAD_PATH = "F:/DAZ/02_installers/dim_downloads"
INSTALL_PATH = "F:/DAZ/03_content/libraries/MaskFactory_DAZ_Library"
INSTALL_TITLE = "MaskFactory DAZ Library"
MAX_ACCOUNT_SETTINGS_BYTES = 1024 * 1024


def configure_dim_paths(path: Path, *, apply: bool = False) -> dict[str, Any]:
    """Plan or atomically change only nonsecret DIM path/automation keys."""
    path = Path(path)
    if not path.is_file():
        raise DimManifestError("dim_settings_missing", "DIM account settings file is missing")
    if path.stat().st_size > MAX_ACCOUNT_SETTINGS_BYTES:
        raise DimManifestError("dim_settings_too_large", "DIM account settings exceed 1 MiB")
    if apply and dim_processes_running():
        raise DimManifestError(
            "dim_process_running", "close DAZ Install Manager before applying paths"
        )
    try:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DimManifestError("dim_settings_unreadable", type(exc).__name__) from exc
    newline = "\r\n" if "\r\n" in original else "\n"
    trailing_newline = original.endswith(("\n", "\r"))
    lines = original.splitlines()
    rewritten, before = _rewrite_lines(lines)
    rendered = newline.join(rewritten) + (newline if trailing_newline else "")
    rendered_bytes = rendered.encode("utf-8")
    changed = rendered_bytes != original_bytes
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "apply": apply,
        "changed": changed,
        "before": before,
        "after": {
            "download_root": "expected_f",
            "install_root": "expected_f",
            "install_path_count": 1,
            "automatic_install": False,
        },
        "credential_values_extracted": False,
        "credential_fields_modified": False,
        "before_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "after_sha256": hashlib.sha256(rendered_bytes).hexdigest(),
    }
    if not apply or not changed:
        report["applied"] = False
        return report

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(rendered_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_preserving_metadata(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if path.read_bytes() != rendered_bytes:
        raise DimManifestError(
            "dim_settings_verify_failed", "atomic DIM settings verification failed"
        )
    report["applied"] = True
    return report


def inspect_dim_paths(path: Path) -> dict[str, Any]:
    """Return only path classifications and automation state, never account values."""
    report = configure_dim_paths(path, apply=False)
    return {
        "schema_version": report["schema_version"],
        "before": report["before"],
        "already_compliant": not report["changed"],
        "settings_sha256": report["before_sha256"],
        "credential_values_extracted": False,
    }


def dim_processes_running() -> tuple[int, ...]:
    if os.name != "nt":
        return ()
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq DAZ3DIM.exe", "/FO", "CSV", "/NH"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    found = re.findall(r'^"DAZ3DIM\.exe","([0-9]+)"', completed.stdout, flags=re.MULTILINE)
    return tuple(sorted(int(value) for value in found))


def _rewrite_lines(lines: list[str]) -> tuple[list[str], dict[str, Any]]:
    replacements = {
        ("General", "DownloadPath"): DOWNLOAD_PATH,
        ("General", "CurInstallPath"): INSTALL_PATH,
        ("General", "AutoInstall"): "false",
        ("InstallPaths", "size"): "1",
        ("InstallPaths", r"1\InstallPathTitle"): INSTALL_TITLE,
        ("InstallPaths", r"1\InstallPath"): INSTALL_PATH,
    }
    seen: set[tuple[str, str]] = set()
    output: list[str] = []
    current_section = ""
    before_values: dict[tuple[str, str], str] = {}
    install_path_entry = re.compile(r"^(?P<index>[0-9]+)\\InstallPath(?:Title)?=")
    for line in lines:
        section_match = re.fullmatch(r"\[([^]]+)]", line.strip())
        if section_match:
            current_section = section_match.group(1)
            output.append(line)
            continue
        if "=" not in line:
            output.append(line)
            continue
        key, value = line.split("=", 1)
        identity = (current_section, key)
        if current_section == "InstallPaths":
            path_match = install_path_entry.match(line)
            if path_match and path_match.group("index") != "1":
                continue
        if identity in replacements:
            if identity in seen:
                raise DimManifestError(
                    "dim_settings_duplicate_key", f"duplicate {current_section}/{key}"
                )
            seen.add(identity)
            before_values[identity] = value
            output.append(f"{key}={replacements[identity]}")
        else:
            output.append(line)
    missing = sorted(
        f"{section}/{key}" for section, key in replacements if (section, key) not in seen
    )
    if missing:
        raise DimManifestError("dim_settings_key_missing", "missing keys: " + ", ".join(missing))
    install_size = before_values[("InstallPaths", "size")]
    try:
        install_count = int(install_size)
    except ValueError as exc:
        raise DimManifestError(
            "dim_settings_install_count_invalid", "InstallPaths/size is not integer"
        ) from exc
    before = {
        "download_root": _root_state(before_values[("General", "DownloadPath")], DOWNLOAD_PATH),
        "install_root": _root_state(before_values[("General", "CurInstallPath")], INSTALL_PATH),
        "install_path_count": install_count,
        "automatic_install": before_values[("General", "AutoInstall")].casefold() == "true",
    }
    return output, before


def _root_state(value: str, expected: str) -> str:
    def normalize(item: str) -> str:
        return os.path.normcase(os.path.normpath(item.replace("/", os.sep)))

    return "expected_f" if normalize(value) == normalize(expected) else "legacy_non_f"


def _replace_preserving_metadata(temporary: Path, target: Path) -> None:
    if os.name != "nt":
        os.replace(temporary, target)
        return
    import ctypes

    replacefile_write_through = 0x00000001
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReplaceFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    kernel32.ReplaceFileW.restype = ctypes.c_int
    if not kernel32.ReplaceFileW(
        str(target), str(temporary), None, replacefile_write_through, None, None
    ):
        error = ctypes.get_last_error()
        raise DimManifestError("dim_settings_replace_failed", f"ReplaceFileW error {error}")


__all__ = ["configure_dim_paths", "dim_processes_running", "inspect_dim_paths"]
