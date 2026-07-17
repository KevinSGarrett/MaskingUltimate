[CmdletBinding()]
param(
    [Parameter()]
    [string]$Distribution = "Ubuntu-22.04",

    [Parameter()]
    [string]$RepairDistribution = "docker-desktop",

    [Parameter()]
    [string]$VhdPath = "F:\MaskFactory_Offload_20260714\WSL\Ubuntu-22.04\ext4.vhdx",

    [Parameter()]
    [string]$BackupRoot = "F:\MaskFactory_Offload_20260714\WSL_BACKUPS",

    [Parameter()]
    [switch]$StopDockerDesktop,

    [Parameter()]
    [switch]$AllowAggressiveRepair,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmRepair
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [Parameter()]
        [int[]]$AcceptedExitCodes = @(0)
    )

    $output = @(& $FilePath @ArgumentList 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -notin $AcceptedExitCodes) {
        $detail = ($output | Select-Object -Last 30) -join [Environment]::NewLine
        throw "Native command failed ($exitCode): $FilePath $($ArgumentList -join ' ')`n$detail"
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Get-WslBlockDevices {
    param([string]$Distro)

    $result = Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList @(
        "-d", $Distro, "-u", "root", "--", "/bin/lsblk", "-dnpo", "NAME"
    )
    return @(
        $result.Output |
            ForEach-Object { "$($_)".Trim() } |
            Where-Object { $_ -match "^/dev/[a-z0-9]+$" } |
            Sort-Object -Unique
    )
}

function Get-DockerProcesses {
    return @(
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -match "^(Docker Desktop|com\.docker\.|docker-agent)" }
    )
}

if (-not $ConfirmRepair) {
    throw "Repair confirmation was not supplied. No action was taken."
}
if (-not (Test-IsAdministrator)) {
    throw "Run this script from an already-elevated PowerShell. It will not self-elevate or open a UAC prompt."
}

$resolvedVhd = (Resolve-Path -LiteralPath $VhdPath).Path
$vhd = Get-Item -LiteralPath $resolvedVhd
if ($vhd.PSIsContainer -or $vhd.Extension -ne ".vhdx" -or $vhd.Length -le 0) {
    throw "The configured Ubuntu VHD is invalid: $resolvedVhd"
}

$registeredDistro = (
    Get-ChildItem -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss" |
        Where-Object { $_.GetValue("DistributionName") -eq $Distribution } |
        Select-Object -First 1
)
if (-not $registeredDistro) {
    throw "The registered WSL distribution was not found: $Distribution"
}
$registeredBase = $registeredDistro.GetValue("BasePath")
if (-not $registeredBase) {
    throw "The registered WSL distribution has no BasePath: $Distribution"
}
$registeredVhd = [IO.Path]::GetFullPath((Join-Path $registeredBase "ext4.vhdx"))
if ($registeredVhd -ne [IO.Path]::GetFullPath($resolvedVhd)) {
    throw "The configured VHD is not the registered disk for $Distribution."
}

$repairDistroPresent = @(
    & wsl.exe --list --quiet 2>$null |
        ForEach-Object { "$($_)".Replace([char]0, "").Trim() }
) -contains $RepairDistribution
if (-not $repairDistroPresent) {
    throw "The repair distribution is unavailable: $RepairDistribution"
}

$dockerWasRunning = (Get-DockerProcesses).Count -gt 0
if ($dockerWasRunning -and -not $StopDockerDesktop) {
    throw "Docker Desktop is running. Re-run with -StopDockerDesktop so it is stopped cleanly before WSL shutdown."
}
if ($dockerWasRunning -and -not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is running but docker.exe is unavailable for a controlled stop."
}

$backupDirectory = Join-Path $BackupRoot $Distribution
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$backupPath = Join-Path $backupDirectory "ext4_before_repair_$stamp.vhdx"
if (Test-Path -LiteralPath $backupPath) {
    throw "Backup destination already exists: $backupPath"
}
$backupDrive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($backupPath).Substring(0, 1))
$requiredFree = $vhd.Length + 5GB
if ($backupDrive.Free -lt $requiredFree) {
    throw "Insufficient backup capacity: free=$($backupDrive.Free) required=$requiredFree"
}

$attached = $false
$dockerStopped = $false
$repairOutput = @()
$repairExitCode = $null
$preRepairHash = $null
$postRepairHash = $null
$backupHash = $null
$unmountSucceeded = $true
$dockerRestarted = $false
$dockerRestartError = $null
$operationError = $null

