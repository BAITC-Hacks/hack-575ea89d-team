"""Resolve configuration once, regardless of the directory used to start Python."""
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

def backend_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name) or default).expanduser()
    return path if path.is_absolute() else BACKEND_DIR / path

DATA_DIR = backend_path("NETWORK_DATA_DIR", "data")
DB_PATH = backend_path("NETWORK_STATE_DB", "data/state.sqlite3")
CORS_ORIGINS = [value.strip() for value in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if value.strip()]
