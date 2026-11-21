"""Apply the checked-in Alembic schema to the configured database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    app = create_app()
    with app.app_context():
        upgrade()
        seed_demo_users()
    print("LinguaPath database migrations are up to date.")


if __name__ == "__main__":
    main()
