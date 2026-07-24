from __future__ import annotations

from pathlib import Path

import yaml

from maskfactory.autonomy.serverless_overflow import OverflowConfig
from maskfactory.runpod_serverless_provisioning import endpoint_spec, provision, template_spec


def config(tmp_path: Path) -> OverflowConfig:
    document = yaml.safe_load(
        Path("configs/runpod_serverless_overflow.yaml").read_text(encoding="utf-8")
    )
    document["durability"]["runpod_root"] = str(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return OverflowConfig.load(path)


def test_resource_specs_are_zero_idle_single_worker_and_us_wa_only(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    template = template_spec("comfyui", "ghcr.io/example/comfy@sha256:abc")
    assert template["isServerless"] is True
    assert template["volumeMountPath"] == "/runpod-volume"
    endpoint = endpoint_spec("comfyui", "template-1", cfg)
    assert endpoint["dataCenterIds"] == ["US-WA-1"]
    assert endpoint["networkVolumeId"] == "o9qv2ld91c"
    assert endpoint["workersMin"] == 0
    assert endpoint["workersMax"] == 1
    assert endpoint["gpuCount"] == 1
    assert endpoint["gpuTypeIds"] == ["NVIDIA A40", "NVIDIA RTX A6000"]
    assert endpoint["executionTimeoutMs"] == 1_800_000


def test_provision_is_idempotent_for_exact_existing_resources(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    images = {"comfyui": "image-comfy", "maskfactory": "image-mask"}

    class Client:
        def __init__(self):
            self.templates = []
            self.endpoints = []

        def list_templates(self):
            return list(self.templates)

        def list_endpoints(self):
            return list(self.endpoints)

        def create_template(self, document):
            row = {**document, "id": f"template-{len(self.templates) + 1}"}
            self.templates.append(row)
            return row

        def create_endpoint(self, document):
            row = {**document, "id": f"endpoint-{len(self.endpoints) + 1}"}
            self.endpoints.append(row)
            return row

    client = Client()
    first = provision(client, cfg, images)
    second = provision(client, cfg, images)
    assert first == second
    assert len(client.templates) == 2
    assert len(client.endpoints) == 2
