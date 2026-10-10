"""Đăng ký, đăng nhập, quên mật khẩu và quản lý tài khoản."""

from __future__ import annotations

import re

import csv
import io
import json

from flask import (Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from flask_limiter.util import get_remote_address

from .extensions import db, limiter, login_manager
from .mail import mail_configured, send_template
from .models import ContactMessage, DiaryEntry, Recognition, User, utcnow

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERIC_LOGIN_ERROR = "Email hoặc mật khẩu không đúng."


# ── Flask-Login ──────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id: str):
    uid, _, version = user_id.partition(":")
    if not uid.isdigit() or not version.isdigit():
        return None
    user = db.session.get(User, int(uid))
    # Phiên cũ (trước khi đổi mật khẩu / đăng xuất mọi thiết bị) bị từ chối
    if user is None or str(user.session_version or 1) != version:
        return None
    return user


def _login_key() -> str:
    """Giới hạn theo cặp IP + email: chặn dò mật khẩu mà không khóa được tài khoản của người khác."""
    return f"{get_remote_address()}|{request.form.get('email', '').strip().lower()}"


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


def _verify_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="verify-email")


def send_verification_email(user: User) -> bool:
    token = _verify_serializer().dumps({"uid": user.id, "email": user.email})
    link = url_for("auth.verify_email", token=token, _external=True)
    return send_template(user.email, "Xác thực email NutriLens", "verify", user=user, link=link)


def _dev_mail_note() -> str:
    return "" if mail_configured() else " (Máy chủ chưa cấu hình email: link được in ra cửa sổ dòng lệnh đang chạy website.)"


def _start_session(user: User, remember: bool) -> None:
    # Làm mới session khi đăng nhập để chống session fixation
    session.clear()
    login_user(user, remember=remember)
    session.permanent = True


# ── Đăng ký ──────────────────────────────────────────────────
@bp.route("/dang-ky", methods=["GET", "POST"])
@limiter.limit("5 per hour; 20 per day", methods=["POST"])
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
                send_verification_email(user)
                flash(f"Chào mừng {user.name}! Chúng tôi đã gửi link xác thực tới {user.email}.{_dev_mail_note()}", "success")
                return redirect(next_url or url_for("main.diary"))

    status = 422 if errors else 200
    return render_template("auth/register.html", form=form, errors=errors, next_url=next_url), status


