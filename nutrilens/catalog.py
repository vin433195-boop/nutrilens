"""Truy vấn thư viện món ăn và bài viết từ cơ sở dữ liệu."""

from __future__ import annotations

import json
import math
import time
import unicodedata
from pathlib import Path

from sqlalchemy import func, select

from .extensions import db
from .models import Article, Category, Food, ModelLabel


class ListPage:
    """Phân trang cho danh sách đã có sẵn, cùng giao diện với Pagination của Flask-SQLAlchemy."""

    def __init__(self, items: list, page: int, per_page: int):
        self.total = len(items)
        self.per_page = per_page
        self.pages = max(1, math.ceil(self.total / per_page))
        self.page = min(max(1, page), self.pages)
        start = (self.page - 1) * per_page
        self.items = items[start:start + per_page]
        self.has_prev, self.has_next = self.page > 1, self.page < self.pages
        self.prev_num, self.next_num = self.page - 1, self.page + 1
        self.first = start + 1 if self.total else 0
        self.last = start + len(self.items)

    def iter_pages(self, left_edge=1, left_current=2, right_current=2, right_edge=1):
        last = 0
        for n in range(1, self.pages + 1):
            if n <= left_edge or self.page - left_current <= n <= self.page + right_current or n > self.pages - right_edge:
                if last + 1 != n:
                    yield None
                yield n
                last = n


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt: dùng để tìm kiếm và sắp xếp theo bảng chữ cái."""
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


SORTS = {
    "ten": ("Tên A–Z", lambda f: fold(f.name_vi), False),
    "calo-tang": ("Calo thấp → cao", lambda f: f.calories, False),
    "calo-giam": ("Calo cao → thấp", lambda f: f.calories, True),
    "protein": ("Protein nhiều nhất", lambda f: f.protein, True),
    "diem": ("Điểm sức khỏe", lambda f: f.health_score, True),
}


class Catalog:
    _count_cache: tuple[float, int] | None = None

    def __init__(self, classes_path: Path):
        # Thứ tự lớp đầu ra của model AI. Đây là siêu dữ liệu của file model, không phải dữ liệu món ăn.
        with open(classes_path, encoding="utf-8") as f:
            self.class_names: list[str] = json.load(f)

    @staticmethod
    def _published():
        return select(Food).where(Food.is_published.is_(True))

    def count(self, max_age: float = 60) -> int:
        """Số món đang hiển thị. Lưu đệm 60 giây vì được dùng trên mọi trang."""
        now = time.monotonic()
        if self._count_cache and now - self._count_cache[0] < max_age:
            return self._count_cache[1]
        n = db.session.scalar(select(func.count(Food.id)).where(Food.is_published.is_(True))) or 0
        self._count_cache = (now, n)
        return n

    def invalidate(self) -> None:
        self._count_cache = None

    def browse(self, q: str = "", category: str = "", sort: str = "ten", page: int = 1, per_page: int = 12) -> ListPage:
        """Lọc, sắp xếp và phân trang cho trang thư viện."""
        foods = self.search(q) if q else self.all()
        if category:
            foods = [f for f in foods if f.category == category]
        label, key, reverse = SORTS.get(sort, SORTS["ten"])
        foods.sort(key=key, reverse=reverse)
        return ListPage(foods, page, per_page)

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
        """Tìm không phân biệt dấu: "pho" khớp "Phở", "nhat" khớp "Nhật Bản"."""
        terms = fold(query).split()
        if not terms:
            return self.all()
        out = []
        for f in self.all():
            haystack = fold(" ".join([f.name_vi, f.name_en, f.cuisine, f.category, *f.tags]))
            if all(t in haystack for t in terms):
                out.append(f)
        return out


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
