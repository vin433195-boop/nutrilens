"""Trang quản trị: món ăn, bài viết, tin nhắn, người dùng, thống kê nhận dạng. Chỉ dành cho vai trò admin."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_, select

from .extensions import db
from .images import ImageError, delete_image, save_image
from .models import (Article, Category, ContactMessage, DiaryEntry, Food, FoodNote, ModelLabel,
                     Recognition, Subscriber, Tag, User, utcnow)
from .seed import slugify

bp = Blueprint("admin", __name__)

PER_PAGE = 20
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
NUTRIENTS = [("calories", "Calo (kcal)", 0, 3000), ("carbohydrate", "Carbohydrate (g)", 0, 500),
             ("protein", "Protein (g)", 0, 300), ("lipid", "Chất béo (g)", 0, 300),
             ("fiber", "Chất xơ (g)", 0, 100), ("sugar", "Đường (g)", 0, 300), ("sodium", "Natri (mg)", 0, 10000)]


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403, description="Bạn không có quyền truy cập trang quản trị.")
        return view(*args, **kwargs)
    return wrapped


@bp.before_request
@admin_required
def _guard():
    """Mọi trang trong blueprint này đều yêu cầu quyền admin."""


@bp.context_processor
def _admin_globals():
    unread = db.session.scalar(select(func.count(ContactMessage.id)).where(ContactMessage.is_read.is_(False)))
    return {"unread_messages": unread or 0}


def paginate(stmt, per_page: int = PER_PAGE):
    return db.paginate(stmt, page=request.args.get("trang", 1, type=int), per_page=per_page, error_out=False)


# ════════════════════════════════════════════════════════════
#  Tổng quan
# ════════════════════════════════════════════════════════════
@bp.route("/")
def dashboard():
    week_ago = utcnow() - timedelta(days=7)
    count = lambda model, *where: db.session.scalar(select(func.count()).select_from(model).where(*where)) or 0  # noqa: E731
    total_rec = count(Recognition)
    corrected = count(Recognition, Recognition.corrected_food_id.is_not(None))
    stats = {
        "users": count(User), "users_week": count(User, User.created_at >= week_ago),
        "foods": count(Food), "foods_hidden": count(Food, Food.is_published.is_(False)),
        "articles": count(Article), "messages_unread": count(ContactMessage, ContactMessage.is_read.is_(False)),
        "subscribers": count(Subscriber), "diary_week": count(DiaryEntry, DiaryEntry.created_at >= week_ago),
        "recognitions": total_rec, "recognitions_week": count(Recognition, Recognition.created_at >= week_ago),
        "corrected": corrected,
        "correction_rate": round(corrected * 100 / total_rec) if total_rec else 0,
        "no_image": count(Food, Food.image_path.is_(None)),
    }
    latest_messages = db.session.scalars(select(ContactMessage).order_by(ContactMessage.id.desc()).limit(5)).all()
    latest_users = db.session.scalars(select(User).order_by(User.id.desc()).limit(5)).all()
    # Các cặp "AI đoán X nhưng người dùng chọn Y" gặp nhiều nhất: gợi ý dữ liệu cần huấn luyện thêm
    confusions = db.session.execute(
        select(Recognition.predicted_label, Food.name_vi, func.count().label("n"))
        .join(Food, Food.id == Recognition.corrected_food_id)
        .group_by(Recognition.predicted_label, Food.name_vi).order_by(func.count().desc()).limit(6)).all()
    return render_template("admin/dashboard.html", stats=stats, latest_messages=latest_messages,
                           latest_users=latest_users, confusions=confusions)


# ════════════════════════════════════════════════════════════
#  Món ăn
# ════════════════════════════════════════════════════════════
@bp.route("/mon-an")
def foods():
    q = request.args.get("q", "").strip()
    stmt = select(Food).order_by(Food.name_vi)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Food.name_vi.ilike(like), Food.name_en.ilike(like), Food.slug.ilike(like)))
    if request.args.get("loc") == "chua-co-anh":
        stmt = stmt.where(Food.image_path.is_(None))
    return render_template("admin/foods.html", page=paginate(stmt), q=q)


def _food_form_data(food: Food | None) -> dict:
    if food is None:
        return {"slug": "", "name_vi": "", "name_en": "", "emoji": "🍽️", "category": "", "new_category": "",
                "cuisine": "", "serving": "", "serving_grams": "", "description": "", "highlights": "", "tips": "",
                "tags": "", "is_published": True, "is_featured": False, "model_label": "",
                "image_credit": "", "image_license": "", "image_source": "", "source": "",
                **{k: "" for k, *_ in NUTRIENTS}}
    label = db.session.scalar(select(ModelLabel.label).where(ModelLabel.food_id == food.id))
    return {
        "slug": food.slug, "name_vi": food.name_vi, "name_en": food.name_en, "emoji": food.emoji,
        "category": food.category, "new_category": "", "cuisine": food.cuisine, "serving": food.serving,
        "serving_grams": food.serving_grams or "", "description": food.description,
        "highlights": "\n".join(food.highlights), "tips": "\n".join(food.tips), "tags": ", ".join(food.tags),
        "is_published": food.is_published, "is_featured": food.is_featured, "model_label": label or "",
        "image_credit": food.image_credit or "", "image_license": food.image_license or "",
        "image_source": food.image_source or "", "source": food.source or "",
        **{k: getattr(food, k) for k, *_ in NUTRIENTS},
    }


def _parse_food_form(food: Food | None) -> tuple[dict, dict]:
    f = request.form
    data = {k: f.get(k, "").strip() for k in _food_form_data(None) if k not in ("is_published", "is_featured")}
    data["is_published"] = bool(f.get("is_published"))
    data["is_featured"] = bool(f.get("is_featured"))
    errors: dict[str, str] = {}

    if not data["slug"]:
        data["slug"] = slugify(data["name_vi"]).replace("-", "_")
    if not SLUG_RE.match(data["slug"]):
        errors["slug"] = "Slug chỉ gồm chữ thường không dấu, số, gạch ngang hoặc gạch dưới (2–80 ký tự)."
    else:
        clash = db.session.scalar(select(Food.id).where(Food.slug == data["slug"]))
        if clash and (food is None or clash != food.id):
            errors["slug"] = "Slug này đã được dùng cho món khác."
    if not 2 <= len(data["name_vi"]) <= 120:
        errors["name_vi"] = "Tên tiếng Việt cần 2–120 ký tự."
    if len(data["name_en"]) > 120:
        errors["name_en"] = "Tên tiếng Anh tối đa 120 ký tự."
    if not data["category"] and not data["new_category"]:
        errors["category"] = "Chọn danh mục hoặc nhập danh mục mới."
    if not data["serving"]:
        errors["serving"] = "Nhập mô tả khẩu phần, ví dụ: 1 tô (~500 g)."
    for key, label, lo, hi in NUTRIENTS:
        try:
            v = float(data[key].replace(",", ".")) if data[key] != "" else 0.0
        except ValueError:
            errors[key] = f"{label} phải là số."
            continue
        if not lo <= v <= hi:
            errors[key] = f"{label} phải từ {lo} đến {hi}."
        data[key] = v
    if data["serving_grams"]:
        try:
            data["serving_grams"] = float(data["serving_grams"].replace(",", "."))
            if not 1 <= data["serving_grams"] <= 3000:
                raise ValueError
        except ValueError:
            errors["serving_grams"] = "Khối lượng khẩu phần phải từ 1 đến 3.000 g."
    else:
        data["serving_grams"] = None
    if data["model_label"]:
        owner = db.session.get(ModelLabel, data["model_label"])
        if owner is None:
            errors["model_label"] = "Nhãn model không tồn tại."
        elif food is None or owner.food_id != food.id:
            errors["model_label"] = "Nhãn này đang gắn với món khác."
    return data, errors


def _apply_food(food: Food, data: dict) -> None:
    cat_name = data["new_category"] or data["category"]
    category = db.session.scalar(select(Category).where(Category.name == cat_name))
    if category is None:
        category = Category(name=cat_name, slug=slugify(cat_name), position=99)
        db.session.add(category)
    for key in ("slug", "name_vi", "name_en", "cuisine", "serving", "serving_grams", "description",
                "is_published", "is_featured", "image_credit", "image_license", "image_source", "source"):
        setattr(food, key, data[key] if data[key] != "" else None if key.startswith(("image_", "source")) else data[key])
    food.emoji = data["emoji"] or "🍽️"
    food.name_en = data["name_en"] or data["name_vi"]
    food.cuisine = data["cuisine"] or "Quốc tế"
    for key, *_ in NUTRIENTS:
        setattr(food, key, data[key])
    food.category_ref = category
    food.notes = (
        [FoodNote(kind="highlight", text=t[:255], position=i)
         for i, t in enumerate(x.strip() for x in data["highlights"].splitlines() if x.strip())]
        + [FoodNote(kind="tip", text=t[:255], position=i)
           for i, t in enumerate(x.strip() for x in data["tips"].splitlines() if x.strip())]
    )
    tags = []
    for name in dict.fromkeys(t.strip().lower() for t in data["tags"].split(",") if t.strip()):
        tag = db.session.scalar(select(Tag).where(Tag.name == name[:60])) or Tag(name=name[:60])
        tags.append(tag)
    food.tag_objs = tags


def _handle_image_upload(food: Food) -> str | None:
    file = request.files.get("image")
    if request.form.get("remove_image"):
        delete_image(food.image_path)
        food.image_path = food.image_credit = food.image_license = food.image_source = None
    if not file or not file.filename:
        return None
    try:
        new_path = save_image(file.read(), "uploads/foods", food.slug)
    except ImageError as exc:
        return str(exc)
    delete_image(food.image_path)
    food.image_path = new_path
    return None


def _render_food_form(food, data, errors, status=200):
    categories = db.session.scalars(select(Category.name).order_by(Category.position, Category.name)).all()
    used = select(ModelLabel.label).where(ModelLabel.food_id != (food.id if food else -1))
    labels = [l for l in current_app.extensions["catalog"].class_names if l not in set(db.session.scalars(used))]
    return render_template("admin/food_form.html", food=food, form=data, errors=errors,
                           categories=categories, labels=labels, nutrients=NUTRIENTS), status


@bp.route("/mon-an/them", methods=["GET", "POST"])
def food_new():
    if request.method == "GET":
        return _render_food_form(None, _food_form_data(None), {})
    data, errors = _parse_food_form(None)
    if errors:
        return _render_food_form(None, data, errors, 422)
    food = Food()
    with db.session.no_autoflush:
        _apply_food(food, data)
        img_err = _handle_image_upload(food)
    if img_err:
        errors["image"] = img_err
        db.session.rollback()
        return _render_food_form(None, data, errors, 422)
    db.session.add(food)
    db.session.flush()
    _set_model_label(food, data["model_label"])
    db.session.commit()
    flash(f"Đã thêm món {food.name_vi}.", "success")
    return redirect(url_for("admin.food_edit", food_id=food.id))


@bp.route("/mon-an/<int:food_id>", methods=["GET", "POST"])
def food_edit(food_id):
    food = db.session.get(Food, food_id) or abort(404)
    if request.method == "GET":
        return _render_food_form(food, _food_form_data(food), {})
    data, errors = _parse_food_form(food)
    if errors:
        return _render_food_form(food, data, errors, 422)
    with db.session.no_autoflush:
        _apply_food(food, data)
        img_err = _handle_image_upload(food)
    if img_err:
        db.session.rollback()
        errors["image"] = img_err
        return _render_food_form(food, data, errors, 422)
    _set_model_label(food, data["model_label"])
    db.session.commit()
    flash(f"Đã lưu thay đổi cho {food.name_vi}.", "success")
    return redirect(url_for("admin.food_edit", food_id=food.id))


def _set_model_label(food: Food, label: str) -> None:
    current = db.session.scalars(select(ModelLabel).where(ModelLabel.food_id == food.id)).all()
    for m in current:
        if m.label != label:
            db.session.delete(m)
    if label and not any(m.label == label for m in current):
        db.session.add(ModelLabel(label=label, food_id=food.id))


@bp.post("/mon-an/<int:food_id>/xoa")
def food_delete(food_id):
    food = db.session.get(Food, food_id) or abort(404)
    used = db.session.scalar(select(func.count(DiaryEntry.id)).where(DiaryEntry.food_id == food.id))
    if used:
        flash(f"Không thể xóa: {used} mục nhật ký đang dùng món này. Hãy bỏ tick “Hiển thị” để ẩn món.", "error")
        return redirect(url_for("admin.food_edit", food_id=food.id))
    db.session.execute(Recognition.__table__.update().where(Recognition.food_id == food.id).values(food_id=None))
    db.session.execute(Recognition.__table__.update().where(Recognition.corrected_food_id == food.id)
                       .values(corrected_food_id=None))
    delete_image(food.image_path)
    name = food.name_vi
    db.session.delete(food)
    db.session.commit()
    flash(f"Đã xóa món {name}.", "success")
    return redirect(url_for("admin.foods"))


# ════════════════════════════════════════════════════════════
#  Bài viết
# ════════════════════════════════════════════════════════════
@bp.route("/bai-viet")
def articles():
    stmt = select(Article).order_by(Article.published_at.desc(), Article.id.desc())
    return render_template("admin/articles.html", page=paginate(stmt))


def _article_form(article: Article | None) -> dict:
    if article is None:
        return {"title": "", "slug": "", "excerpt": "", "category": "Kiến thức", "emoji": "📘", "body_md": "",
                "read_time": "", "published_at": date.today().isoformat(), "is_published": True, "cover_credit": ""}
    return {"title": article.title, "slug": article.slug, "excerpt": article.excerpt, "category": article.category,
            "emoji": article.emoji, "body_md": article.body_md, "read_time": article.read_time,
            "published_at": article.published_at.isoformat(), "is_published": article.is_published,
            "cover_credit": article.cover_credit or ""}


@bp.route("/bai-viet/them", methods=["GET", "POST"], defaults={"article_id": None})
@bp.route("/bai-viet/<int:article_id>", methods=["GET", "POST"])
def article_edit(article_id):
    article = db.session.get(Article, article_id) if article_id else None
    if article_id and article is None:
        abort(404)
    if request.method == "GET":
        return render_template("admin/article_form.html", article=article, form=_article_form(article), errors={})

    f = request.form
    data = {k: f.get(k, "").strip() for k in _article_form(None) if k != "is_published"}
    data["body_md"] = f.get("body_md", "")
    data["is_published"] = bool(f.get("is_published"))
    errors = {}
    data["slug"] = data["slug"] or slugify(data["title"])
    if not 5 <= len(data["title"]) <= 255:
        errors["title"] = "Tiêu đề cần 5–255 ký tự."
    if not SLUG_RE.match(data["slug"]):
        errors["slug"] = "Slug chỉ gồm chữ thường không dấu, số và gạch ngang."
    else:
        clash = db.session.scalar(select(Article.id).where(Article.slug == data["slug"]))
        if clash and (article is None or clash != article.id):
            errors["slug"] = "Slug này đã được dùng."
    if len(data["excerpt"]) > 500:
        errors["excerpt"] = "Tóm tắt tối đa 500 ký tự."
    if len(data["body_md"].strip()) < 20:
        errors["body_md"] = "Nội dung quá ngắn."
    try:
        published = date.fromisoformat(data["published_at"])
    except ValueError:
        errors["published_at"] = "Ngày không hợp lệ."
    if errors:
        return render_template("admin/article_form.html", article=article, form=data, errors=errors), 422

    if article is None:
        article = Article()
        db.session.add(article)
    words = len(re.findall(r"\w+", data["body_md"]))
    article.title, article.slug, article.excerpt = data["title"], data["slug"], data["excerpt"]
    article.category = data["category"] or "Kiến thức"
    article.emoji = data["emoji"] or "📘"
    article.body_md = data["body_md"]
    article.read_time = int(data["read_time"]) if str(data["read_time"]).isdigit() else max(1, round(words / 200))
    article.published_at = published
    article.is_published = data["is_published"]
    article.cover_credit = data["cover_credit"] or None

    file = request.files.get("cover")
    if f.get("remove_cover"):
        delete_image(article.cover_image)
        article.cover_image = None
    if file and file.filename:
        try:
            new_path = save_image(file.read(), "uploads/articles", article.slug)
        except ImageError as exc:
            db.session.rollback()
            return render_template("admin/article_form.html", article=article, form=data,
                                   errors={"cover": str(exc)}), 422
        delete_image(article.cover_image)
        article.cover_image = new_path
    db.session.commit()
    flash("Đã lưu bài viết.", "success")
    return redirect(url_for("admin.article_edit", article_id=article.id))


@bp.post("/bai-viet/<int:article_id>/xoa")
def article_delete(article_id):
    article = db.session.get(Article, article_id) or abort(404)
    delete_image(article.cover_image)
    db.session.delete(article)
    db.session.commit()
    flash("Đã xóa bài viết.", "success")
    return redirect(url_for("admin.articles"))


# ════════════════════════════════════════════════════════════
#  Tin nhắn liên hệ
# ════════════════════════════════════════════════════════════
@bp.route("/tin-nhan")
def messages():
    stmt = select(ContactMessage).order_by(ContactMessage.is_read, ContactMessage.id.desc())
    if request.args.get("loc") == "chua-doc":
        stmt = stmt.where(ContactMessage.is_read.is_(False))
    return render_template("admin/messages.html", page=paginate(stmt))


@bp.route("/tin-nhan/<int:msg_id>")
def message_view(msg_id):
    msg = db.session.get(ContactMessage, msg_id) or abort(404)
    if not msg.is_read:
        msg.is_read = True
        db.session.commit()
    return render_template("admin/message_view.html", msg=msg)


@bp.post("/tin-nhan/<int:msg_id>/xoa")
def message_delete(msg_id):
    msg = db.session.get(ContactMessage, msg_id) or abort(404)
    db.session.delete(msg)
    db.session.commit()
    flash("Đã xóa tin nhắn.", "success")
    return redirect(url_for("admin.messages"))


# ════════════════════════════════════════════════════════════
#  Người dùng
# ════════════════════════════════════════════════════════════
@bp.route("/nguoi-dung")
def users():
    q = request.args.get("q", "").strip()
    stmt = select(User).order_by(User.id.desc())
    if q:
        stmt = stmt.where(or_(User.email.ilike(f"%{q}%"), User.name.ilike(f"%{q}%")))
    page = paginate(stmt)
    ids = [u.id for u in page.items]
    counts = dict(db.session.execute(select(DiaryEntry.user_id, func.count(DiaryEntry.id))
                                     .where(DiaryEntry.user_id.in_(ids)).group_by(DiaryEntry.user_id)).all()) if ids else {}
    return render_template("admin/users.html", page=page, q=q, counts=counts)
    return render_template("admin/users.html", page=page, q=q)


@bp.post("/nguoi-dung/<int:user_id>")
def user_update(user_id):
    user = db.session.get(User, user_id) or abort(404)
    action = request.form.get("action")
    if user.id == current_user.id and action in ("deactivate", "demote"):
        flash("Bạn không thể tự khóa hoặc tự bỏ quyền quản trị của mình.", "error")
    elif action == "deactivate":
        user.active = False
        user.revoke_sessions()
        flash(f"Đã khóa tài khoản {user.email}.", "success")
    elif action == "activate":
        user.active = True
        flash(f"Đã mở khóa tài khoản {user.email}.", "success")
    elif action == "promote":
        user.role = "admin"
        flash(f"{user.email} đã có quyền quản trị.", "success")
    elif action == "demote":
        user.role = "user"
        flash(f"Đã bỏ quyền quản trị của {user.email}.", "success")
    db.session.commit()
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url) else url_for("admin.users"))


# ════════════════════════════════════════════════════════════
#  Nhận dạng: dữ liệu cải thiện model
# ════════════════════════════════════════════════════════════
@bp.route("/nhan-dang")
def recognitions():
    stmt = select(Recognition).order_by(Recognition.id.desc())
    if request.args.get("loc") == "da-sua":
        stmt = stmt.where(Recognition.corrected_food_id.is_not(None))
    accuracy = db.session.execute(
        select(Recognition.predicted_label, func.count(),
               func.sum(case((Recognition.corrected_food_id.is_(None), 1), else_=0)))
        .where(Recognition.user_id.is_not(None))
        .group_by(Recognition.predicted_label).order_by(func.count().desc()).limit(20)).all()
    return render_template("admin/recognitions.html", page=paginate(stmt), accuracy=accuracy)


@bp.route("/nhan-dang/xuat-csv")
def recognitions_csv():
    rows = db.session.scalars(select(Recognition).where(Recognition.corrected_food_id.is_not(None))
                              .order_by(Recognition.id)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "predicted_label", "confidence", "corrected_slug", "tta"])
    for r in rows:
        w.writerow([r.id, r.created_at.isoformat(), r.predicted_label, r.confidence,
                    r.corrected_food.slug if r.corrected_food else "", int(r.tta)])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=nutrilens-corrections.csv"})
