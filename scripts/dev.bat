@echo off
REM scripts/dev.bat — launch the PFE Marketing Agent dev stack (3 windows)
REM Usage:  scripts\dev.bat

setlocal
set REPO_ROOT=%~dp0..
pushd "%REPO_ROOT%" >nul
set REPO_ROOT=%CD%
popd >nul

echo.
echo ===============================================
echo  Starting PFE Marketing Agent dev stack
echo  Repo: %REPO_ROOT%
echo ===============================================
echo.

REM Backend
start "PFE - backend :5000" cmd /k "cd /d %REPO_ROOT%\backend && npm run dev"

REM Frontend
start "PFE - frontend :5173" cmd /k "cd /d %REPO_ROOT%\frontend && npm run dev"

REM Scraper (requires uv)
where uv >nul 2>nul
if %ERRORLEVEL%==0 (
    start "PFE - scraper :8000" cmd /k "cd /d %REPO_ROOT%\backend\scraper && uv sync && uv run uvicorn scraper_service:app --reload --port 8000"
) else (
    echo [!] uv not found on PATH - scraper window skipped.
    echo     Install with:  winget install astral-sh.uv
)

echo.
echo ^> Backend  ^-^> http://localhost:5000
echo ^> Frontend ^-^> http://localhost:5173
echo ^> Scraper  ^-^> http://localhost:8000/health
echo.
echo Close each window to stop that service.
endlocal
