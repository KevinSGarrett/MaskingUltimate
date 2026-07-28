$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$Log = Join-Path $Root "logs\cold_copy_reminders.log"
$Message = "MaskFactory B2 due: connect the offline external SSD and zip D:\MaskFactoryBackup plus models\model_registry.json. Disconnect it after verification."
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
Add-Content -LiteralPath $Log -Value ("{0:o} {1}" -f (Get-Date), $Message)
& msg.exe $env:USERNAME $Message 2>$null
