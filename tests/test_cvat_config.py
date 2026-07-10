from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_cvat_is_pinned_local_only_and_secret_free() -> None:
    config = yaml.safe_load((ROOT / "configs" / "cvat.yaml").read_text(encoding="utf-8"))

    assert config["version"] == "v2.24.0"
    assert config["git_commit"] == "9fafd98f0c0588b775db8f98648569dfa48292b5"
    assert config["host"] == "127.0.0.1"
    assert config["compose"]["public_ports"] == []
    assert config["serverless"]["deployment"] == "cpu"
    assert config["compatibility"]["traefik_image"] == "traefik:v3.6.1"
    assert config["compatibility"]["nuclio_helper_alias"] == ("gcr.io/iguazio/alpine:3.17")
    assert config["credentials"]["source"] == ".env"
    assert config["credentials"]["committed"] is False


def test_compose_override_has_local_ports_and_all_required_share_mounts() -> None:
    text = (ROOT / "configs" / "cvat-compose.maskfactory.yml").read_text(encoding="utf-8")

    assert "ports: !override" in text
    assert '"127.0.0.1:8080:8080"' in text
    assert '"127.0.0.1:8090:8090"' in text
    assert '"127.0.0.1:8070:8070"' in text
    assert "image: traefik:v3.6.1" in text
    assert "PathPrefix(`/api/`) || PathPrefix(`/static/`)" in text
    assert 'com.docker.network.bridge.host_binding_ipv4: "127.0.0.1"' in text
    assert "0.0.0.0" not in text
    assert (
        text.count(
            "${MASKFACTORY_DATA_PATH:-/mnt/c/Comfy_UI_Main_Masking/data}:/home/django/share:ro"
        )
        == 5
    )


def test_cvat_bootstrap_encodes_retired_nuclio_helper_alias() -> None:
    text = (ROOT / "tools" / "bootstrap_cvat.py").read_text(encoding="utf-8")

    assert '"alpine:3.17"' in text
    assert '"gcr.io/iguazio/alpine:3.17"' in text
    assert "MASKFACTORY_DATA_PATH" in text


def test_cvat_credential_bootstrap_is_secret_safe_and_verifies_auth() -> None:
    text = (ROOT / "tools" / "bootstrap_cvat_credentials.py").read_text(encoding="utf-8")

    assert "secrets.token_urlsafe(32)" in text
    assert '"/api/auth/login"' in text
    assert '"/api/users/self"' in text
    assert '"CVAT_TOKEN": token' in text
    assert "print(password)" not in text
    assert "print(token)" not in text
