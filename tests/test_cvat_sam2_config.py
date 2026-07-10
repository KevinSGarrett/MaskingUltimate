from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = (
    ROOT
    / "integrations"
    / "cvat"
    / "serverless"
    / "pytorch"
    / "facebookresearch"
    / "sam2"
    / "nuclio"
)


def test_sam2_function_is_cpu_only_pinned_and_generic_interactor() -> None:
    config = yaml.safe_load((FUNCTION / "function.yaml").read_text(encoding="utf-8"))

    assert config["metadata"]["name"] == "pth-sam2"
    assert config["metadata"]["annotations"]["type"] == "interactor"
    assert config["metadata"]["annotations"]["version"] == 2
    assert config["spec"]["runtime"] == "python:3.10"
    assert config["spec"]["resources"]["limits"]["cpu"] == 4
    assert "nvidia.com/gpu" not in (FUNCTION / "function.yaml").read_text(encoding="utf-8")
    directives = config["spec"]["build"]["directives"]["preCopy"]
    commands = "\n".join(item["value"] for item in directives)
    assert "2b90b9f5ceec907a1c18123530e92e794ad901a4" in commands
    assert "sam2.1_hiera_base_plus.pt" in commands


def test_sam2_adapter_returns_full_binary_mask_not_sam1_embedding() -> None:
    main = (FUNCTION / "main.py").read_text(encoding="utf-8")
    handler = (FUNCTION / "model_handler.py").read_text(encoding="utf-8")

    assert 'json.dumps({"mask": mask.tolist()})' in main
    assert "get_image_embedding" not in handler
    assert "best.astype(np.uint8) * 255" in handler
    assert 'device="cpu"' in handler


def test_deploy_uses_helper_free_wsl_docker_config() -> None:
    deploy = (ROOT / "tools" / "deploy_cvat_sam2.py").read_text(encoding="utf-8")

    assert "DOCKER_CONFIG=/tmp/maskfactory-docker-config" in deploy
    assert '"nuctl deploy --project-name cvat "' in deploy
    assert "CVAT_FUNCTIONS_REDIS_HOST=cvat_redis_ondisk" in deploy
    assert "cvat_cvat" in deploy
    assert "docker-localonly-bin" in deploy

    docker_wrapper = (ROOT / "tools" / "docker-localonly-bin" / "docker").read_text(
        encoding="utf-8"
    )
    assert '"127.0.0.1::8080"' in docker_wrapper
    assert 'exec /usr/bin/docker "${args[@]}"' in docker_wrapper


def test_smoke_invokes_sam2_through_cvat_and_checks_binary_mask() -> None:
    smoke = (ROOT / "tools" / "smoke_cvat_sam2.py").read_text(encoding="utf-8")

    assert '"/api/lambda/functions/pth-sam2"' in smoke
    assert '"binary_0_255"' in smoke
    assert '"positive_point_foreground"' in smoke
    assert '"negative_point_background"' in smoke
    assert "CVAT_TOKEN" in smoke
    assert "print(token)" not in smoke
