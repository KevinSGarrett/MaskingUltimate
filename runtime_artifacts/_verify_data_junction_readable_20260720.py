import json
import os
import sqlite3
from pathlib import Path

root = Path(r"C:\Comfy_UI_Main_Masking")
data = root / "data"
pkgs = data / "packages"

result = {}
result["data_is_junction"] = os.path.islink(str(data)) or bool(os.path.exists(str(data)))
try:
    result["data_realpath"] = os.path.realpath(str(data))
except Exception as e:
    result["data_realpath_error"] = str(e)

pkg_dirs = sorted([p.name for p in pkgs.iterdir() if p.is_dir()]) if pkgs.exists() else []
result["package_count"] = len(pkg_dirs)
result["packages"] = pkg_dirs

# sample: confirm files readable inside first package
sample = {}
if pkg_dirs:
    first = pkgs / pkg_dirs[0]
    files = list(first.rglob("*"))
    readable = 0
    total_bytes = 0
    for f in files[:200]:
        if f.is_file():
            try:
                total_bytes += f.stat().st_size
                readable += 1
            except Exception:
                pass
    sample["package"] = pkg_dirs[0]
    sample["files_seen"] = len([f for f in files if f.is_file()])
    sample["files_stat_ok"] = readable
    sample["sample_bytes"] = total_bytes
result["sample"] = sample

# sqlite readability
dbp = data / "maskfactory.sqlite"
if dbp.exists():
    try:
        con = sqlite3.connect(str(dbp))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        result["sqlite_tables"] = tables
        counts = {}
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                counts[t] = cur.fetchone()[0]
            except Exception as e:
                counts[t] = f"err: {e}"
        result["sqlite_row_counts"] = counts
        con.close()
    except Exception as e:
        result["sqlite_error"] = str(e)

print(json.dumps(result, indent=2))
