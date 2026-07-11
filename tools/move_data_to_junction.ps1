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

$Plan = [ordered]@{
    mode = if ($Apply) { 'apply' } else { 'rehearsal' }
    source = $Source
    target = $TargetPath
    rollback_directory = $Backup
    source_bytes = [int64]$SourceBytes
    target_volume_visible = $DriveVisible
    safeguards = @(
        'robocopy exit code must be <8',
        'source renamed only after mirror succeeds',
        'junction removed and source restored on verification failure',
        'backup directory is never automatically deleted',
        'models is not an allowed source'
    )
}
$Plan | ConvertTo-Json -Depth 4

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
