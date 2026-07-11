$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Nightly = "`"$PowerShell`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Root\tools\nightly_backup.ps1`""
$Weekly = "`"$PowerShell`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Root\tools\weekly_cold_copy_reminder.ps1`""

& schtasks.exe /Create /TN "MaskFactory_NightlyBackupIntegrity" /TR $Nightly /SC DAILY /ST 02:00 /RL LIMITED /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "failed to register nightly task" }
& schtasks.exe /Create /TN "MaskFactory_WeeklyColdCopyReminder" /TR $Weekly /SC WEEKLY /D MON /ST 09:00 /RL LIMITED /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "failed to register weekly task" }

& schtasks.exe /Query /TN "MaskFactory_NightlyBackupIntegrity" /FO LIST /V
& schtasks.exe /Query /TN "MaskFactory_WeeklyColdCopyReminder" /FO LIST /V
