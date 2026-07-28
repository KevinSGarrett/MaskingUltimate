"""Probe and optionally seal the gold-volume source path map (read-when-present)."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from maskfactory.autonomy.gold_volume_sources import (
    DEFAULT_CONFIG_PATH,
    probe_gold_volume_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional sealed evidence path under qa/live_verification/.",
    )
    args = parser.parse_args()

    probe = probe_gold_volume_sources(args.config)
    payload = {
        "artifact_type": "gold_volume_path_map",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "config_path": str(args.config),
        "probe": probe.to_dict(),
        "honesty_boundary": {
            "read_when_present_only": True,
            "no_junction_critical_runtime_to_usb": True,
            "data_junction_remains_on_fixed_local": True,
            "external_labels_not_treated_as_gold": True,
            "no_force_registered_champions": True,
        },
        "sibling_correction": {
            "prior_claim": (
                "MaskedWarehouse/reference/DAZ gold-volume sources not present in working tree"
            ),
            "corrected": (
                "Sources live outside the repo working tree; probe configured absolute "
                "candidates including removable F: USB when present."
            ),
        },
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["self_sha256"] = hashlib.sha256(body).hexdigest()

    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if probe.any_source_present else 1


if __name__ == "__main__":
    raise SystemExit(main())
