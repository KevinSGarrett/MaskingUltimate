"""Provision and verify the local CVAT administrator without exposing secrets."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
CVAT_URL = "http://localhost:8080"


def _read_env() -> tuple[list[str], dict[str, str]]:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def _write_env(lines: list[str], updates: dict[str, str]) -> None:
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if output and output[-1] != "":
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    ENV_PATH.write_text("\n".join(output) + "\n", encoding="utf-8")


def _request(path: str, *, data: dict[str, str] | None = None, token: str = "") -> dict:
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    request = urllib.request.Request(CVAT_URL + path, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        if response.status != 200:
            raise RuntimeError(f"CVAT returned HTTP {response.status} for {path}")
        return json.load(response)


def main() -> None:
    """Create/update the admin, obtain a token, and prove authenticated access."""
    lines, values = _read_env()
    username = values.get("CVAT_USERNAME") or "kevin"
    password = values.get("CVAT_PASSWORD") or secrets.token_urlsafe(32)
    email = values.get("CVAT_EMAIL") or "kevin@maskfactory.local"
    _write_env(
        lines,
        {"CVAT_USERNAME": username, "CVAT_PASSWORD": password, "CVAT_EMAIL": email},
    )

    command = (
        "import os; "
        "from django.contrib.auth import get_user_model; "
        "User=get_user_model(); "
        "u,created=User.objects.get_or_create(username=os.environ['CVAT_USERNAME'], "
        "defaults={'email': os.environ['CVAT_EMAIL']}); "
        "u.email=os.environ['CVAT_EMAIL']; u.is_staff=True; u.is_superuser=True; "
        "u.set_password(os.environ['CVAT_PASSWORD']); u.save(); "
        "print('admin_created='+str(created))"
    )
    process_env = os.environ.copy()
    process_env.update({"CVAT_USERNAME": username, "CVAT_PASSWORD": password, "CVAT_EMAIL": email})
    subprocess.run(  # noqa: S603
        [
            "docker",
            "exec",
            "-e",
            "CVAT_USERNAME",
            "-e",
            "CVAT_PASSWORD",
            "-e",
            "CVAT_EMAIL",
            "cvat_server",
            "python3",
            "manage.py",
            "shell",
            "-c",
            command,
        ],
        cwd=ROOT,
        env=process_env,
        check=True,
    )

    login = _request("/api/auth/login", data={"username": username, "password": password})
    token = login.get("key")
    if not isinstance(token, str) or not token:
        raise RuntimeError("CVAT login succeeded without returning an API token")
    current_user = _request("/api/users/self", token=token)
    if current_user.get("username") != username or not current_user.get("is_superuser"):
        raise RuntimeError("Authenticated CVAT user is not the expected superuser")

    lines, _ = _read_env()
    _write_env(lines, {"CVAT_TOKEN": token})
    print(f"verified_admin={username}; authenticated_user_endpoint=200; token_stored=true")


if __name__ == "__main__":
    main()
