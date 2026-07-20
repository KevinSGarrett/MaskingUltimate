from __future__ import annotations

import re
from pathlib import Path

path = Path("Plan/OPS_LOG.md")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"(storage soft \(127\.629 GiB free\) so acquisition_pool_capacity_safe refuses new_work)."
    r".{1,6}"
    r"(acceptable_for_static_reverify=true)"
)
replacement = r"\1 — \2"
fixed, n = pattern.subn(replacement, text, count=1)
if n != 1:
    raise SystemExit(f"mojibake_fix_miss:{n}")
path.write_text(fixed, encoding="utf-8")
print("fixed", n)
