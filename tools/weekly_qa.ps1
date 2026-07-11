$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$Date = Get-Date -Format "yyyy-MM-dd"
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
