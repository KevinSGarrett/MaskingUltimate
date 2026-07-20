$ErrorActionPreference = "Stop"
$Root = "C:\Comfy_UI_Main_Masking"
$Date = Get-Date -Format "yyyy-MM-dd"
function Get-IsoWeekId([datetime]$Value) {
    # Windows PowerShell 5.1 does not expose System.Globalization.ISOWeek.
    # ISO week/year are determined by the Thursday belonging to the week.
    $Day = [int]$Value.DayOfWeek
    if ($Day -eq 0) { $Day = 7 }
    $Thursday = $Value.Date.AddDays(4 - $Day)
    $IsoYear = $Thursday.Year
    $January4 = Get-Date -Year $IsoYear -Month 1 -Day 4
    $January4Day = [int]$January4.DayOfWeek
    if ($January4Day -eq 0) { $January4Day = 7 }
    $FirstThursday = $January4.Date.AddDays(4 - $January4Day)
    $IsoWeek = 1 + [int][Math]::Floor(($Thursday - $FirstThursday).TotalDays / 7)
    return "{0}-W{1:D2}" -f $IsoYear, $IsoWeek
}
$Week = Get-IsoWeekId (Get-Date)
$LogRoot = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Log = Join-Path $LogRoot ("weekly_qa_{0}.log" -f $Date.Replace("-", ""))
$WindowsPython = (Get-Command python.exe -ErrorAction Stop).Source
$PythonDrive = $WindowsPython.Substring(0, 1).ToLowerInvariant()
$PythonTail = $WindowsPython.Substring(2).Replace("\", "/")
$WslPython = "/mnt/$PythonDrive$PythonTail"
$WslPythonSetup = "mkdir -p /tmp/maskfactory-python && ln -sf $WslPython /tmp/maskfactory-python/python && export PATH=/tmp/maskfactory-python:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
$Command = @(
    $WslPythonSetup
    "&&"
    "cd /mnt/c/Comfy_UI_Main_Masking"
    "&&"
    "PYTHONPATH=src python -m maskfactory.cli active-learning"
    "--failure-queue qa/failure_queue.jsonl"
    "--coverage-matrix qa/coverage_matrix.json"
    "--packages-root data/packages"
    "--output-dir qa/reports"
    "--report-date $Date"
    "--config configs/vlm.yaml"
) -join " "
# WSL's Windows argument bridge otherwise splits the bash -lc program into
# multiple argv entries.  Preserve it as one explicit double-quoted argument.
$QuotedCommand = '"' + $Command.Replace('"', '\"') + '"'
& wsl.exe -d Ubuntu-22.04 -- bash -lc $QuotedCommand *>> $Log
if ($LASTEXITCODE -ne 0) { throw "weekly QA mining failed" }

$AuditCommand = @(
    $WslPythonSetup
    "&&"
    "cd /mnt/c/Comfy_UI_Main_Masking"
    "&&"
    "PYTHONPATH=src python -m maskfactory.cli autonomy build-audit-queue"
    "--lifecycle-root runs"
    "--period-id $Week"
    "--config configs/autonomous_masks.yaml"
    "--output qa/autonomy/audit_queues/$Week.json"
) -join " "
$QuotedAuditCommand = '"' + $AuditCommand.Replace('"', '\"') + '"'
& wsl.exe -d Ubuntu-22.04 -- bash -lc $QuotedAuditCommand *>> $Log
if ($LASTEXITCODE -ne 0) { throw "weekly autonomy audit selection failed" }
