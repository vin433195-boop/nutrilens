"""Nạp dữ liệu khởi tạo từ các file JSON/Markdown vào cơ sở dữ liệu.

Nguồn dữ liệu:
- nutrilens/data/foods.json: danh sách món, tên, mô tả, điểm cộng, mẹo, thẻ
- nutrilens/data/nutrition.json: dinh dưỡng tính từ USDA FoodData Central (scripts/build_nutrition.py)
- nutrilens/data/images.json: ảnh món ăn (Wikimedia Commons) kèm tác giả và giấy phép
- class_names.json: nhãn đầu ra của model AI, dùng để gắn nhãn cho món tương ứng
- nutrilens/data/articles/*.md: bài viết

Mặc định chỉ thêm bản ghi chưa có (theo slug) để không ghi đè nội dung đã sửa trên CSDL.
Dùng overwrite=True để cập nhật lại toàn bộ từ file.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from flask import current_app
from sqlalchemy import select

from .extensions import db
from .models import Article, Category, Food, FoodIngredient, FoodNote, ModelLabel, Tag
from .nutrition import CATEGORY_ORDER, pretty

FEATURED = ["pho", "com_tam", "banh_mi", "goi_cuon", "bun_cha", "sushi"]
# Ảnh bìa bài viết lấy từ ảnh món ăn liên quan
ARTICLE_COVERS = {
    "hieu-dung-ve-calo": "com_tam", "ba-nhom-chat-da-luong": "steak", "dia-an-can-bang-kieu-viet": "canh_chua_ca",
    "giam-muoi-mon-nuoc": "pho", "duong-an-trong-do-ngot": "cup_cakes", "protein-cho-nguoi-tap-luyen": "com_ga",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _load_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_category(name: str, cache: dict) -> Category:
    if name not in cache:
        cat = db.session.scalar(select(Category).where(Category.name == name))
        if cat is None:
            pos = CATEGORY_ORDER.index(name) if name in CATEGORY_ORDER else len(CATEGORY_ORDER)
            cat = Category(name=name, slug=slugify(name), position=pos)
            db.session.add(cat)
            db.session.flush()
        cache[name] = cat
    return cache[name]


def _get_tag(name: str, cache: dict) -> Tag:
    if name not in cache:
        tag = db.session.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.session.add(tag)
            db.session.flush()
        cache[name] = tag
    return cache[name]


def _load_optional(path: Path) -> dict:
    return _load_json(path) if path.exists() else {}


def seed_foods(overwrite: bool = False) -> tuple[int, int]:
    """Nạp món ăn. Món đã có chỉ được bổ sung phần còn thiếu (ảnh, thành phần) trừ khi overwrite=True."""
    cfg = current_app.config
    data_dir = Path(cfg["FOODS_PATH"]).parent
    content = _load_json(cfg["FOODS_PATH"])
    nutrition = _load_optional(data_dir / "nutrition.json")
    images = _load_optional(data_dir / "images.json")
    mapping = _load_optional(Path(cfg["MAPPING_PATH"]))
    class_names = set(_load_json(cfg["CLASSES_PATH"]))
    categories, tags = {}, {}
    created = updated = 0

    # Tắt autoflush: món mới chỉ được ghi xuống CSDL sau khi đã gán đủ danh mục, thẻ
    with db.session.no_autoflush:
        for slug, extra in content.items():
            food = db.session.scalar(select(Food).where(Food.slug == slug))
            nut = nutrition.get(slug)
            if food is not None and not overwrite:
                _fill_missing(food, nut, images.get(slug))
                if slug in class_names:
                    _ensure_label(slug, food)
                continue
            is_new = food is None
            if is_new:
                food = Food(slug=slug)  # Chỉ add vào session sau khi đã gán đủ các trường
                created += 1
            else:
                updated += 1

            food.name_vi = extra.get("name_vi", pretty(slug))
            food.name_en = extra.get("name_en", pretty(slug))
            food.emoji = extra.get("emoji", "🍽️")
            food.category_ref = _get_category(extra.get("category", "Món chính"), categories)
            food.cuisine = extra.get("cuisine", "Quốc tế")
            food.description = extra.get("description", "")
            if nut:
                _apply_nutrition(food, nut)
            else:  # Dự phòng: số liệu gốc của dự án (không rõ khẩu phần)
                m = mapping.get(slug, {})
                food.serving = extra.get("serving", "100 g")
                food.serving_grams = 100
                food.calories, food.carbohydrate = m.get("calories", 0), m.get("carbohydrate", 0)
                food.protein, food.lipid = m.get("protein", 0), m.get("lipid", 0)
                food.fiber = food.sugar = food.sodium = 0
                food.source = "Mapping_Calories.json của dự án gốc (chưa kiểm chứng)"
            _apply_image(food, images.get(slug), force=True)
            food.is_featured = slug in FEATURED
            food.notes = (
                [FoodNote(kind="highlight", text=t, position=i) for i, t in enumerate(extra.get("highlights", []))]
                + [FoodNote(kind="tip", text=t, position=i) for i, t in enumerate(extra.get("tips", []))]
            )
            food.tag_objs = [_get_tag(t, tags) for t in extra.get("tags", [])]
            if is_new:
                db.session.add(food)
            db.session.flush()
            if slug in class_names:
                _ensure_label(slug, food)

    db.session.commit()
    return created, updated


def _apply_nutrition(food: Food, nut: dict) -> None:
    n = nut["nutrition"]
    food.serving = nut["serving"]
    food.serving_grams = nut["serving_grams"]
    food.calories, food.carbohydrate, food.protein, food.lipid = (
        n["calories"], n["carbohydrate"], n["protein"], n["lipid"])
    food.fiber, food.sugar, food.sodium = n["fiber"], n["sugar"], n["sodium"]
    food.source = nut["source"]
    food.ingredients = [FoodIngredient(position=i, name=it["name"], grams=it["grams"], fdc_id=it["fdc_id"],
                                       usda_name=it["usda"][:255])
                        for i, it in enumerate(nut["ingredients"])]


def _apply_image(food: Food, img: dict | None, force: bool = False) -> None:
    if img and (force or not food.image_path):
        food.image_path = img["file"]
        food.image_credit = img.get("credit")
        food.image_license = img.get("license")
        food.image_source = img.get("source")


def _fill_missing(food: Food, nut: dict | None, img: dict | None) -> None:
    _apply_image(food, img)
    if nut and not food.ingredients:
        food.ingredients = [FoodIngredient(position=i, name=it["name"], grams=it["grams"], fdc_id=it["fdc_id"],
                                           usda_name=it["usda"][:255])
                            for i, it in enumerate(nut["ingredients"])]


def _ensure_label(label: str, food: Food) -> None:
    if db.session.get(ModelLabel, label) is None:
        db.session.add(ModelLabel(label=label, food_id=food.id))


def parse_article(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    header, _, body = raw.partition("\n---\n")
    meta = {}
    for line in header.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return {
        "slug": path.stem,
        "title": meta.get("title", path.stem),
        "excerpt": meta.get("excerpt", ""),
        "category": meta.get("category", "Kiến thức"),
        "emoji": meta.get("emoji", "📘"),
        "published_at": date.fromisoformat(meta.get("date", date.today().isoformat())),
        "read_time": int(meta.get("read_time", 3)),
        "body_md": body.strip() + "\n",
    }


def seed_articles(overwrite: bool = False) -> tuple[int, int]:
    created = updated = 0
    for path in sorted(Path(current_app.config["ARTICLES_DIR"]).glob("*.md")):
        data = parse_article(path)
        article = db.session.scalar(select(Article).where(Article.slug == data["slug"]))
        if article is not None and not overwrite:
            continue
        if article is None:
            article = Article()
            db.session.add(article)
            created += 1
        else:
            updated += 1
        for key, value in data.items():
            setattr(article, key, value)
        _apply_cover(article)
    for article in db.session.scalars(select(Article).where(Article.cover_image.is_(None))):
        _apply_cover(article)
    db.session.commit()
    return created, updated


def _apply_cover(article: Article) -> None:
    food = db.session.scalar(select(Food).where(Food.slug == ARTICLE_COVERS.get(article.slug, "")))
    if food is not None and food.image_path and not article.cover_image:
        article.cover_image = food.image_path
        article.cover_credit = " · ".join(x for x in (food.image_credit, food.image_license) if x) or None


def seed_all(overwrite: bool = False) -> dict:
    return {"foods": seed_foods(overwrite), "articles": seed_articles(overwrite)}
