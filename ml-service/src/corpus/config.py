"""Environment config loader.

Reads MONGODB_URI from ml-service/.env (if present), falling back to the
local default URI used by the rest of the project.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)

MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/battouta_db")
