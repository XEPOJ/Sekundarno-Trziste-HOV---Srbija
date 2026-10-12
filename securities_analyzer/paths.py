import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "SecuritiesAnalyzer"


def seed_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "data" / "seed.db"
    return Path(__file__).resolve().parents[1] / "data" / "seed.db"
