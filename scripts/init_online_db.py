"""Compatibility wrapper for initializing the application's schema with Alembic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.init_app_db import main as initialize_app_db

if __name__ == "__main__":
    initialize_app_db()
