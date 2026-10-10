"""Các trang HTML của website."""

import re

from flask import (Blueprint, Response, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .extensions import db, limiter
from .models import ContactMessage, Favorite, Subscriber

bp = Blueprint("main", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTACT_TOPICS = ["Góp ý website", "Báo lỗi nhận dạng", "Đề xuất thêm món ăn", "Hợp tác", "Khác"]


def catalog():
    return current_app.extensions["catalog"]


def articles():
    return current_app.extensions["articles"]


def all_foods_or_503():
    foods = catalog().all()
    if len(foods) < 2:
        abort(503, description="Thư viện món ăn chưa có dữ liệu. Hãy chạy lệnh: flask --app app setup-db")
    return foods


def favorite_ids() -> set[int]:
    if not current_user.is_authenticated:
        return set()
    return set(db.session.scalars(select(Favorite.food_id).where(Favorite.user_id == current_user.id)))


def user_profile_data():
    """Hồ sơ và mục tiêu của người dùng đã đăng nhập, để điền sẵn vào giao diện."""
    if not current_user.is_authenticated or current_user.profile is None:
        return None
    p = current_user.profile
    return {"body": p.body_dict(), "target": p.target_dict()}


@bp.route("/")
def index():
    return render_template(
        "index.html",
        featured=catalog().featured(6),
        hero=catalog().get("pho") or next(iter(catalog().featured(1)), None),
        latest_articles=articles().latest(3),
        categories=catalog().categories(),
    )


@bp.route("/mon-an")
def foods():
    from .catalog import SORTS
    q = request.args.get("q", "").strip()[:80]
    category = request.args.get("danh-muc", "")
    sort = request.args.get("sap-xep", "ten")
    only_fav = request.args.get("yeu-thich") == "1" and current_user.is_authenticated
    page = catalog().browse(q=q, category=category, sort=sort, page=request.args.get("trang", 1, type=int),
                            only_ids=favorite_ids() if only_fav else None)
    return render_template("foods.html", page=page, categories=catalog().categories(), query=q,
                           active_category=category, sort=sort, sorts=SORTS, only_fav=only_fav)


@bp.route("/mon-an/<slug>")
def food_detail(slug):
    food = catalog().get(slug)
    if food is None:
        abort(404, description="Không tìm thấy món ăn này.")
    return render_template("food_detail.html", food=food, related=catalog().related(food),
                           is_favorite=food.id in favorite_ids())


@bp.route("/so-sanh")
def compare():
    all_foods = all_foods_or_503()
    a = catalog().get(request.args.get("a", "pho")) or all_foods[0]
    b = catalog().get(request.args.get("b", "ramen")) or all_foods[1]
    return render_template("compare.html", foods=all_foods, a=a, b=b)


@bp.route("/nhan-dang")
def recognize():
    predictor = current_app.extensions["predictor"]
    labels = catalog().class_names
    foods = [f for f in (catalog().by_label(l) for l in labels) if f]
    return render_template("recognize.html", model_status=predictor.status,
                           foods=sorted(foods, key=lambda f: f.name_vi))


@bp.route("/cong-cu")
def calculator():
    return render_template("calculator.html", profile_data=user_profile_data())


@bp.route("/nhat-ky")
def diary():
    from .catalog import fold
    foods = sorted(catalog().all(), key=lambda f: fold(f.name_vi))
    favs = favorite_ids()
    return render_template("diary.html", foods_data=[dict(f.to_dict(), favorite=f.id in favs) for f in foods],
                           profile_data=user_profile_data())


@bp.route("/bao-cao")
@login_required
def report():
    return render_template("report.html")


@bp.route("/kien-thuc")
def article_list():
    return render_template("articles.html", articles=articles().all(),
                           categories=articles().categories())


@bp.route("/kien-thuc/<slug>")
def article_detail(slug):
    article = articles().get(slug)
    if article is None:
        abort(404, description="Không tìm thấy bài viết này.")
    more = [a for a in articles().all() if a.slug != slug][:3]
    return render_template("article_detail.html", article=article, more=more)


@bp.route("/gioi-thieu")
def about():
    return render_template("about.html")


@bp.route("/phuong-phap")
def methodology():
    return render_template("methodology.html")


@bp.route("/chinh-sach-quyen-rieng-tu")
def privacy():
    return render_template("privacy.html")


@bp.route("/lien-he", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def contact():
    form = {"name": "", "email": "", "topic": CONTACT_TOPICS[0], "body": ""}
    if current_user.is_authenticated:
        form.update(name=current_user.name, email=current_user.email)
    errors = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        if not 2 <= len(form["name"]) <= 80:
            errors["name"] = "Vui lòng nhập họ tên (2–80 ký tự)."
        if not EMAIL_RE.match(form["email"]) or len(form["email"]) > 255:
            errors["email"] = "Địa chỉ email không hợp lệ."
        if form["topic"] not in CONTACT_TOPICS:
            errors["topic"] = "Vui lòng chọn chủ đề."
        if not 10 <= len(form["body"]) <= 3000:
            errors["body"] = "Nội dung cần từ 10 đến 3.000 ký tự."
        if not errors:
            db.session.add(ContactMessage(
                user_id=current_user.id if current_user.is_authenticated else None, **form))
            db.session.commit()
            flash("Cảm ơn bạn! Chúng tôi đã nhận được tin nhắn và sẽ phản hồi sớm.", "success")
            return redirect(url_for("main.contact"))
    status = 422 if errors else 200
    return render_template("contact.html", form=form, errors=errors, topics=CONTACT_TOPICS), status


@bp.route("/dang-ky-ban-tin", methods=["POST"])
@limiter.limit("10 per hour")
def subscribe():
    email = request.form.get("email", "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 255:
        flash("Email đăng ký chưa hợp lệ.", "error")
    elif db.session.scalar(select(Subscriber.id).where(Subscriber.email == email)):
        flash("Email này đã đăng ký bản tin rồi.", "info")
    else:
        db.session.add(Subscriber(email=email))
        try:
            db.session.commit()
            flash("Đăng ký thành công! Mẹo dinh dưỡng hay sẽ sớm đến hộp thư của bạn.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Email này đã đăng ký bản tin rồi.", "info")
    target = request.form.get("next", "")
    if not target.startswith("/") or target.startswith("//"):
        target = url_for("main.index")
    return redirect(target)


@bp.route("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nSitemap: {url_for('main.sitemap', _external=True)}\n"
    return Response(body, mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    urls = [url_for(e, _external=True) for e in (
        "main.index", "main.foods", "main.recognize", "main.calculator", "main.diary",
        "main.compare", "main.article_list", "main.about", "main.contact", "main.privacy", "main.methodology")]
    urls += [url_for("main.food_detail", slug=f.slug, _external=True) for f in catalog().all()]
    urls += [url_for("main.article_detail", slug=a.slug, _external=True) for a in articles().all()]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"  <url><loc>{u}</loc></url>" for u in urls]
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")
