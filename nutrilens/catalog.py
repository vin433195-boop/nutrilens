"""Truy vấn thư viện món ăn và bài viết từ cơ sở dữ liệu."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, or_, select

from .extensions import db
from .models import Article, Category, Food, ModelLabel, Tag


class Catalog:
    def __init__(self, classes_path: Path):
        # Thứ tự lớp đầu ra của model AI. Đây là siêu dữ liệu của file model, không phải dữ liệu món ăn.
        with open(classes_path, encoding="utf-8") as f:
            self.class_names: list[str] = json.load(f)

    @staticmethod
    def _published():
        return select(Food).where(Food.is_published.is_(True))

    def count(self) -> int:
        return db.session.scalar(select(func.count(Food.id)).where(Food.is_published.is_(True))) or 0

    def all(self) -> list[Food]:
        return list(db.session.scalars(self._published().order_by(Food.name_vi)).unique())

    def get(self, slug: str) -> Food | None:
        return db.session.scalars(self._published().where(Food.slug == slug)).unique().first()

    def by_label(self, label: str) -> Food | None:
        mapping = db.session.get(ModelLabel, label)
        return mapping.food if mapping and mapping.food.is_published else None

    def categories(self) -> list[str]:
        stmt = (select(Category.name).join(Food, Food.category_id == Category.id)
                .where(Food.is_published.is_(True)).group_by(Category.id, Category.name, Category.position)
                .order_by(Category.position, Category.name))
        return list(db.session.scalars(stmt))

    def featured(self, n: int = 6) -> list[Food]:
        foods = list(db.session.scalars(self._published().where(Food.is_featured.is_(True))
                                        .order_by(Food.id).limit(n)).unique())
        return foods or self.all()[:n]

    def related(self, food: Food, n: int = 4) -> list[Food]:
        stmt = (self._published().where(Food.id != food.id)
                .order_by((Food.category_id != food.category_id), (Food.cuisine != food.cuisine),
                          func.abs(Food.calories - food.calories))
                .limit(n))
        return list(db.session.scalars(stmt).unique())

    def search(self, query: str) -> list[Food]:
        q = query.strip()
        if not q:
            return self.all()
        like = f"%{q}%"
        stmt = (self._published().outerjoin(Food.tag_objs)
                .where(or_(Food.name_vi.ilike(like), Food.name_en.ilike(like),
                           Food.cuisine.ilike(like), Tag.name.ilike(like)))
                .order_by(Food.name_vi))
        return list(db.session.scalars(stmt).unique())


class ArticleStore:
    @staticmethod
    def _published():
        return (select(Article).where(Article.is_published.is_(True))
                .order_by(Article.published_at.desc(), Article.id.desc()))

    def all(self) -> list[Article]:
        return list(db.session.scalars(self._published()))

    def latest(self, n: int = 3) -> list[Article]:
        return list(db.session.scalars(self._published().limit(n)))

    def get(self, slug: str) -> Article | None:
        return db.session.scalars(self._published().where(Article.slug == slug)).first()

    def categories(self) -> list[str]:
        seen: list[str] = []
        for a in self.all():
            if a.category not in seen:
                seen.append(a.category)
        return seen
