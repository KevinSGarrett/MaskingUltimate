"""Append OPS_LOG entry for ≥100 gold-volume tournament corpus expansion."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "Plan" / "OPS_LOG.md"

ENTRY = """
## {ts} - Tournament corpus expanded to ≥100 (image-disjoint gold volumes)
**Item:** GOLD FACTORY / tournament sample set sibling feed (MaskedWarehouse + Reference_Images + DAZ RO)
**Command:** `python runtime_artifacts/_expand_gold_volume_corpus_20260720.py --ts 20260720T1650`
**Result:** DONE. Frozen image-disjoint tournament SOURCE corpus expanded from prior 96 → **128** (≥100 target met):

- preserved_base=96 from tournament_sample_set_gold_volume_20260720T1625.json (hash-verified)
- mw_expand_added=32 (CelebA / LaPa / LV-MHP / swimsuit / body archive); daz_added=0 (only 3 DAZ RGB stills on disk; no Studio)
- counts_by_source: maskedwarehouse=62, ultimate=40, reference_library=16, characters=7, daz=3
- Sibling feed + latest pointer published for GPU siblings
- Read-only sources; no bytes copied; no F: data junction; external labels NOT gold; no interactive DAZ

Evidence: qa/live_verification/tournament_sample_set_gold_volume_20260720T1650.json (self_sha256 21ba6829...); sibling feed self_sha256 9520147d...; corpus self_sha256 c445d15b...
"""


def main() -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    text = OPS.read_text(encoding="utf-8")
    marker = "tournament_sample_set_gold_volume_20260720T1650.json"
    if marker in text:
        print("ops_log_already_has_entry")
        return
    OPS.write_text(text.rstrip() + "\n" + ENTRY.format(ts=now) + "\n", encoding="utf-8")
    print("ops_log_appended")


if __name__ == "__main__":
    main()
