"""Create a consistent backup of the local SQLite database."""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT_SQLITE_URI


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    database_url = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URI)
    if not database_url.startswith("sqlite"):
        raise SystemExit("Refusing to back up a non-SQLite database.")
    source = Path(database_url.removeprefix("sqlite:///"))
    if not source.is_absolute():
        source = Path.cwd() / source
    if not source.exists():
        raise SystemExit(f"Local database does not exist: {source}")
    backup_dir = project_root / "backups"
    backup_dir.mkdir(exist_ok=True)
    destination = backup_dir / f"linguapath-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    print(f"Created local database backup: {destination}")


if __name__ == "__main__":
    main()
