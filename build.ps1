<#
.SYNOPSIS
    Builds (and optionally pushes) the Portcullis Docker images.

.DESCRIPTION
    Builds two images:
      <registry>/portcullis:<tag>            — FastAPI backend (repo root Dockerfile)
      <registry>/portcullis-frontend:<tag>   — Streamlit UI (frontend/Dockerfile)

    Each image is also tagged 'latest' when a non-latest tag is given.

.PARAMETER Tag
    Image tag. Defaults to the version in src/main.py.

.PARAMETER Registry
    Docker Hub namespace / registry prefix. Default: simplitics1

.PARAMETER Service
    Which image(s) to build: all (default), api, frontend

.PARAMETER Push
    Push the built tags to the registry after a successful build.

.PARAMETER NoCache
    Build without using the layer cache.

.EXAMPLE
    ./build.ps1                       # build both, tag from src/main.py + latest
    ./build.ps1 -Tag 3.2.0 -Push      # build and push
    ./build.ps1 -Service frontend     # frontend only
#>
[CmdletBinding()]
param(
    [string]$Tag,
    [string]$Registry = "simplitics1",
    [ValidateSet("all", "api", "frontend")]
    [string]$Service = "all",
    [switch]$Push,
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Get-ProjectVersion {
    $mainPy = Join-Path $root "src/main.py"
    if (Test-Path $mainPy) {
        $m = Select-String -Path $mainPy -Pattern 'version\s*=\s*"([^"]+)"' | Select-Object -First 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    return "latest"
}

if (-not $Tag -or $Tag -eq "") { $Tag = Get-ProjectVersion }

$tags = @($Tag)
if ($Tag -ne "latest") { $tags += "latest" }

function Invoke-Build {
    param(
        [string]$Name,
        [string]$Context,
        [string]$Dockerfile
    )

    $image = "$Registry/$Name"
    $dockerArgs = @("build", "-f", $Dockerfile)
    foreach ($t in $tags) { $dockerArgs += @("-t", "$image`:$t") }
    if ($NoCache) { $dockerArgs += "--no-cache" }
    $dockerArgs += $Context

    Write-Host "==> Building $image ($($tags -join ', '))" -ForegroundColor Cyan
    & docker @dockerArgs
    if ($LASTEXITCODE -ne 0) { throw "docker build failed for $image" }

    if ($Push) {
        foreach ($t in $tags) {
            Write-Host "==> Pushing $image`:$t" -ForegroundColor Cyan
            & docker push "$image`:$t"
            if ($LASTEXITCODE -ne 0) { throw "docker push failed for $image`:$t" }
        }
    }
}

if ($Service -in @("all", "api")) {
    Invoke-Build -Name "portcullis" -Context $root -Dockerfile (Join-Path $root "Dockerfile")
}
if ($Service -in @("all", "frontend")) {
    Invoke-Build -Name "portcullis-frontend" -Context (Join-Path $root "frontend") -Dockerfile (Join-Path $root "frontend/Dockerfile")
}

Write-Host ""
Write-Host "Done. Tags: $($tags -join ', ')" -ForegroundColor Green
if (-not $Push) {
    Write-Host "Not pushed. Re-run with -Push (after 'docker login') to publish." -ForegroundColor Yellow
}
Write-Host "Run with: `$env:IMAGE_TAG='$Tag'; docker compose up -d"
