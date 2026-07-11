$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$BackupRoot = "D:\MaskFactoryBackup"
$LogRoot = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $BackupRoot, $LogRoot | Out-Null
$Log = Join-Path $LogRoot ("nightly_backup_{0:yyyyMMdd}.log" -f (Get-Date))

function Invoke-RobocopyMirror([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy.exe $Source $Destination /MIR /COPY:DAT /DCOPY:T /R:2 /W:2 /NP /NFL /NDL *>> $Log
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE: $Source" }
}

# B5 is deliberately first: the mirror never races a live SQLite WAL database.
& python.exe (Join-Path $Root "tools\backup_state.py") `
    --source (Join-Path $Root "data\maskfactory.sqlite") `
    --destination (Join-Path $BackupRoot "state_db") --retain 7 *>> $Log
if ($LASTEXITCODE -ne 0) { throw "SQLite B5 backup failed" }

Invoke-RobocopyMirror (Join-Path $Root "data\packages") (Join-Path $BackupRoot "packages")
Invoke-RobocopyMirror (Join-Path $Root "qa") (Join-Path $BackupRoot "qa")
Invoke-RobocopyMirror (Join-Path $Root "configs") (Join-Path $BackupRoot "configs")

# The integrity sample runs through the requested WSL boundary after B5 and B1.
& wsl.exe -d Ubuntu-22.04 -- bash -lc `
    "cd /mnt/c/Comfy_UI_Main_Masking && PYTHONPATH=src python -m maskfactory.cli verify-package --root data/packages --sample 10" *>> $Log
if ($LASTEXITCODE -ne 0) { throw "nightly WSL integrity sweep failed" }
