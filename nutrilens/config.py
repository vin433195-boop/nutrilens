"""Cấu hình ứng dụng. Giá trị đọc từ biến môi trường hoặc file .env ở thư mục gốc."""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

load_dotenv(PROJECT_DIR / ".env")


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SITE_NAME = "NutriLens"
    SITE_TAGLINE = "Hiểu món ăn, sống khỏe mỗi ngày"

    # Nếu không đặt SECRET_KEY, create_app() tạo khóa và lưu vào instance/secret_key
    # để mọi tiến trình và mọi lần khởi động dùng chung một khóa.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # ── Cơ sở dữ liệu ──
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "mysql+pymysql://root:@localhost:3306/nutrilens?charset=utf8mb4")
    # pool_pre_ping và pool_recycle tránh lỗi "MySQL server has gone away" khi kết nối để lâu
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Tải ảnh và model ──
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
    # Ưu tiên bản .tflite (nhẹ, chạy được trên máy chủ 512 MB RAM), không có thì dùng .h5
    MODEL_PATH = Path(os.environ.get("MODEL_PATH") or next(
        (p for p in (PROJECT_DIR / "food_model.tflite", PROJECT_DIR / "food_model.h5") if p.exists()),
        PROJECT_DIR / "food_model.h5"))
    CLASSES_PATH = PROJECT_DIR / "class_names.json"
    # Nạp model ở luồng nền ngay khi có request đầu tiên. Đặt PRELOAD_MODEL=0 để chỉ nạp khi cần.
    PRELOAD_MODEL = _bool("PRELOAD_MODEL", "1")

    # ── Dữ liệu khởi tạo (chỉ dùng cho lệnh flask seed / setup-db) ──
    MAPPING_PATH = PROJECT_DIR / "Mapping_Calories.json"
    FOODS_PATH = PACKAGE_DIR / "data" / "foods.json"
    ARTICLES_DIR = PACKAGE_DIR / "data" / "articles"

    # ── Phiên đăng nhập ──
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("COOKIE_SECURE")  # Bật khi chạy HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _bool("COOKIE_SECURE")

    # ── Giới hạn số request (Flask-Limiter) ──
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", "1")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    PASSWORD_RESET_MAX_AGE = 3600  # giây
    EMAIL_VERIFY_MAX_AGE = 3 * 24 * 3600

    # ── Email (để trống MAIL_SERVER thì email được in ra log, dùng khi phát triển) ──
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", "1")
    MAIL_USE_SSL = _bool("MAIL_USE_SSL", "0")  # Cổng 465
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_SENDER = os.environ.get("MAIL_SENDER", "NutriLens <no-reply@nutrilens.local>")


    # ── Vận hành ──
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
    TRUST_PROXY = _bool("TRUST_PROXY")                      # Bật khi chạy sau Nginx/Caddy
    LOG_DIR = os.environ.get("LOG_DIR", str(PROJECT_DIR / "logs"))
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
    BACKUP_DIR = os.environ.get("BACKUP_DIR", str(PROJECT_DIR / "backups"))
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", 14))


class TestConfig(Config):
    TESTING = True
    RATELIMIT_ENABLED = False
    SECRET_KEY = "test-secret"  # noqa: S105 - chỉ dùng khi chạy test
    PRELOAD_MODEL = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    # Một kết nối dùng chung để CSDL trong bộ nhớ không bị mất giữa các truy vấn
    SQLALCHEMY_ENGINE_OPTIONS = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    MAIL_SERVER = ""