# ── Đăng nhập / đăng xuất ───────────────────────────────────
@bp.route("/dang-nhap", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
@limiter.limit("5 per 15 minutes", methods=["POST"], key_func=_login_key)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    email = ""
    error = None
    next_url = safe_next(request.values.get("next"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(User.email == email)) if email else None

        if user is None or not user.check_password(password):
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
@limiter.limit("5 per hour", methods=["POST"])
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
                send_template(user.email, "Đặt lại mật khẩu NutriLens", "reset", user=user, link=link)
                current_app.logger.info("Password reset requested for user %s", user.id)
            # Luôn trả về cùng một thông báo để không lộ email nào đã đăng ký
            flash("Nếu email đã đăng ký, chúng tôi đã gửi link đặt lại mật khẩu. Link có hiệu lực 60 phút."
                  + _dev_mail_note(), "info")
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
            user.revoke_sessions()
            db.session.commit()
            flash("Đã đặt lại mật khẩu và đăng xuất khỏi mọi thiết bị. Hãy đăng nhập bằng mật khẩu mới.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", errors=errors, token=token), 422 if errors else 200


# ── Xác thực email ───────────────────────────────────────────
@bp.route("/xac-thuc-email/<token>")
def verify_email(token):
    try:
        data = _verify_serializer().loads(token, max_age=current_app.config["EMAIL_VERIFY_MAX_AGE"])
    except SignatureExpired:
        flash("Link xác thực đã hết hạn. Hãy đăng nhập và bấm “Gửi lại email xác thực”.", "error")
        return redirect(url_for("auth.account" if current_user.is_authenticated else "auth.login"))
    except BadSignature:
        flash("Link xác thực không hợp lệ.", "error")
        return redirect(url_for("main.index"))
    user = db.session.get(User, data.get("uid"))
    if user is None or user.email != data.get("email"):
        flash("Link xác thực không hợp lệ.", "error")
        return redirect(url_for("main.index"))
    if not user.email_verified:
        user.email_verified_at = utcnow()
        db.session.commit()
    flash("Email của bạn đã được xác thực. Cảm ơn bạn!", "success")
    return redirect(url_for("auth.account" if current_user.is_authenticated else "auth.login"))


@bp.post("/tai-khoan/gui-lai-xac-thuc")
@login_required
@limiter.limit("3 per hour")
def resend_verification():
    if current_user.email_verified:
        flash("Email của bạn đã được xác thực rồi.", "info")
    else:
        send_verification_email(current_user)
        flash(f"Đã gửi lại email xác thực tới {current_user.email}.{_dev_mail_note()}", "success")
    target = safe_next(request.form.get("next"))
    return redirect(target or url_for("auth.account"))


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
            user.revoke_sessions()
            db.session.commit()
            _start_session(user, remember=False)
            flash("Đã đổi mật khẩu. Các thiết bị khác đã được đăng xuất.", "success")
            return redirect(url_for("auth.account"))

    elif action == "revoke":
        user.revoke_sessions()
        db.session.commit()
        _start_session(user, remember=False)
        flash("Đã đăng xuất khỏi mọi thiết bị khác.", "success")
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


# ── Tải về dữ liệu cá nhân (quyền của chủ thể dữ liệu theo Nghị định 13/2023/NĐ-CP) ──
@bp.route("/tai-khoan/xuat-du-lieu.json")
@login_required
def export_json():
    u: User = current_user
    p = u.profile
    data = {
        "exported_at": utcnow().isoformat() + "Z",
        "account": {"email": u.email, "name": u.name, "created_at": u.created_at.isoformat(),
                    "email_verified_at": u.email_verified_at.isoformat() if u.email_verified_at else None},
        "profile": ({"body": p.body_dict(), "target": p.target_dict()} if p else None),
        "diary": [dict(e.to_dict(), date=e.entry_date.isoformat())
                  for e in sorted(u.diary_entries, key=lambda e: (e.entry_date, e.id))],
        "weights": [w.to_dict() for w in sorted(u.weight_logs, key=lambda w: w.log_date)],
        "custom_foods": [c.to_dict() for c in u.custom_foods],
        "favorites": [f.food.slug for f in u.favorites],
        "recognitions": [r.to_dict() for r in u.recognitions],
        "contact_messages": [{"topic": m.topic, "body": m.body, "created_at": m.created_at.isoformat()}
                             for m in db.session.scalars(select(ContactMessage).where(ContactMessage.user_id == u.id))],
    }
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=nutrilens-du-lieu-cua-toi.json"})


@bp.route("/tai-khoan/nhat-ky.csv")
@login_required
def export_diary_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Ngày", "Bữa", "Món", "Khẩu phần", "Số khẩu phần", "Calo", "Protein (g)", "Carb (g)", "Chất béo (g)"])
    meals = {"breakfast": "Sáng", "lunch": "Trưa", "dinner": "Tối", "snack": "Phụ"}
    for e in sorted(current_user.diary_entries, key=lambda e: (e.entry_date, e.id)):
        d = e.to_dict()
        w.writerow([e.entry_date.isoformat(), meals.get(e.meal, e.meal), d["name"], d["serving"], e.servings,
                    round(e.kcal * e.servings), round(e.protein * e.servings, 1),
                    round(e.carb * e.servings, 1), round(e.fat * e.servings, 1)])
    # BOM để Excel mở đúng tiếng Việt
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=nutrilens-nhat-ky.csv"})
