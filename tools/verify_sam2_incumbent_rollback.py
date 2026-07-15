from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from maskfactory.doctor import check_nuclio_interactor
from maskfactory.models.registry import resolve_registered_model
from maskfactory.providers.selection import ProviderSelectionError, validate_provider_selection

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the governed SAM2.1 incumbent, OOM fallback, and SAM3.1 fail-closed gate"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "qa" / "live_verification" / "sam2_incumbent_rollback_20260715.json",
    )
    args = parser.parse_args()

    pipeline_path = ROOT / "configs" / "pipeline.yaml"
    external_path = ROOT / "configs" / "external_sources.yaml"
    registry_path = ROOT / "models" / "model_registry.json"
    pipeline_before = pipeline_path.read_bytes()
    pipeline = yaml.safe_load(pipeline_before)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = {str(entry["key"]): entry for entry in registry["models"]}

    selection = validate_provider_selection(
        pipeline,
        external_registry_path=external_path,
        model_registry_path=registry_path,
    )
    role = "interactive_segmenter"
    expected = {
        "active": "sam2_1_large",
        "oom_fallback": "sam2_1_base_plus",
        "rollback": "sam2_1_large",
        "challenger": "sam3_1",
    }
    observed = {
        "active": selection["active"].get(role),
        "oom_fallback": selection["fallbacks"].get(role, {}).get("oom_fallback"),
        "rollback": selection["rollback"].get(role),
        "challenger": selection["shadow"].get(role, (None,))[0],
    }
    if observed != expected:
        raise RuntimeError(f"interactive provider selection drifted: {observed!r}")

    checkpoint_rows: dict[str, Any] = {}
    for alias, key in (
        ("sam2_1_large", "sam2_1_hiera_large"),
        ("sam2_1_base_plus", "sam2_1_hiera_base_plus"),
    ):
        path = resolve_registered_model(key, registry_path=registry_path)
        entry = entries[key]
        checkpoint_rows[alias] = {
            "registry_key": key,
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "lifecycle_state": entry["lifecycle_state"],
            "runtime": entry["runtime"],
            "recorded_smoke_output_sha256": entry["smoke_test"]["output_sha256"],
        }

    attempted = copy.deepcopy(pipeline)
    attempted["provider_roles"][role]["active"] = "sam3_1"
    try:
        validate_provider_selection(
            attempted,
            external_registry_path=external_path,
            model_registry_path=registry_path,
        )
    except ProviderSelectionError as exc:
        switch_rejection = str(exc)
    else:
        raise RuntimeError("planned SAM3.1 unexpectedly became an active provider")

    live = check_nuclio_interactor()
    if live.status != "PASS":
        raise RuntimeError(f"live CVAT SAM2 check failed: {live.detail}")

    selection_after = validate_provider_selection(
        yaml.safe_load(pipeline_path.read_text(encoding="utf-8")),
        external_registry_path=external_path,
        model_registry_path=registry_path,
    )
    pipeline_unchanged = pipeline_path.read_bytes() == pipeline_before
    if selection_after != selection or not pipeline_unchanged:
        raise RuntimeError("incumbent continuity verification changed production selection")

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "result": "pass",
        "authority": "incumbent_continuity_only_no_sam31_promotion_authority",
        "pipeline_sha256": _sha256(pipeline_path),
        "external_registry_sha256": _sha256(external_path),
        "model_registry_sha256": _sha256(registry_path),
        "interactive_selection": {
            **observed,
            "active_lifecycle": selection["provider_states"]["sam2_1_large"],
            "oom_fallback_lifecycle": selection["provider_states"]["sam2_1_base_plus"],
            "challenger_lifecycle": selection["provider_states"]["sam3_1"],
        },
        "checkpoints": checkpoint_rows,
        "fail_closed_switch_probe": {
            "attempted_active": "sam3_1",
            "rejected": True,
            "reason": switch_rejection,
            "production_pipeline_unchanged": pipeline_unchanged,
            "selection_restored_exactly": selection_after == selection,
        },
        "live_cvat_sam2": live.as_dict(),
        "remaining_promotion_gate": {
            "tracker_item": "MF-P2-11.15",
            "satisfied": False,
            "reason": "SAM3.1 lacks the required current frozen role benchmark and promotion certificate",
        },
        "full_displaced_incumbent_rollback_claimed": False,
    }
    document["sha256"] = _canonical_sha256(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
