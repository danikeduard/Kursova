"""Registration, login, and account lifecycle routes."""

import re

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, limiter, login_manager
from .models import SkillRating, User
from .rating import LEVELS, initial_states

auth_bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DUMMY_PASSWORD_HASH = generate_password_hash("linguapath-invalid-account-dummy-password")


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.chat"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        level = request.form.get("level", "").upper()
        if not EMAIL_RE.match(email) or len(email) > 320 or not 8 <= len(password) <= 1024 or level not in LEVELS:
            flash("Use a valid email, an 8-character password, and choose a CEFR level.", "error")
            return render_template("register.html", levels=LEVELS)
        if db.session.scalar(db.select(User).filter_by(email=email)):
            flash("If this email can be registered, you can continue with the selected level.", "info")
            return render_template("register.html", levels=LEVELS)
        user = User(email=email, self_level=level)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        for skill, state in initial_states(level).items():
            db.session.add(SkillRating(
                user_id=user.id, skill=skill, rating=state.r, display_level=level,
                variance=state.p, last_outlier_sign=state.last_outlier_sign,
            ))
        db.session.commit()
        session.clear()
        login_user(user)
        return redirect(url_for("main.chat"))
    return render_template("register.html", levels=LEVELS)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:320]
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).filter_by(email=email))
        password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
        password_matches = check_password_hash(password_hash, password[:1024])
        if user and password_matches:
            session.clear()
            login_user(user, remember=True)
            return redirect(url_for("main.chat"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))
