"""Install the dependency-light MaskFactory node pack into a ComfyUI tree."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import comfy_export


def install_node_pack(
    comfy_root: Path,
    *,
    packages_root: Path,
    api_url: str = "http://127.0.0.1:8765",
) -> Path:
    """Copy the standalone node module/workflows and write its local configuration."""
    comfy_root = Path(comfy_root).resolve()
    if not comfy_root.is_dir():
        raise FileNotFoundError(f"ComfyUI root does not exist: {comfy_root}")
    if api_url != "http://127.0.0.1:8765":
        raise ValueError("MaskFactory Comfy API URL must remain localhost 127.0.0.1:8765")
    target = comfy_root / "custom_nodes" / "maskfactory_nodes"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(comfy_export.__file__), target / "__init__.py")
    source_workflows = Path(comfy_export.__file__).with_name("maskfactory_nodes") / "workflows"
    shutil.copytree(source_workflows, target / "workflows", dirs_exist_ok=True)
    config = {
        "packages_root": str(Path(packages_root).resolve()),
        "api_url": api_url,
        "format_version": "1.x-2.x",
        "supported_ontology_versions": ["body_parts_v1", "body_parts_v2"],
    }
    (target / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target
