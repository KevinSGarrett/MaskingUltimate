param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$RuntimeRoot = Join-Path $RepositoryRoot ".tools\dvc-venv"
$Python = Join-Path $RuntimeRoot "Scripts\python.exe"
$Dvc = Join-Path $RuntimeRoot "Scripts\dvc.exe"
$UvCache = Join-Path $RepositoryRoot ".runtime_tmp\uv-cache"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to bootstrap the pinned workspace-local DVC runtime"
}
if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv $RuntimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "failed to create DVC virtual environment"
    }
}

New-Item -ItemType Directory -Force $UvCache | Out-Null
$env:UV_CACHE_DIR = $UvCache
$Requirements = @(
    "dvc==3.67.1",
    "dvc-s3==3.3.0",
    "fsspec==2026.4.0",
    "s3fs==2026.4.0"
)
uv pip install --python $Python $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "failed to install pinned DVC/S3 runtime"
}

$version = & $Dvc version
if ($LASTEXITCODE -ne 0 -or ($version -join "`n") -notmatch "s3 \(s3fs = 2026\.4\.0\)") {
    throw "DVC runtime does not report the pinned S3 backend"
}
$version
