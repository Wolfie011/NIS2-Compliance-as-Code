from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "server_data"

AGENTS_DIR = DATA_DIR / "agents"
AGENTS_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)