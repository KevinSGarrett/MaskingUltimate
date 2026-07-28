# External Bootstrap Tracker Notes

This note explains the external bootstrap items added after the original 326-item plan.

New source file:

- `Plan\Items\09_ITEMS_P0_EXTERNAL_BOOTSTRAP.md`

New tracked item range:

- `MF-P0-09.*`: external source and dataset registry.
- `MF-P0-10.*`: Civitai workflow reference intake.
- `MF-P0-11.*`: provider probe command.
- `MF-P0-12.*`: fixture smoke run across installed external providers.
- `MF-P0-13.*`: local `C:\Comfy_UI_Main\MaskedWarehouse` source inventory, remap, QA overlay, and provenance checks.

Tracker update procedure:

```powershell
cd C:\Comfy_UI_Main_Masking\Plan\Tracker
python tracker.py rebuild
python tracker.py report
```

The added items intentionally keep external models and datasets as bootstrap components. They do not relax any gold-mask QA gates.
