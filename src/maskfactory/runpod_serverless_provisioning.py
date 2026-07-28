"""Idempotent RunPod resources for the two-profile Serverless overflow."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from maskfactory.autonomy.serverless_overflow import OverflowConfig, OverflowError

REST_ROOT = "https://rest.runpod.io/v1"
TEMPLATE_NAMES = {
    "comfyui": "Shared Overflow ComfyUI US-WA-1 20260724",
    "maskfactory": "Shared Overflow MaskFactory US-WA-1 20260724",
}
ENDPOINT_NAMES = {
    "comfyui": "shared-overflow-comfyui-us-wa-1",
    "maskfactory": "shared-overflow-maskfactory-us-wa-1",
}


def template_spec(profile: str, image_name: str) -> dict[str, Any]:
    if profile not in TEMPLATE_NAMES or not image_name:
        raise OverflowError("invalid Serverless template profile or image")
    return {
        "name": TEMPLATE_NAMES[profile],
        "imageName": image_name,
        "category": "NVIDIA",
        "containerDiskInGb": 30 if profile == "comfyui" else 40,
        "isPublic": False,
        "isServerless": True,
        "volumeInGb": 0,
        "volumeMountPath": "/runpod-volume",
        "ports": [],
        "dockerEntrypoint": [],
        "dockerStartCmd": [],
        "env": {
            "OVERFLOW_PROFILE": profile,
            "OVERFLOW_NETWORK_VOLUME_ID": "o9qv2ld91c",
        },
    }


def endpoint_spec(profile: str, template_id: str, config: OverflowConfig) -> dict[str, Any]:
    if profile not in ENDPOINT_NAMES or not template_id:
        raise OverflowError("invalid Serverless endpoint profile or template")
    return {
        "name": ENDPOINT_NAMES[profile],
        "templateId": template_id,
        "computeType": "GPU",
        "gpuCount": 1,
        "gpuTypeIds": [
            "NVIDIA RTX 6000 Ada Generation",
            "NVIDIA RTX PRO 6000 Blackwell Server Edition",
        ],
        "dataCenterIds": [config.datacenter_id],
        "networkVolumeId": config.network_volume_id,
        "workersMin": 0,
        "workersMax": 1,
        "idleTimeout": config.idle_timeout_seconds,
        "executionTimeoutMs": config.execution_timeout_seconds * 1000,
        "scalerType": "REQUEST_COUNT",
        "scalerValue": 1,
        "flashboot": True,
        "allowedCudaVersions": [
            "12.4",
            "12.5",
            "12.6",
            "12.7",
            "12.8",
            "12.9",
            "13.0",
        ],
    }


@dataclass
class RunPodRestClient:
    api_key: str
    timeout_seconds: float = 30

    def _request(self, method: str, path: str, document: Mapping[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise OverflowError("RUNPOD_API_KEY is required")
        body = None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if document is not None:
            body = json.dumps(document, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{REST_ROOT}/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OverflowError(f"RunPod REST HTTP {exc.code}: {detail[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise OverflowError(f"RunPod REST request failed: {exc.reason}") from exc
        return json.loads(payload.decode("utf-8")) if payload else {}

    def list_templates(self) -> list[dict[str, Any]]:
        result = self._request("GET", "templates")
        if not isinstance(result, list):
            raise OverflowError("RunPod template list response is invalid")
        return result

    def list_endpoints(self) -> list[dict[str, Any]]:
        result = self._request("GET", "endpoints")
        if not isinstance(result, list):
            raise OverflowError("RunPod endpoint list response is invalid")
        return result

    def create_template(self, document: Mapping[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "templates", document)
        if not isinstance(result, dict) or not result.get("id"):
            raise OverflowError("RunPod template creation response is invalid")
        return result

    def create_endpoint(self, document: Mapping[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "endpoints", document)
        if not isinstance(result, dict) or not result.get("id"):
            raise OverflowError("RunPod endpoint creation response is invalid")
        return result


def provision(
    client: RunPodRestClient,
    config: OverflowConfig,
    images: Mapping[str, str],
) -> dict[str, Any]:
    """Create missing resources; reject same-name drift instead of replacing it."""

    templates = {row.get("name"): row for row in client.list_templates()}
    template_results: dict[str, dict[str, Any]] = {}
    for profile in ("comfyui", "maskfactory"):
        expected = template_spec(profile, images[profile])
        existing = templates.get(expected["name"])
        if existing is not None:
            if existing.get("imageName") != expected["imageName"]:
                raise OverflowError(f"existing template image drift: {profile}")
            template_results[profile] = existing
        else:
            template_results[profile] = client.create_template(expected)

    endpoints = {row.get("name"): row for row in client.list_endpoints()}
    endpoint_results: dict[str, dict[str, Any]] = {}
    for profile in ("comfyui", "maskfactory"):
        expected = endpoint_spec(profile, template_results[profile]["id"], config)
        existing = endpoints.get(expected["name"])
        if existing is not None:
            drift_fields = (
                "templateId",
                "networkVolumeId",
                "workersMin",
                "workersMax",
                "idleTimeout",
                "executionTimeoutMs",
                "gpuTypeIds",
            )
            drift = [field for field in drift_fields if existing.get(field) != expected.get(field)]
            if drift:
                raise OverflowError(f"existing endpoint drift ({profile}): {drift}")
            endpoint_results[profile] = existing
        else:
            endpoint_results[profile] = client.create_endpoint(expected)
    return {
        "schema_version": "maskfactory.runpod_serverless_overflow_deployment.v1",
        "network_volume_id": config.network_volume_id,
        "datacenter_id": config.datacenter_id,
        "templates": {
            profile: {
                "id": row["id"],
                "name": row["name"],
                "imageName": row["imageName"],
            }
            for profile, row in template_results.items()
        },
        "endpoints": {
            profile: {
                "id": row["id"],
                "name": row["name"],
                "templateId": row.get("templateId"),
            }
            for profile, row in endpoint_results.items()
        },
    }
