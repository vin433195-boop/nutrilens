"""Lệnh quản trị: flask --app app <lệnh>

  setup-db       Tạo database MySQL (nếu chưa có), chạy migration và nạp dữ liệu mẫu
  seed           Nạp dữ liệu món ăn và bài viết từ file
  create-admin   Tạo hoặc nâng quyền tài khoản quản trị
"""

import sys

import click
from flask import current_app
from flask_migrate import upgrade
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from .extensions import db
from .models import User
from .seed import seed_all


def create_database_if_missing() -> str | None:
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if not url.get_backend_name().startswith(("mysql", "mariadb")) or not url.database:
        return None
    name = url.database
    if not name.replace("_", "").isalnum():
        raise click.ClickException(f"Tên database không hợp lệ: {name}")
    engine = create_engine(url.set(database=""))  # set() bỏ qua None, chuỗi rỗng = không chọn DB
    with engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}` "
                          "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    engine.dispose()
    return name


def _print_seed(result: dict) -> None:
    for kind, (created, updated) in result.items():
        click.echo(f"  {kind}: thêm mới {created}, cập nhật {updated}")


def _utf8_console() -> None:
    """Console Windows mặc định không in được tiếng Việt, chuyển sang UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def register(app):
    @app.cli.command("setup-db")
    def setup_db():
        """Tạo database, chạy migration và nạp dữ liệu mẫu."""
        _utf8_console()
        name = create_database_if_missing()
        if name:
            click.echo(f"Database `{name}` đã sẵn sàng (utf8mb4).")
        upgrade()
        click.echo("Đã tạo/cập nhật các bảng.")
        _print_seed(seed_all())
        click.echo("Hoàn tất.")

    @app.cli.command("seed")
    @click.option("--overwrite", is_flag=True, help="Ghi đè bản ghi đã có bằng dữ liệu trong file.")
    def seed(overwrite):
        """Nạp món ăn và bài viết từ file JSON/Markdown."""
        _utf8_console()
        _print_seed(seed_all(overwrite))

    @app.cli.command("create-admin")
    @click.option("--email", prompt="Email")
    @click.option("--name", prompt="Họ tên", default="Quản trị viên")
    @click.password_option(prompt="Mật khẩu")
    def create_admin(email, name, password):
        """Tạo tài khoản quản trị, hoặc nâng quyền nếu email đã tồn tại."""
        _utf8_console()
        email = email.strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name)
            user.set_password(password)
            db.session.add(user)
        user.role = "admin"
        db.session.commit()
        click.echo(f"Tài khoản {email} đã có quyền quản trị.")
