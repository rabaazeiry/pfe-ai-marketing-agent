# scripts/seed.ps1 — run the backend DB seed
[CmdletBinding()]
param([switch]$Reset)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location (Join-Path $RepoRoot "backend")

if ($Reset) {
    Write-Host "⚠ Running npm run seed:reset (wipes users/projects/competitors)" -ForegroundColor Yellow
    npm run seed:reset
} else {
    Write-Host "▶ Running npm run seed (idempotent)" -ForegroundColor Cyan
    npm run seed
}
