"""Đăng ký, đăng nhập, quên mật khẩu và quản lý tài khoản."""

from __future__ import annotations

import math
import re

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .extensions import db, login_manager
from .mail import mail_configured, send_mail
from .models import DiaryEntry, Recognition, User, utcnow

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERIC_LOGIN_ERROR = "Email hoặc mật khẩu không đúng."


# ── Flask-Login ──────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id)) if user_id.isdigit() else None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify(error="Vui lòng đăng nhập để dùng tính năng này.", status=401), 401
    flash("Vui lòng đăng nhập để tiếp tục.", "info")
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


# ── Tiện ích ─────────────────────────────────────────────────
def safe_next(target: str | None) -> str | None:
    """Chỉ cho phép chuyển hướng về đường dẫn nội bộ, chống open redirect."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def validate_email(email: str) -> str | None:
    if not EMAIL_RE.match(email) or len(email) > 255:
        return "Địa chỉ email không hợp lệ."
    return None


def validate_password(password: str) -> str | None:
    if len(password) < 8:
        return "Mật khẩu cần ít nhất 8 ký tự."
    if len(password) > 128:
        return "Mật khẩu tối đa 128 ký tự."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Mật khẩu cần có cả chữ và số."
    return None


def validate_name(name: str) -> str | None:
    if not 2 <= len(name) <= 80:
        return "Họ tên cần từ 2 đến 80 ký tự."
    return None


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def make_reset_token(user: User) -> str:
    # Gắn một phần mã băm mật khẩu: đổi mật khẩu xong thì link cũ tự hết hiệu lực
    return _serializer().dumps({"uid": user.id, "h": user.password_hash[-12:]})


def verify_reset_token(token: str) -> User | None:
    try:
        data = _serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE"])
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, data.get("uid"))
    if user is None or not user.active or user.password_hash[-12:] != data.get("h"):
        return None
    return user


def _start_session(user: User, remember: bool) -> None:
    # Làm mới session khi đăng nhập để chống session fixation
    session.clear()
    login_user(user, remember=remember)
    session.permanent = True


# ── Đăng ký ──────────────────────────────────────────────────
@bp.route("/dang-ky", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = {"name": "", "email": ""}
    errors: dict[str, str] = {}
    next_url = safe_next(request.values.get("next"))

    if request.method == "POST":
        form = {"name": request.form.get("name", "").strip(),
                "email": request.form.get("email", "").strip().lower()}
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        for field, err in (("name", validate_name(form["name"])),
                           ("email", validate_email(form["email"])),
                           ("password", validate_password(password))):
            if err:
                errors[field] = err
        if not errors.get("password") and password != confirm:
            errors["confirm"] = "Mật khẩu nhập lại không khớp."
        if not request.form.get("agree"):
            errors["agree"] = "Bạn cần đồng ý với chính sách quyền riêng tư để tạo tài khoản."
        if not errors.get("email") and db.session.scalar(select(User.id).where(User.email == form["email"])):
            errors["email"] = "Email này đã được đăng ký."

        if not errors:
            user = User(email=form["email"], name=form["name"])
            user.set_password(password)
            user.register_login()
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors["email"] = "Email này đã được đăng ký."
            else:
                _start_session(user, remember=False)
                flash(f"Chào mừng {user.name}! Tài khoản của bạn đã được tạo.", "success")
                return redirect(next_url or url_for("main.diary"))

    status = 422 if errors else 200
    return render_template("auth/register.html", form=form, errors=errors, next_url=next_url), status


# ── Đăng nhập / đăng xuất ───────────────────────────────────
@bp.route("/dang-nhap", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    email = ""
    error = None
    next_url = safe_next(request.values.get("next"))

    if request.method == "POST":
        cfg = current_app.config
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(User.email == email)) if email else None

        if user is not None and user.is_locked():
            minutes = math.ceil((user.locked_until - utcnow()).total_seconds() / 60)
            error = f"Tài khoản tạm khóa do đăng nhập sai nhiều lần. Vui lòng thử lại sau {minutes} phút."
        elif user is None or not user.check_password(password):
            if user is not None:
                user.register_failed_login(cfg["LOGIN_MAX_ATTEMPTS"], cfg["LOGIN_LOCK_MINUTES"])
                db.session.commit()
            error = GENERIC_LOGIN_ERROR
        elif not user.active:
            error = "Tài khoản này đã bị vô hiệu hóa."
        else:
            user.register_login()
            db.session.commit()
            _start_session(user, remember=bool(request.form.get("remember")))
            flash(f"Xin chào {user.name}!", "success")
            return redirect(next_url or url_for("main.index"))

    status = 401 if error else 200
    return render_template("auth/login.html", email=email, error=error, next_url=next_url), status


@bp.post("/dang-xuat")
def logout():
    logout_user()
    session.clear()
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("main.index"))


# ── Quên / đặt lại mật khẩu ──────────────────────────────────
@bp.route("/quen-mat-khau", methods=["GET", "POST"])
def forgot_password():
    email = ""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        error = validate_email(email)
        if not error:
            user = db.session.scalar(select(User).where(User.email == email))
            if user is not None and user.active:
                link = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
                body = (f"Xin chào {user.name},\n\n"
                        f"Bạn vừa yêu cầu đặt lại mật khẩu NutriLens. Mở link sau trong vòng 60 phút:\n\n"
                        f"{link}\n\nNếu bạn không yêu cầu, hãy bỏ qua email này.\n\nNutriLens")
                send_mail(user.email, "Đặt lại mật khẩu NutriLens", body)
                current_app.logger.info("Password reset requested for user %s", user.id)
            # Luôn trả về cùng một thông báo để không lộ email nào đã đăng ký
            msg = "Nếu email đã đăng ký, chúng tôi đã gửi link đặt lại mật khẩu. Link có hiệu lực 60 phút."
            if not mail_configured():
                msg += " (Máy chủ chưa cấu hình email: link được in ra cửa sổ dòng lệnh đang chạy website.)"
            flash(msg, "info")
            return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", email=email, error=error), 422 if error else 200


@bp.route("/dat-lai-mat-khau/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = verify_reset_token(token)
    if user is None:
        flash("Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn. Vui lòng yêu cầu link mới.", "error")
        return redirect(url_for("auth.forgot_password"))
    errors: dict[str, str] = {}
    if request.method == "POST":
        password = request.form.get("password", "")
        err = validate_password(password)
        if err:
            errors["password"] = err
        elif password != request.form.get("confirm", ""):
            errors["confirm"] = "Mật khẩu nhập lại không khớp."
        if not errors:
            user.set_password(password)
            user.failed_logins = 0
            user.locked_until = None
            db.session.commit()
            flash("Đã đặt lại mật khẩu. Hãy đăng nhập bằng mật khẩu mới.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", errors=errors, token=token), 422 if errors else 200


# ── Tài khoản ────────────────────────────────────────────────
@bp.route("/tai-khoan", methods=["GET", "POST"])
@login_required
def account():
    user: User = current_user
    errors: dict[str, str] = {}
    action = request.form.get("action") if request.method == "POST" else None

    if action == "profile":
        name = request.form.get("name", "").strip()
        err = validate_name(name)
        if err:
            errors["name"] = err
        else:
            user.name = name
            db.session.commit()
            flash("Đã cập nhật hồ sơ.", "success")
            return redirect(url_for("auth.account"))

    elif action == "password":
        current = request.form.get("current", "")
        new = request.form.get("password", "")
        if not user.check_password(current):
            errors["current"] = "Mật khẩu hiện tại không đúng."
        elif err := validate_password(new):
            errors["password"] = err
        elif new != request.form.get("confirm", ""):
            errors["confirm"] = "Mật khẩu nhập lại không khớp."
        if not errors:
            user.set_password(new)
            db.session.commit()
            _start_session(user, remember=False)
            flash("Đã đổi mật khẩu.", "success")
            return redirect(url_for("auth.account"))

    elif action == "delete":
        if not user.check_password(request.form.get("current_delete", "")):
            errors["current_delete"] = "Mật khẩu không đúng."
        elif request.form.get("confirm_text", "").strip().upper() != "XOA":
            errors["confirm_text"] = "Vui lòng gõ XOA để xác nhận."
        else:
            db.session.delete(user)
            db.session.commit()
            logout_user()
            session.clear()
            flash("Tài khoản và toàn bộ dữ liệu của bạn đã được xóa.", "info")
            return redirect(url_for("main.index"))

    stats = {
        "entries": db.session.scalar(select(func.count(DiaryEntry.id)).where(DiaryEntry.user_id == user.id)),
        "days": db.session.scalar(select(func.count(func.distinct(DiaryEntry.entry_date)))
                                  .where(DiaryEntry.user_id == user.id)),
        "recognitions": db.session.scalar(select(func.count(Recognition.id)).where(Recognition.user_id == user.id)),
    }
    status = 422 if errors else 200
    return render_template("account.html", errors=errors, stats=stats, action=action), status
