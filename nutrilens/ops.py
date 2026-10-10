"""Vận hành: kiểm tra sức khỏe, ghi log ra file, chạy sau reverse proxy, theo dõi lỗi (Sentry), sao lưu CSDL."""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.engine import make_url
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import db

bp = Blueprint("ops", __name__)


@bp.get("/healthz")
def healthz():
    """Dùng cho Docker healthcheck, load balancer hoặc dịch vụ giám sát uptime."""
    checks = {"database": "ok", "model": current_app.extensions["predictor"].status}
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - chỉ cần biết CSDL có trả lời hay không
        db.session.rollback()
        checks["database"] = "error"
    ok = checks["database"] == "ok"
    return jsonify(status="ok" if ok else "degraded", **checks), 200 if ok else 503


def setup(app) -> None:
    if app.config.get("TRUST_PROXY"):
        # Chạy sau Nginx/Caddy: lấy đúng IP người dùng (cho giới hạn request) và scheme https
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    log_dir = app.config.get("LOG_DIR")
    if log_dir and not app.testing:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(Path(log_dir) / "nutrilens.log", maxBytes=5 * 1024 * 1024,
                                      backupCount=5, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)

    dsn = app.config.get("SENTRY_DSN")
    if dsn and not app.testing:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration
        except ImportError:
            app.logger.warning("SENTRY_DSN is set but sentry-sdk is not installed (pip install sentry-sdk[flask])")
        else:
            sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()], traces_sample_rate=0.1,
                            send_default_pii=False, environment=app.config.get("ENVIRONMENT", "production"))


def find_mysqldump() -> str | None:
    candidates = [os.environ.get("MYSQLDUMP_PATH"), shutil.which("mysqldump"), shutil.which("mariadb-dump"),
                  r"C:\xampp\mysql\bin\mysqldump.exe"]
    return next((c for c in candidates if c and Path(c).exists()), None)


def backup_database(out_dir: Path, keep: int = 14) -> Path:
    """Xuất toàn bộ CSDL MySQL ra file .sql.gz và chỉ giữ lại `keep` bản mới nhất."""
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if not url.get_backend_name().startswith(("mysql", "mariadb")):
        raise RuntimeError("Lệnh sao lưu chỉ hỗ trợ MySQL/MariaDB.")
    tool = find_mysqldump()
    if tool is None:
        raise RuntimeError("Không tìm thấy mysqldump. Đặt biến MYSQLDUMP_PATH trỏ tới file mysqldump.")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{url.database}-{datetime.now():%Y%m%d-%H%M%S}.sql.gz"
    cmd = [tool, f"--host={url.host or 'localhost'}", f"--port={url.port or 3306}", f"--user={url.username}",
           "--single-transaction", "--routines", "--default-character-set=utf8mb4", url.database]
    env = dict(os.environ, MYSQL_PWD=url.password or "")  # Không đưa mật khẩu lên dòng lệnh
    proc = subprocess.run(cmd, capture_output=True, env=env, timeout=600)  # noqa: S603 - tham số lấy từ cấu hình
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or "mysqldump thất bại")
    with gzip.open(target, "wb") as f:
        f.write(proc.stdout)
    backups = sorted(out_dir.glob(f"{url.database}-*.sql.gz"))
    for old in backups[:-keep]:
        old.unlink()
    return target
