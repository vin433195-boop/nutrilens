"""API JSON: món ăn, nhận dạng ảnh, nhật ký, hồ sơ và lịch sử nhận dạng."""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, func, select

from .extensions import db, limiter
from .models import DiaryEntry, Profile, Recognition
from .predictor import PredictorUnavailable

bp = Blueprint("api", __name__)

MIN_SERVINGS, MAX_SERVINGS = 0.25, 20
MAX_IMPORT_ENTRIES = 2000


def catalog():
    return current_app.extensions["catalog"]


def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="Dữ liệu gửi lên phải là JSON.")
    return data


def _parse_date(value, default: date | None = None) -> date:
    if value in (None, "") and default is not None:
        return default
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        abort(400, description="Ngày không hợp lệ, cần dạng YYYY-MM-DD.")
    if abs((d - date.today()).days) > 3650:
        abort(400, description="Ngày nằm ngoài phạm vi cho phép.")
    return d


def _parse_servings(value) -> float:
    try:
        s = float(value)
    except (TypeError, ValueError):
        abort(400, description="Số khẩu phần không hợp lệ.")
    if not MIN_SERVINGS <= s <= MAX_SERVINGS:
        abort(400, description=f"Số khẩu phần phải từ {MIN_SERVINGS} đến {MAX_SERVINGS}.")
    return round(s, 2)


def _parse_meal(value) -> str:
    if value not in DiaryEntry.MEALS:
        abort(400, description="Bữa ăn không hợp lệ.")
    return value


def me():
    """Đối tượng User thật phía sau proxy current_user (cần khi gán quan hệ ORM)."""
    return current_user._get_current_object()


def _profile(create: bool = False) -> Profile | None:
    profile = current_user.profile
    if profile is None and create:
        profile = Profile(user=me())
        db.session.add(profile)
    return profile


