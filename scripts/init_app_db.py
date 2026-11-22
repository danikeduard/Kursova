"""Apply the checked-in Alembic schema to the configured database."""

import sys
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import SkillRating, User
from app.rating import initial_states


def seed_demo_users() -> None:
    """Create the documented demo accounts when they do not exist."""
    accounts = (
        ("admin", "admin", True),
        ("user", "user", False),
    )

    for login, password, is_admin in accounts:
        user = db.session.scalar(db.select(User).filter_by(email=login))
        if user is None:
            user = User(email=login, self_level="B1", is_admin=is_admin)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            for skill, state in initial_states("B1").items():
                db.session.add(SkillRating(
                    user_id=user.id,
                    skill=skill,
                    rating=state.r,
                    display_level="B1",
                    variance=state.p,
                    last_outlier_sign=state.last_outlier_sign,
                ))
        elif is_admin:
            user.is_admin = True

    db.session.commit()


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    database_url = os.environ.get("DATABASE_URL", "")
    migration_url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("MIGRATION_DATABASE_URL")

    if not migration_url and database_url:
        parsed = urlsplit(database_url)
        if parsed.scheme in {"postgresql", "postgres"} and parsed.hostname:
            direct_netloc = parsed.netloc.replace("-pooler.", ".", 1)
            if direct_netloc != parsed.netloc:
                migration_url = urlunsplit(parsed._replace(netloc=direct_netloc))

    if migration_url:
        os.environ["MIGRATION_DATABASE_URL"] = migration_url

    app = create_app()
    with app.app_context():
        upgrade()
        seed_demo_users()
    print("LinguaPath database migrations are up to date.")


if __name__ == "__main__":
    main()
