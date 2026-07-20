$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddMinutes(12)
$iter = 0
while ((Get-Date) -lt $deadline) {
    $iter++
    $ts = (Get-Date).ToString("HH:mm:ss")
    $dockerUp = $false
    $cvat = ""
    $nuclio = ""
    $sver = & docker info --format "{{.ServerVersion}}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $sver) { $dockerUp = $true }
    if ($dockerUp) {
        $cvat = (& curl.exe -s -m 6 http://localhost:8080/api/server/about) 2>$null
        $nuclio = (& docker ps --filter "name=nuclio-nuclio-pth-sam2" --format "{{.Names}} {{.Status}}") 2>$null
    }
    $cvatOk = $cvat -match "2\.24"
    $nuclioOk = $nuclio -match "healthy|Up"
    Write-Output "[$ts] iter=$iter docker=$dockerUp server=$sver cvatOk=$cvatOk nuclio='$nuclio'"
    if ($dockerUp -and $cvatOk -and $nuclioOk) {
        Write-Output "ALL_READY docker+cvat+nuclio up"
        exit 0
    }
    Start-Sleep -Seconds 40
}
Write-Output "POLL_TIMEOUT docker/cvat/nuclio not all ready within window"
exit 1
