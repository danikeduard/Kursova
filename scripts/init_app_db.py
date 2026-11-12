"""Apply the checked-in Alembic schema to the configured database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask_migrate import upgrade

from app import create_app


def main() -> None:
    app = create_app()
    with app.app_context():
        upgrade()
    print("LinguaPath database migrations are up to date.")


if __name__ == "__main__":
    main()
