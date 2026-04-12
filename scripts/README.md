# scripts/

Cross-platform dev launchers for the PFE Marketing Agent stack.

| Script        | Platform                   | What it does                                                        |
|---------------|----------------------------|---------------------------------------------------------------------|
| `dev.ps1`     | Windows (PowerShell)       | Opens 3 windows: backend · frontend · scraper                       |
| `dev.bat`     | Windows (cmd.exe)          | Same, via `start` command                                           |
| `dev.sh`      | Linux · macOS · WSL · Git-Bash | Runs all services in **one** terminal with interleaved coloured logs |
| `seed.ps1`    | Windows (PowerShell)       | Runs `npm run seed` (or `seed:reset` with `-Reset`)                 |

## Quick start

### Windows (PowerShell — recommended)
```powershell
.\scripts\dev.ps1
```
Skip specific services:
```powershell
.\scripts\dev.ps1 -NoScraper
.\scripts\dev.ps1 -NoBackend -NoFrontend
```

### Windows (cmd)
```cmd
scripts\dev.bat
```

### Linux / macOS / WSL / Git-Bash
```bash
./scripts/dev.sh
./scripts/dev.sh --no-scraper
```
Press **Ctrl+C** once to stop everything (the script traps SIGINT and kills all children).

## Requirements

- **Node.js ≥ 20** with `npm` on PATH
- **[uv](https://docs.astral.sh/uv/)** for the Python scraper (optional — scripts auto-skip it if `uv` is missing)
  ```powershell
  winget install astral-sh.uv          # Windows
  brew install uv                      # macOS
  curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux
  ```

## What gets started

| Service   | URL                                     | Tech                    |
|-----------|-----------------------------------------|-------------------------|
| Backend   | http://localhost:5000                   | Node · Express · Socket.IO |
| Frontend  | http://localhost:5173                   | Vite · React · TS       |
| Scraper   | http://localhost:8000/health            | FastAPI (via `uv run`)  |

## Notes

- `dev.sh` uses `trap` to ensure child processes die on Ctrl+C.
- `dev.ps1` / `dev.bat` spawn detached windows — close each one to stop that service individually.
- The scraper window runs `uv sync` before starting, so the first launch installs deps into `backend/scraper/.venv`.
