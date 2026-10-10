"""Các bảng dữ liệu của NutriLens (SQLAlchemy 2, chạy trên MySQL/MariaDB hoặc SQLite)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import markdown
from flask_login import UserMixin
from markupsafe import Markup
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Table, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .nutrition import NutritionMixin
from .extensions import db


def utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, không kèm múi giờ (kiểu DATETIME của MySQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ════════════════════════════════════════════════════════════
#  Người dùng
# ════════════════════════════════════════════════════════════
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20), default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    profile: Mapped["Profile | None"] = relationship(back_populates="user", uselist=False,
                                                     cascade="all, delete-orphan")
    diary_entries: Mapped[list["DiaryEntry"]] = relationship(back_populates="user",
                                                             cascade="all, delete-orphan")
    recognitions: Mapped[list["Recognition"]] = relationship(back_populates="user",
                                                             cascade="all, delete-orphan")

    # Flask-Login dùng is_active để chặn tài khoản bị vô hiệu hóa
    @property
    def is_active(self) -> bool:
        return bool(self.active)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def initials(self) -> str:
        parts = self.name.split()
        return (parts[-1][0] if parts else self.email[0]).upper()

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > utcnow())

    def register_failed_login(self, max_attempts: int, lock_minutes: int) -> None:
        self.failed_logins = (self.failed_logins or 0) + 1
        if self.failed_logins >= max_attempts:
            self.locked_until = utcnow() + timedelta(minutes=lock_minutes)
            self.failed_logins = 0

    def register_login(self) -> None:
        self.failed_logins = 0
        self.locked_until = None
        self.last_login_at = utcnow()


class Profile(db.Model):
    """Chỉ số cơ thể và mục tiêu dinh dưỡng của người dùng."""
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sex: Mapped[str | None] = mapped_column(String(10))
    age: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    activity: Mapped[float | None] = mapped_column(Float)
    goal: Mapped[int | None] = mapped_column(Integer)
    target_kcal: Mapped[int] = mapped_column(Integer, default=2000)
    target_protein: Mapped[int] = mapped_column(Integer, default=75)
    target_carb: Mapped[int] = mapped_column(Integer, default=250)
    target_fat: Mapped[int] = mapped_column(Integer, default=67)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")

    def target_dict(self) -> dict:
        return {"calories": self.target_kcal, "protein": self.target_protein,
                "carb": self.target_carb, "fat": self.target_fat}

    def body_dict(self) -> dict:
        return {"sex": self.sex, "age": self.age, "height": self.height_cm, "weight": self.weight_kg,
                "activity": self.activity, "goal": self.goal}


# ════════════════════════════════════════════════════════════
#  Món ăn
# ════════════════════════════════════════════════════════════
food_tags = Table(
    "food_tags", db.metadata,
    Column("food_id", ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Category(db.Model):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Tag(db.Model):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)


class Food(NutritionMixin, db.Model):
    """Một món ăn. Giá trị dinh dưỡng tính cho một khẩu phần (cột serving)."""
    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name_vi: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(16), default="🍽️")
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    cuisine: Mapped[str] = mapped_column(String(80), default="Quốc tế")
    serving: Mapped[str] = mapped_column(String(120), default="1 khẩu phần")
    description: Mapped[str] = mapped_column(Text, default="")
    calories: Mapped[float] = mapped_column(Float, default=0)
    carbohydrate: Mapped[float] = mapped_column(Float, default=0)
    protein: Mapped[float] = mapped_column(Float, default=0)
    lipid: Mapped[float] = mapped_column(Float, default=0)
    fiber: Mapped[float] = mapped_column(Float, default=0)
    sugar: Mapped[float] = mapped_column(Float, default=0)
    sodium: Mapped[float] = mapped_column(Float, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    category_ref: Mapped[Category] = relationship(lazy="joined")
    notes: Mapped[list["FoodNote"]] = relationship(order_by="FoodNote.position", lazy="selectin",
                                                   cascade="all, delete-orphan")
    tag_objs: Mapped[list[Tag]] = relationship(secondary=food_tags, lazy="selectin")

    # Giữ nguyên giao diện cũ để template và API không phải thay đổi
    @property
    def category(self) -> str:
        return self.category_ref.name if self.category_ref else ""

    @property
    def highlights(self) -> list[str]:
        return [n.text for n in self.notes if n.kind == "highlight"]

    @property
    def tips(self) -> list[str]:
        return [n.text for n in self.notes if n.kind == "tip"]

    @property
    def tags(self) -> list[str]:
        return [t.name for t in self.tag_objs]


class FoodNote(db.Model):
    """Điểm cộng (highlight) hoặc mẹo ăn lành mạnh (tip) của một món."""
    __tablename__ = "food_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)


class ModelLabel(db.Model):
    """Ánh xạ nhãn đầu ra của model AI sang món ăn trong thư viện."""
    __tablename__ = "model_labels"

    label: Mapped[str] = mapped_column(String(80), primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))

    food: Mapped[Food] = relationship()


# ════════════════════════════════════════════════════════════
#  Bài viết
# ════════════════════════════════════════════════════════════
class Article(db.Model):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    excerpt: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(60), default="Kiến thức")
    emoji: Mapped[str] = mapped_column(String(16), default="📘")
    body_md: Mapped[str] = mapped_column(Text, default="")
    read_time: Mapped[int] = mapped_column(Integer, default=3)
    published_at: Mapped[date] = mapped_column(Date, default=date.today)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def html(self) -> Markup:
        # Nội dung do biên tập viên soạn, không phải dữ liệu người dùng gửi lên
        return Markup(markdown.markdown(self.body_md, extensions=["extra", "sane_lists"]))

    @property
    def date_vi(self) -> str:
        return self.published_at.strftime("%d/%m/%Y")


# ════════════════════════════════════════════════════════════
#  Nhật ký ăn uống và lịch sử nhận dạng
# ════════════════════════════════════════════════════════════
class DiaryEntry(db.Model):
    """Một món trong nhật ký. Lưu lại dinh dưỡng tại thời điểm ghi để lịch sử không đổi khi sửa món."""
    __tablename__ = "diary_entries"
    __table_args__ = (Index("ix_diary_user_date", "user_id", "entry_date"),)

    MEALS = ("breakfast", "lunch", "dinner", "snack")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    meal: Mapped[str] = mapped_column(String(16))
    servings: Mapped[float] = mapped_column(Float, default=1)
    kcal: Mapped[float] = mapped_column(Float)
    carb: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float)
    fat: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="diary_entries")
    food: Mapped[Food] = relationship(lazy="joined")

    @classmethod
    def from_food(cls, user: User, food: Food, day: date, meal: str, servings: float) -> "DiaryEntry":
        return cls(user=user, food=food, entry_date=day, meal=meal, servings=servings,
                   kcal=food.calories, carb=food.carbohydrate, protein=food.protein, fat=food.lipid)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "slug": self.food.slug, "name": self.food.name_vi, "emoji": self.food.emoji,
            "serving": self.food.serving, "meal": self.meal, "servings": self.servings,
            "kcal": self.kcal, "carb": self.carb, "protein": self.protein, "fat": self.fat,
        }


class Recognition(db.Model):
    """Một lần nhận dạng ảnh. Ảnh không được lưu, chỉ lưu kết quả và lựa chọn sửa của người dùng."""
    __tablename__ = "recognitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    predicted_label: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"))
    corrected_food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"))
    tta: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship(back_populates="recognitions")
    food: Mapped[Food | None] = relationship(foreign_keys=[food_id], lazy="joined")
    corrected_food: Mapped[Food | None] = relationship(foreign_keys=[corrected_food_id], lazy="joined")

    def to_dict(self) -> dict:
        shown = self.corrected_food or self.food
        return {
            "id": self.id,
            "slug": shown.slug if shown else self.predicted_label,
            "name": shown.name_vi if shown else self.predicted_label,
            "emoji": shown.emoji if shown else "🍽️",
            "kcal": shown.calories if shown else None,
            "confidence": self.confidence,
            "corrected": self.corrected_food_id is not None,
            "time": self.created_at.replace(tzinfo=timezone.utc).isoformat(),
        }


# ════════════════════════════════════════════════════════════
#  Liên hệ và bản tin
# ════════════════════════════════════════════════════════════
class ContactMessage(db.Model):
    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Subscriber(db.Model):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
