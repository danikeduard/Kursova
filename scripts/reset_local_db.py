"""Delete and recreate the local SQLite database."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT_SQLITE_URI, INSTANCE_DIR
from scripts.init_app_db import main as upgrade_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="confirm deleting the local database")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URI)
    if not database_url.startswith("sqlite"):
        raise SystemExit("Refusing to reset a non-SQLite database.")
    if not args.yes:
        raise SystemExit("Pass --yes to delete the local database.")
    INSTANCE_DIR.mkdir(exist_ok=True)
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    for path in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        if path.exists():
            path.unlink()
    upgrade_database()


if __name__ == "__main__":
    main()