try {
    try {
        if ($dockerWasRunning) {
            Invoke-CheckedNative -FilePath "docker.exe" -ArgumentList @("desktop", "stop") | Out-Null
            $dockerStopped = $true
            $deadline = [DateTime]::UtcNow.AddMinutes(2)
            while ((Get-DockerProcesses).Count -gt 0 -and [DateTime]::UtcNow -lt $deadline) {
                Start-Sleep -Seconds 2
            }
            if ((Get-DockerProcesses).Count -gt 0) {
                throw "Docker Desktop did not stop cleanly within two minutes."
            }
        }

        Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList @("--shutdown") | Out-Null
        Start-Sleep -Seconds 3

        Copy-Item -LiteralPath $resolvedVhd -Destination $backupPath
        if ((Get-Item -LiteralPath $backupPath).Length -ne $vhd.Length) {
            throw "The VHD backup size does not match the source."
        }
        $preRepairHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedVhd).Hash.ToLowerInvariant()
        $backupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupPath).Hash.ToLowerInvariant()
        if ($preRepairHash -ne $backupHash) {
            throw "The VHD backup hash does not match the stopped source disk."
        }

        $baselineDevices = Get-WslBlockDevices -Distro $RepairDistribution
        Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList @(
            "--mount", $resolvedVhd, "--vhd", "--bare"
        ) | Out-Null
        $attached = $true
        Start-Sleep -Seconds 2

        $afterDevices = Get-WslBlockDevices -Distro $RepairDistribution
        $newDevices = @($afterDevices | Where-Object { $_ -notin $baselineDevices })
        $ext4Candidates = @()
        foreach ($device in $newDevices) {
            $typeResult = Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList @(
                "-d", $RepairDistribution, "-u", "root", "--",
                "/sbin/blkid", "-o", "value", "-s", "TYPE", $device
            ) -AcceptedExitCodes @(0, 2)
            if (($typeResult.Output -join "").Trim() -eq "ext4") {
                $ext4Candidates += $device
            }
        }
        if ($ext4Candidates.Count -ne 1) {
            throw "Expected exactly one newly attached ext4 repair disk; found $($ext4Candidates.Count)."
        }
        $repairDevice = $ext4Candidates[0]
        $mountCheck = Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList @(
            "-d", $RepairDistribution, "-u", "root", "--", "/bin/findmnt", "-n", $repairDevice
        ) -AcceptedExitCodes @(0, 1)
        if ($mountCheck.ExitCode -eq 0 -and ($mountCheck.Output -join "").Trim()) {
            throw "The repair device is mounted; refusing to run e2fsck: $repairDevice"
        }

        $repairArguments = @(
            "-d", $RepairDistribution, "-u", "root", "--", "/sbin/e2fsck", "-f", "-p", $repairDevice
        )
        $repairResult = Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList $repairArguments -AcceptedExitCodes @(0, 1, 2, 4)
        $repairOutput = @($repairResult.Output)
        $repairExitCode = $repairResult.ExitCode
        if ($repairExitCode -eq 4 -and $AllowAggressiveRepair) {
            $repairArguments = @(
                "-d", $RepairDistribution, "-u", "root", "--", "/sbin/e2fsck", "-f", "-y", $repairDevice
            )
            $repairResult = Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList $repairArguments -AcceptedExitCodes @(0, 1, 2)
            $repairOutput += @($repairResult.Output)
            $repairExitCode = $repairResult.ExitCode
        }
        if ($repairExitCode -eq 4) {
            throw "Safe automatic e2fsck could not complete. The original is preserved and the verified backup is at $backupPath."
        }
    }
    finally {
        if ($attached) {
            $unmountOutput = @(& wsl.exe --unmount $resolvedVhd 2>&1)
            $unmountExitCode = $LASTEXITCODE
            if ($unmountExitCode -eq 0) {
                $attached = $false
            }
            else {
                $unmountSucceeded = $false
                Write-Warning "Exact-path WSL VHD detach failed ($unmountExitCode): $($unmountOutput -join ' ')"
            }
        }
    }

    if (-not $unmountSucceeded) {
        throw "The repaired VHD could not be detached. Docker Desktop was not restarted to avoid a disk-sharing conflict."
    }

    $postRepairHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedVhd).Hash.ToLowerInvariant()
    $rootProbe = Invoke-CheckedNative -FilePath "wsl.exe" -ArgumentList @(
        "-d", $Distribution, "-u", "root", "--", "/bin/sh", "-lc",
        "cat /proc/mounts; /usr/bin/df -h /; /usr/bin/stat -c '%F' /home/kevin/mfenvs"
    )
    if (($rootProbe.Output -join "`n") -match "(?m)^/dev/[^ ]+ / ext4 .*emergency_ro") {
        throw "Ubuntu still mounted its root filesystem with emergency_ro after repair."
    }
}
catch {
    $operationError = $_
}
finally {
    if ($dockerStopped -and $unmountSucceeded) {
        try {
            Invoke-CheckedNative -FilePath "docker.exe" -ArgumentList @("desktop", "start") | Out-Null
            $dockerRestarted = $true
        }
        catch {
            $dockerRestartError = $_.Exception.Message
            Write-Warning "Docker Desktop restart failed after the VHD was detached: $dockerRestartError"
        }
    }
}

if ($operationError) {
    throw $operationError
}
if ($dockerStopped -and -not $dockerRestarted) {
    throw "The VHD was detached, but Docker Desktop could not be restarted: $dockerRestartError"
}

$evidence = [ordered]@{
    schema_version = "1.0.0"
    captured_at = [DateTime]::UtcNow.ToString("o")
    result = "WSL_VHD_REPAIR_PASS"
    distribution = $Distribution
    repair_distribution = $RepairDistribution
    vhd_path = $resolvedVhd
    backup_path = $backupPath
    vhd_size_bytes = $vhd.Length
    pre_repair_sha256 = $preRepairHash
    backup_sha256 = $backupHash
    post_repair_sha256 = $postRepairHash
    e2fsck_exit_code = $repairExitCode
    e2fsck_output_tail = @($repairOutput | Select-Object -Last 30)
    emergency_ro_absent = $true
    docker_was_running = $dockerWasRunning
    docker_stopped_cleanly = $dockerStopped
    docker_restart_requested = $dockerRestarted
    source_backup_hash_match = ($preRepairHash -eq $backupHash)
    authority = [ordered]@{
        distribution_unregistered = $false
        vhd_moved_or_replaced = $false
        docker_vhd_repaired = $false
        mask_or_gold_authority_changed = $false
    }
}
$evidencePath = Join-Path (Split-Path -Parent $PSScriptRoot) "qa\live_verification\wsl_vhd_repair_$stamp.json"
$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $evidencePath -Encoding utf8
Write-Output ($evidence | ConvertTo-Json -Depth 8)
