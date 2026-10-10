"""Nạp dữ liệu khởi tạo từ các file JSON/Markdown vào cơ sở dữ liệu.

Nguồn dữ liệu:
- class_names.json, Mapping_Calories.json (thư mục gốc): nhãn model và calo/macro gốc
- nutrilens/data/foods.json: tên tiếng Việt, mô tả, khẩu phần, điểm cộng, mẹo, thẻ
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
from .models import Article, Category, Food, FoodNote, ModelLabel, Tag
from .nutrition import CATEGORY_ORDER, pretty

FEATURED = ["pho", "sushi", "spring_rolls", "omelette", "tacos", "chicken_curry"]


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


def seed_foods(overwrite: bool = False) -> tuple[int, int]:
    cfg = current_app.config
    class_names = _load_json(cfg["CLASSES_PATH"])
    mapping = _load_json(cfg["MAPPING_PATH"])
    content = _load_json(cfg["FOODS_PATH"])
    categories, tags = {}, {}
    created = updated = 0

    # Tắt autoflush: món mới chỉ được ghi xuống CSDL sau khi đã gán đủ danh mục, thẻ
    with db.session.no_autoflush:
        for slug in class_names:
            macros, extra = mapping.get(slug, {}), content.get(slug, {})
            food = db.session.scalar(select(Food).where(Food.slug == slug))
            if food is not None and not overwrite:
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
            food.serving = extra.get("serving", "1 khẩu phần")
            food.description = extra.get("description", "")
            food.calories = macros.get("calories", 0)
            food.carbohydrate = macros.get("carbohydrate", 0)
            food.protein = macros.get("protein", 0)
            food.lipid = macros.get("lipid", 0)
            food.fiber = extra.get("fiber", 0)
            food.sugar = extra.get("sugar", 0)
            food.sodium = extra.get("sodium", 0)
            food.is_featured = slug in FEATURED
            food.notes = (
                [FoodNote(kind="highlight", text=t, position=i) for i, t in enumerate(extra.get("highlights", []))]
                + [FoodNote(kind="tip", text=t, position=i) for i, t in enumerate(extra.get("tips", []))]
            )
            food.tag_objs = [_get_tag(t, tags) for t in extra.get("tags", [])]
            if is_new:
                db.session.add(food)
            db.session.flush()
            _ensure_label(slug, food)

    db.session.commit()
    return created, updated


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
    db.session.commit()
    return created, updated


def seed_all(overwrite: bool = False) -> dict:
    return {"foods": seed_foods(overwrite), "articles": seed_articles(overwrite)}
