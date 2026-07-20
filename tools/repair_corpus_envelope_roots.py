"""Repair corpus envelopes whose paths are relative to a tournament subdir.

Live tournaments previously wrote ``*.corpus_record.json`` with
``machine_root=<tournament_batch>``, so ``machine_lifecycle_path`` looked like
``img_xxx/autonomy/torso.json`` and failed to resolve under production ``runs/``.

This tool rewrites envelopes in place so paths resolve under ``--machine-root``
(default: ``runs/``). Never fabricates independence / stability fields.

Usage:
  python tools/repair_corpus_envelope_roots.py [--machine-root runs] [--dry-run] \\
      --output qa/live_verification/corpus_envelope_repair_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.corpus import discover_corpus_records  # noqa: E402
from maskfactory.autonomy.emit import repair_corpus_envelopes  # noqa: E402


def _resolvable_count(machine_root: Path) -> int:
    root = Path(machine_root).resolve()
    good = 0
    for record in discover_corpus_records(root):
        life = root / str(record["machine_lifecycle_path"])
        mask = root / str(record["machine_mask_path"])
        if life.is_file() and mask.is_file():
            good += 1
    return good


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-root", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    machine_root = args.machine_root.resolve()
    before = _resolvable_count(machine_root)
    result = repair_corpus_envelopes(machine_root, dry_run=args.dry_run)
    after = before if args.dry_run else _resolvable_count(machine_root)
    evidence = {
        "artifact_type": "corpus_envelope_root_repair",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "machine_root": str(machine_root),
        "before_resolvable_envelope_count": before,
        "after_resolvable_envelope_count": after,
        "repair": result,
        "claim_boundary": {
            "rewrites_path_bindings_only": True,
            "preserves_independence_stability_fields": True,
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
        },
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "before": before,
                "after": after,
                "repaired": result["repaired"],
                "failed": result["failed"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
