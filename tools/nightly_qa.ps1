$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$Date = Get-Date -Format "yyyy-MM-dd"
$LogRoot = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Log = Join-Path $LogRoot ("nightly_qa_{0}.log" -f $Date.Replace("-", ""))
$Command = @(
    "cd /mnt/c/Comfy_UI_Main_Masking"
    "PYTHONPATH=src python -m maskfactory.cli manifest-lint"
    "--packages-root data/packages"
    "--output qa/reports/manifest_lint_$Date.json"
    "--state qa/reports/manifest_lint_state.json"
    "--config configs/vlm.yaml"
) -join " "
& wsl.exe -d Ubuntu-22.04 -- bash -lc $Command *>> $Log
if ($LASTEXITCODE -ne 0) { throw "nightly P-MANIFEST sweep failed" }
