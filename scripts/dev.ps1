# scripts/dev.ps1
# Launch the full PFE Marketing Agent dev stack in three separate PowerShell windows.
#
# Usage:
#   .\scripts\dev.ps1              # start all services
#   .\scripts\dev.ps1 -NoScraper   # skip Python scraper
#   .\scripts\dev.ps1 -NoFrontend  # skip frontend
#   .\scripts\dev.ps1 -NoBackend   # skip backend

[CmdletBinding()]
param(
    [switch]$NoBackend,
    [switch]$NoFrontend,
    [switch]$NoScraper
)

$ErrorActionPreference = "Stop"

# Resolve repo root (parent of scripts/)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Write-Host ">> Repo root: $RepoRoot" -ForegroundColor Cyan

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkDir,
        [string]$Command,
        [string]$Color = "White"
    )
    Write-Host ">> Starting $Title in: $WorkDir" -ForegroundColor $Color
    $psCmd = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location '$WorkDir'; $Command"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $psCmd | Out-Null
}

if (-not $NoBackend) {
    Start-ServiceWindow `
        -Title "PFE - backend :5000" `
        -WorkDir (Join-Path $RepoRoot "backend") `
        -Command "npm run dev" `
        -Color Green
}

if (-not $NoFrontend) {
    Start-ServiceWindow `
        -Title "PFE - frontend :5173" `
        -WorkDir (Join-Path $RepoRoot "frontend") `
        -Command "npm run dev" `
        -Color Magenta
}

if (-not $NoScraper) {
    $scraperDir = Join-Path $RepoRoot "backend\scraper"
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Start-ServiceWindow `
            -Title "PFE - scraper :8000" `
            -WorkDir $scraperDir `
            -Command "uv sync; uv run uvicorn scraper_service:app --reload --port 8000" `
            -Color Yellow
    } else {
        Write-Warning "uv not found on PATH -- skipping scraper. Install with: winget install astral-sh.uv"
    }
}

Write-Host ""
Write-Host "All services launched in separate windows." -ForegroundColor Green
Write-Host "  Backend  -> http://localhost:5000"
Write-Host "  Frontend -> http://localhost:5173"
Write-Host "  Scraper  -> http://localhost:8000/health"
Write-Host ""
Write-Host "Close each window to stop that service."
