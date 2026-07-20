"""Honest MVC coverage: real multiprovider FP vs prove-emit synthetics."""

from __future__ import annotations

import json
from pathlib import Path

from maskfactory.autonomy.corpus import scan_lifecycle_pool

REAL_FP = "multiprovider-local-cuda-tournament-20260720-v1"
REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    feed = json.loads(
        (REPO / "qa/live_verification/tournament_sample_set_sibling_feed_latest.json").read_text(
            encoding="utf-8"
        )
    )
    sample_set = json.loads((REPO / feed["sample_set_path"]).read_text(encoding="utf-8"))
    mvc_real: set[str] = set()
    mvc_all: set[str] = set()
    by_fp: dict[str, int] = {}
    for path in (REPO / "runs").rglob("autonomy/*.json"):
        if path.name.endswith(".corpus_record.json"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("status") != "machine_verified_candidate":
            continue
        image_id = str(doc.get("image_id") or path.parent.parent.name)
        fingerprint = str(doc.get("pipeline_fingerprint") or "unknown")
        by_fp[fingerprint] = by_fp.get(fingerprint, 0) + 1
        mvc_all.add(image_id)
        if fingerprint == REAL_FP:
            mvc_real.add(image_id)
    present_real = sum(
        1 for sample in sample_set["samples"] if f"img_{sample['source_sha256'][:12]}" in mvc_real
    )
    present_any = sum(
        1 for sample in sample_set["samples"] if f"img_{sample['source_sha256'][:12]}" in mvc_all
    )
    pool = scan_lifecycle_pool(REPO / "runs")
    print(
        json.dumps(
            {
                "pool_mvc": pool["machine_verified_candidate_count"],
                "pool_envelopes": pool["corpus_record_envelopes_seen"],
                "unique_all": len(mvc_all),
                "unique_real_fp": len(mvc_real),
                "feed_covered_real": present_real,
                "feed_covered_any": present_any,
                "feed_total": len(sample_set["samples"]),
                "by_fp": by_fp,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
