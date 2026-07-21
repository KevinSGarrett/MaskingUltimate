[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][ValidateSet('data', 'datasets', 'runs')][string]$Name,
    [Parameter(Mandatory = $true)][string]$Target,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Source = Join-Path $Root $Name
$TargetPath = [System.IO.Path]::GetFullPath($Target)
$Backup = Join-Path $Root ($Name + '_old_' + (Get-Date -Format 'yyyyMMddTHHmmss'))

if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    throw "source directory is missing: $Source"
}
if ($TargetPath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'junction target must be on a separate governed volume, outside the workspace'
}
$SourceBytes = (Get-ChildItem -LiteralPath $Source -File -Recurse -Force |
    Measure-Object -Property Length -Sum).Sum
if ($null -eq $SourceBytes) { $SourceBytes = 0 }
$TargetRoot = [System.IO.Path]::GetPathRoot($TargetPath)
$DriveVisible = Test-Path -LiteralPath $TargetRoot
$DriveLetter = if ($TargetRoot -and $TargetRoot.Length -ge 1) {
    $TargetRoot.Substring(0, 1).ToUpperInvariant()
} else {
    ''
}
# Host policy: F: is USB-removable Seagate. GetDriveType often lies (FIXED) for USB HDD —
# BusType=USB / policy letter is dispositive. Never junction live data/datasets/runs onto it.
$RemovablePolicyLetters = @('F')
$TargetBusType = $null
if ($DriveLetter -and $DriveVisible) {
    try {
        $TargetBusType = (
            Get-Partition -DriveLetter $DriveLetter -ErrorAction Stop |
                Get-Disk -ErrorAction Stop |
                Select-Object -ExpandProperty BusType -First 1
        )
    } catch {
        $TargetBusType = $null
    }
}
$RejectedRemovable = ($DriveLetter -in $RemovablePolicyLetters) -or ($TargetBusType -eq 'USB')

$Plan = [ordered]@{
    mode = if ($Apply) { 'apply' } else { 'rehearsal' }
    source = $Source
    target = $TargetPath
    rollback_directory = $Backup
    source_bytes = [int64]$SourceBytes
    target_volume_visible = $DriveVisible
    target_drive_letter = $DriveLetter
    target_bus_type = $TargetBusType
    rejected_removable_usb = [bool]$RejectedRemovable
    safeguards = @(
        'robocopy exit code must be <8',
        'source renamed only after mirror succeeds',
        'junction removed and source restored on verification failure',
        'backup directory is never automatically deleted',
        'models is not an allowed source',
        'target must not be removable USB (policy F: / BusType=USB)'
    )
}
$Plan | ConvertTo-Json -Depth 4

if ($RejectedRemovable) {
    throw ("refusing junction onto removable USB target ${TargetPath} " +
        "(drive=${DriveLetter}: bus=${TargetBusType}). Use a fixed local volume; " +
        "F: is cold-offload only. See Plan/DOCKER_RUNTIME_AND_SESSION_USE.md §8b.")
}

if (-not $Apply) {
    Write-Host 'REHEARSAL ONLY: no filesystem changes made.'
    return
}
if (-not $DriveVisible) { throw "target volume is unavailable: $TargetRoot" }
if (Test-Path -LiteralPath $TargetPath) { throw "target already exists: $TargetPath" }
$Drive = [System.IO.DriveInfo]::new($TargetRoot)
if ($Drive.AvailableFreeSpace -lt ($SourceBytes + 20GB)) {
    throw 'target lacks source size plus 20 GiB safety reserve'
}

New-Item -ItemType Directory -Path $TargetPath | Out-Null
& robocopy $Source $TargetPath /MIR /COPY:DAT /DCOPY:T /R:2 /W:2
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

Move-Item -LiteralPath $Source -Destination $Backup
try {
    New-Item -ItemType Junction -Path $Source -Target $TargetPath | Out-Null
    & maskfactory verify-package --root $Source --sample 25
    if ($LASTEXITCODE -ne 0) { throw 'verify-package through junction failed' }
    & maskfactory reindex --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'reindex through junction failed' }
    & maskfactory doctor
    if ($LASTEXITCODE -ne 0) { throw 'doctor after junction move failed' }
}
catch {
    if (Test-Path -LiteralPath $Source) { Remove-Item -LiteralPath $Source }
    Move-Item -LiteralPath $Backup -Destination $Source
    throw
}

Write-Host "VERIFIED. Retain rollback directory until a separately reviewed cleanup: $Backup"