def _own_entry(entry_id: int) -> DiaryEntry:
    entry = db.session.get(DiaryEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        abort(404, description="Không tìm thấy mục nhật ký.")
    return entry


# ── Món ăn ───────────────────────────────────────────────────
@bp.get("/foods")
def list_foods():
    foods = catalog().all()
    return jsonify(foods=[f.to_dict() for f in foods], count=len(foods))


@bp.get("/foods/<slug>")
def get_food(slug):
    food = catalog().get(slug)
    if food is None:
        abort(404, description="Không tìm thấy món ăn.")
    return jsonify(food.to_dict())


@bp.get("/status")
def status():
    return jsonify(model=current_app.extensions["predictor"].status, dishes=catalog().count())


# ── Nhận dạng ────────────────────────────────────────────────
def _confidence_level(conf: float) -> tuple[str, str]:
    if conf >= 0.8:
        return "high", "Cao"
    if conf >= 0.5:
        return "medium", "Trung bình"
    return "low", "Thấp"


@bp.post("/predict")
@limiter.limit("20 per minute; 300 per day")
def predict():
    file = request.files.get("image")
    if file is None or not file.filename:
        abort(400, description="Vui lòng chọn một ảnh món ăn.")
    try:
        img = Image.open(file.stream)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        abort(400, description="File tải lên không phải ảnh hợp lệ.")
    if img.format not in current_app.config["ALLOWED_IMAGE_FORMATS"]:
        abort(400, description="Chỉ hỗ trợ ảnh JPG, PNG hoặc WEBP.")

    tta = request.form.get("tta") in ("1", "true", "on")
    predictor = current_app.extensions["predictor"]
    try:
        top = predictor.predict(img, tta=tta)
    except PredictorUnavailable as exc:
        abort(503, description=str(exc))

    predictions = []
    for label, conf in top:
        food = catalog().by_label(label)
        level, level_vi = _confidence_level(conf)
        predictions.append({"label": label, "confidence": round(conf, 4), "level": level,
                            "level_vi": level_vi, "food": food.to_dict() if food else None,
                            "_food": food})

    best = predictions[0]
    record = Recognition(user_id=current_user.id if current_user.is_authenticated else None,
                         predicted_label=best["label"], confidence=best["confidence"],
                         food=best["_food"], tta=tta)
    db.session.add(record)
    db.session.commit()
    for p in predictions:
        p.pop("_food")
    return jsonify(predictions=predictions, tta=tta, input_size=list(predictor.img_size),
                   recognition_id=record.id if current_user.is_authenticated else None)


@bp.get("/recognitions")
@login_required
def list_recognitions():
    rows = db.session.scalars(select(Recognition).where(Recognition.user_id == current_user.id)
                              .order_by(Recognition.id.desc()).limit(12))
    return jsonify(items=[r.to_dict() for r in rows])


@bp.patch("/recognitions/<int:rec_id>")
@login_required
def correct_recognition(rec_id):
    rec = db.session.get(Recognition, rec_id)
    if rec is None or rec.user_id != current_user.id:
        abort(404, description="Không tìm thấy lần nhận dạng.")
    food = catalog().get(str(_json().get("slug", "")))
    if food is None:
        abort(400, description="Món ăn không hợp lệ.")
    rec.corrected_food_id = None if rec.food_id == food.id else food.id
    db.session.commit()
    return jsonify(rec.to_dict())


@bp.delete("/recognitions/<int:rec_id>")
@login_required
def delete_recognition(rec_id):
    rec = db.session.get(Recognition, rec_id)
    if rec is None or rec.user_id != current_user.id:
        abort(404, description="Không tìm thấy lần nhận dạng.")
    db.session.delete(rec)
    db.session.commit()
    return jsonify(ok=True)


@bp.delete("/recognitions")
@login_required
def clear_recognitions():
    db.session.execute(delete(Recognition).where(Recognition.user_id == current_user.id))
    db.session.commit()
    return jsonify(ok=True)


# ── Nhật ký ──────────────────────────────────────────────────
@bp.get("/diary")
@login_required
def diary_day():
    day = _parse_date(request.args.get("date"), date.today())
    entries = db.session.scalars(select(DiaryEntry)
                                 .where(DiaryEntry.user_id == current_user.id, DiaryEntry.entry_date == day)
                                 .order_by(DiaryEntry.id))
    return jsonify(date=day.isoformat(), entries=[e.to_dict() for e in entries])


@bp.post("/diary")
@login_required
def diary_add():
    data = _json()
    food = catalog().get(str(data.get("slug", "")))
    if food is None:
        abort(400, description="Món ăn không hợp lệ.")
    entry = DiaryEntry.from_food(me(), food, _parse_date(data.get("date"), date.today()),
                                 _parse_meal(data.get("meal")), _parse_servings(data.get("servings", 1)))
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


@bp.patch("/diary/<int:entry_id>")
@login_required
def diary_update(entry_id):
    entry = _own_entry(entry_id)
    data = _json()
    if "servings" in data:
        entry.servings = _parse_servings(data["servings"])
    if "meal" in data:
        entry.meal = _parse_meal(data["meal"])
    db.session.commit()
    return jsonify(entry.to_dict())


@bp.delete("/diary/<int:entry_id>")
@login_required
def diary_delete(entry_id):
    db.session.delete(_own_entry(entry_id))
    db.session.commit()
    return jsonify(ok=True)


@bp.delete("/diary")
@login_required
def diary_clear_day():
    day = _parse_date(request.args.get("date"))
    db.session.execute(delete(DiaryEntry).where(DiaryEntry.user_id == current_user.id,
                                                DiaryEntry.entry_date == day))
    db.session.commit()
    return jsonify(ok=True)


@bp.get("/diary/summary")
@login_required
def diary_summary():
    end = _parse_date(request.args.get("end"), date.today())
    days = max(1, min(int(request.args.get("days", 7)), 31))
    start = end - timedelta(days=days - 1)
    rows = db.session.execute(
        select(DiaryEntry.entry_date, func.sum(DiaryEntry.kcal * DiaryEntry.servings))
        .where(DiaryEntry.user_id == current_user.id, DiaryEntry.entry_date.between(start, end))
        .group_by(DiaryEntry.entry_date))
    totals = {d.isoformat() if isinstance(d, date) else str(d): float(k or 0) for d, k in rows}
    out = [{"date": (start + timedelta(days=i)).isoformat(),
            "kcal": totals.get((start + timedelta(days=i)).isoformat(), 0)} for i in range(days)]
    return jsonify(days=out)


@bp.post("/diary/import")
@login_required
def diary_import():
    """Chuyển nhật ký và mục tiêu đang lưu trên trình duyệt lên tài khoản (chạy một lần sau khi đăng nhập)."""
    data = _json()
    entries = data.get("entries") or {}
    if not isinstance(entries, dict):
        abort(400, description="Dữ liệu nhật ký không hợp lệ.")
    imported = 0
    for day_str, items in entries.items():
        if not isinstance(items, list):
            continue
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        for it in items:
            if imported >= MAX_IMPORT_ENTRIES or not isinstance(it, dict):
                break
            food = catalog().get(str(it.get("slug", "")))
            if food is None or it.get("meal") not in DiaryEntry.MEALS:
                continue
            try:
                servings = min(MAX_SERVINGS, max(MIN_SERVINGS, float(it.get("qty", 1))))
            except (TypeError, ValueError):
                continue
            db.session.add(DiaryEntry.from_food(me(), food, day, it["meal"], servings))
            imported += 1

    target = data.get("target")
    target_imported = False
    if isinstance(target, dict) and current_user.profile is None:
        _apply_target(_profile(create=True), target)
        target_imported = True
    db.session.commit()
    return jsonify(imported=imported, target=target_imported)


# ── Hồ sơ & mục tiêu ─────────────────────────────────────────
def _apply_target(profile: Profile, t: dict) -> None:
    limits = {"calories": (800, 6000), "protein": (10, 400), "carb": (0, 900), "fat": (10, 300)}
    values = {}
    for key, (lo, hi) in limits.items():
        try:
            v = int(round(float(t.get(key))))
        except (TypeError, ValueError):
            abort(400, description="Mục tiêu dinh dưỡng không hợp lệ.")
        if not lo <= v <= hi:
            abort(400, description="Mục tiêu dinh dưỡng nằm ngoài phạm vi cho phép.")
        values[key] = v
    profile.target_kcal = values["calories"]
    profile.target_protein = values["protein"]
    profile.target_carb = values["carb"]
    profile.target_fat = values["fat"]


def _apply_body(profile: Profile, b: dict) -> None:
    def num(key, lo, hi, cast=float):
        try:
            v = cast(b.get(key))
        except (TypeError, ValueError):
            return None
        return v if lo <= v <= hi else None

    profile.sex = b.get("sex") if b.get("sex") in ("male", "female") else profile.sex
    profile.age = num("age", 15, 90, int) or profile.age
    profile.height_cm = num("height", 120, 230) or profile.height_cm
    profile.weight_kg = num("weight", 30, 250) or profile.weight_kg
    profile.activity = num("activity", 1.2, 1.9) or profile.activity
    goal = num("goal", -1000, 1000, int)
    profile.goal = goal if goal is not None else profile.goal


@bp.get("/profile")
@login_required
def get_profile():
    p = _profile()
    default = {"calories": 2000, "protein": 75, "carb": 250, "fat": 67}
    return jsonify(target=p.target_dict() if p else default, body=p.body_dict() if p else None)


@bp.put("/profile")
@login_required
def put_profile():
    data = _json()
    p = _profile(create=True)
    if isinstance(data.get("target"), dict):
        _apply_target(p, data["target"])
    if isinstance(data.get("body"), dict):
        _apply_body(p, data["body"])
    db.session.commit()
    return jsonify(target=p.target_dict(), body=p.body_dict())
