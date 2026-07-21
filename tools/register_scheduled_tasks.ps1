$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$WScript = "$env:SystemRoot\System32\wscript.exe"
$HiddenHost = "$Root\tools\Invoke-HiddenPowerShell.vbs"

if (-not (Test-Path -LiteralPath $HiddenHost -PathType Leaf)) { throw "hidden PowerShell host missing: $HiddenHost" }

function New-HiddenPowerShellAction {
    param([Parameter(Mandatory = $true)][string]$ScriptPath)
    $tokens = @($HiddenHost, $PowerShell, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath)
    $arguments = "//B //NoLogo " + (($tokens | ForEach-Object { '"' + $_ + '"' }) -join " ")
    New-ScheduledTaskAction -Execute $WScript -Argument $arguments
}

$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$Definitions = @(
    [ordered]@{ Name = "MaskFactory_NightlyBackupIntegrity"; Script = "$Root\tools\nightly_backup.ps1"; Trigger = New-ScheduledTaskTrigger -Daily -At "02:00" },
    [ordered]@{ Name = "MaskFactory_WeeklyColdCopyReminder"; Script = "$Root\tools\weekly_cold_copy_reminder.ps1"; Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "09:00" },
    [ordered]@{ Name = "MaskFactory_NightlyManifestLint"; Script = "$Root\tools\nightly_qa.ps1"; Trigger = New-ScheduledTaskTrigger -Daily -At "03:00" },
    [ordered]@{ Name = "MaskFactory_WeeklyQaMining"; Script = "$Root\tools\weekly_qa.ps1"; Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "10:00" }
)

foreach ($Definition in $Definitions) {
    $Action = New-HiddenPowerShellAction -ScriptPath $Definition.Script
    Register-ScheduledTask -TaskName $Definition.Name -Action $Action -Trigger $Definition.Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
}

$Definitions | ForEach-Object { Get-ScheduledTask -TaskName $_.Name }
