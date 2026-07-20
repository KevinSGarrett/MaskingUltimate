"""Append-only OPS_LOG entry for gold-volume compose RO overlay seal."""

ENTRY = """
## 2026-07-20 14:55 UTC - Gold-volume tournament RO compose overlay + fixed path map sealed
**Item:** multi_provider_gpu_tournament_toward_autonomous_gold (path-map + RO container mounts)
**Command:** `python -m pytest tests/test_gold_volume_sources.py tests/test_gold_volume_tournament_inputs.py -q`; `python runtime_artifacts/_seal_gold_volume_tournament_path_map_20260720.py`
**Result:** PATH_MAP_SEALED. Complements the read-when-present selector (`configs/gold_volume_sources.yaml` / `gold_volume_sources.py`, evidence `gold_volume_path_map_20260720T1448Z.json`) with:

- Fixed RO tournament input map: `configs/gold_volume_tournament_inputs.yaml` + `src/maskfactory/autonomy/gold_volume_paths.py`
- Docker RO overlay: `docker/compose.gold-volumes.yml` mounting `/gold/maskedwarehouse`, `/gold/reference`, `/gold/daz` (`:ro`) for train/serve via `docker compose -f docker/compose.gpu.yml -f docker/compose.gold-volumes.yml ...`

Paths found (F: USB up): MaskedWarehouse=`C:\\Comfy_UI_Main\\MaskedWarehouse`; reference=`F:\\Reference_Images` (Ultimate DB present); DAZ=`F:\\DAZ` (root_uuid 6bd1b3ba...). No tournament executed; no gold/champions claimed; no critical-runtime junction onto USB.

Evidence: qa/live_verification/gold_volume_tournament_path_map_20260720.json; prior sibling map qa/live_verification/gold_volume_path_map_20260720T1448Z.json
"""

with open("Plan/OPS_LOG.md", "a", encoding="utf-8", newline="\n") as handle:
    handle.write(ENTRY)
print("APPENDED", len(ENTRY), "chars")
