$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$Date = Get-Date -Format "yyyy-MM-dd"
$Week = "{0}-W{1:D2}" -f [System.Globalization.ISOWeek]::GetYear((Get-Date)), [System.Globalization.ISOWeek]::GetWeekOfYear((Get-Date))
$LogRoot = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Log = Join-Path $LogRoot ("weekly_qa_{0}.log" -f $Date.Replace("-", ""))
$Command = @(
    "cd /mnt/c/Comfy_UI_Main_Masking"
    "PYTHONPATH=src python -m maskfactory.cli active-learning"
    "--failure-queue qa/failure_queue.jsonl"
    "--coverage-matrix qa/coverage_matrix.json"
    "--packages-root data/packages"
    "--output-dir qa/reports"
    "--report-date $Date"
    "--config configs/vlm.yaml"
) -join " "
& wsl.exe -d Ubuntu-22.04 -- bash -lc $Command *>> $Log
if ($LASTEXITCODE -ne 0) { throw "weekly QA mining failed" }
$AuditCommand = @(
    "cd /mnt/c/Comfy_UI_Main_Masking"
    "PYTHONPATH=src python -m maskfactory.cli autonomy build-audit-queue"
    "--lifecycle-root work/instances"
    "--period-id $Week"
    "--config configs/autonomous_masks.yaml"
    "--output qa/autonomy/audit_queues/$Week.json"
) -join " "
& wsl.exe -d Ubuntu-22.04 -- bash -lc $AuditCommand *>> $Log
if ($LASTEXITCODE -ne 0) { throw "weekly autonomy audit selection failed" }
