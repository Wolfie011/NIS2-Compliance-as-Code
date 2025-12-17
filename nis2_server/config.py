from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "server_data"

AGENTS_DIR = DATA_DIR / "agents"
AGENTS_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Publiczny URL serwera używany m.in. w /register i bootstrap.ps1
# np. PUBLIC_BASE_URL="https://nis2.example.com"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")