"""Small authenticated CVAT REST client used by the scripted review bridge."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "cvat.yaml"


class CvatApiError(RuntimeError):
    """CVAT returned an error or malformed response."""


class CvatClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        opener: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.username = username
        self.password = password
        self.opener = opener or urllib.request.urlopen
        if not token and not (username and password):
            raise CvatApiError("CVAT token or username/password credentials are required")

    @classmethod
    def from_config(cls, path: Path = DEFAULT_CONFIG) -> CvatClient:
        config = load_cvat_config(path)
        credentials = _credentials(config)
        return cls(str(config["api_url"]), **credentials)

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 120,
        raw: bool = False,
    ) -> Any:
        url = path if path.startswith("http") else self.base_url + "/" + path.lstrip("/")
        # CVAT 2.24's DRF content negotiation rejects a generic explicit Accept header.
        request_headers = {"User-Agent": "MaskFactory/0.0.1", **(headers or {})}
        if self.token:
            request_headers["Authorization"] = f"Token {self.token}"
        else:
            encoded = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            request_headers["Authorization"] = f"Basic {encoded}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            response_context = self.opener(request, timeout=timeout)
            with response_context as response:
                body = response.read()
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise CvatApiError(f"CVAT {method} {url} returned {exc.code}: {detail}") from exc
        except OSError as exc:
            raise CvatApiError(f"CVAT {method} {url} failed: {exc}") from exc
        if status < 200 or status >= 300:
            raise CvatApiError(f"CVAT {method} {url} returned status {status}")
        if raw:
            return body
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise CvatApiError(f"CVAT {method} {url} returned invalid JSON") from exc

    def paginated(self, path: str) -> list[dict[str, Any]]:
        response = self.request("GET", path)
        if isinstance(response, list):
            return response
        results: list[dict[str, Any]] = []
        while isinstance(response, dict):
            page = response.get("results")
            if not isinstance(page, list):
                raise CvatApiError(f"CVAT paginated response has no results list: {path}")
            results.extend(page)
            next_url = response.get("next")
            if not next_url:
                break
            response = self.request("GET", str(next_url))
        return results

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str | int],
        files: dict[str, tuple[str, bytes, str]],
        timeout: float = 120,
    ) -> Any:
        boundary = "maskfactory-" + uuid.uuid4().hex
        body = bytearray()
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(str(value).encode())
            body.extend(b"\r\n")
        for name, (filename, content, content_type) in files.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.extend(content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self._request_bytes(method, path, bytes(body), headers=headers, timeout=timeout)

    def wait_request(self, request_id: str, *, timeout: float = 300) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.request("GET", f"/api/requests/{urllib.parse.quote(request_id, safe='')}")
            state = status.get("status") if isinstance(status, dict) else None
            if state == "finished":
                return status
            if state == "failed":
                raise CvatApiError(f"CVAT async request failed: {status.get('message', status)}")
            time.sleep(0.5)
        raise CvatApiError(f"CVAT async request timed out after {timeout}s: {request_id}")

    def _request_bytes(
        self,
        method: str,
        path: str,
        data: bytes,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> Any:
        url = self.base_url + "/" + path.lstrip("/")
        request_headers = {"User-Agent": "MaskFactory/0.0.1", **headers}
        if self.token:
            request_headers["Authorization"] = f"Token {self.token}"
        else:
            encoded = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            request_headers["Authorization"] = f"Basic {encoded}"
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with self.opener(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise CvatApiError(f"CVAT {method} {url} returned {exc.code}: {detail}") from exc
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise CvatApiError(f"CVAT {method} {url} returned invalid JSON") from exc


def load_cvat_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise CvatApiError(f"CVAT config root must be a mapping: {path}")
    if not isinstance(document.get("api_url"), str):
        raise CvatApiError("CVAT config requires api_url")
    return document


def _credentials(config: dict[str, Any]) -> dict[str, str | None]:
    values = dict(os.environ)
    env_path = config.get("credentials", {}).get("env_file")
    if env_path:
        candidate = Path(str(env_path))
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if candidate.is_file():
            values = {**_read_dotenv(candidate), **values}
    return {
        "token": values.get("CVAT_TOKEN") or None,
        "username": values.get("CVAT_USERNAME") or None,
        "password": values.get("CVAT_PASSWORD") or None,
    }


def _read_dotenv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result
