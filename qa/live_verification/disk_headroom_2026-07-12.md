# Disk headroom review — 2026-07-12

Live C: capacity is 951.65 GiB with 97.05 GiB free. Doctor correctly reports `WARN`: ingest is
not blocked (>75 GiB), but the junction move must be scheduled (<150 GiB) and the 200 GiB target
is not met.

Only C: is visible, so applying the runbook move now would have no safe destination. The
no-write rehearsal command is:

```powershell
powershell -File tools/move_data_to_junction.ps1 -Name data -Target D:\MaskFactory\data -WhatIf
```

The script allowlists only `data`, `datasets`, and `runs`; rejects targets inside the workspace;
requires target capacity plus 20 GiB; accepts only robocopy exit codes below 8; renames source
only after mirroring; rolls back if package verification, reindex, or doctor fails; excludes
`models`; and never automatically deletes the rollback directory.

Next action: attach/provision a governed fixed volume, rerun rehearsal, then use `-Apply`. Keep
the rollback directory until `verify-package --sample 25`, clean reindex, and doctor output are
reviewed.
