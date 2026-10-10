"""Các extension Flask dùng chung, khởi tạo trong create_app()."""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Quy ước đặt tên ràng buộc để Alembic sinh migration ổn định trên mọi loại CSDL
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING))
migrate = Migrate()
login_manager = LoginManager()
# Giới hạn số request theo địa chỉ IP. Mặc định lưu trong bộ nhớ;
# khi chạy nhiều tiến trình hãy đặt RATELIMIT_STORAGE_URI=redis://...
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
