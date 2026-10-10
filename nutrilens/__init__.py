"""NutriLens: website ẩm thực và dinh dưỡng với nhận dạng món ăn bằng AI."""

import logging
import secrets
import threading
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import HTTPException, ServiceUnavailable

from . import cli, security
from .catalog import ArticleStore, Catalog
from .config import Config
from .extensions import db, login_manager, migrate
from .nutrition import DAILY_VALUES
from .predictor import Predictor


def create_app(config_object=Config, predictor=None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _ensure_secret_key(app)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(Path(app.root_path).parent / "migrations"))
    login_manager.init_app(app)
    login_manager.session_protection = "basic"
    from . import models  # noqa: F401  Đăng ký các bảng với SQLAlchemy và Alembic

    catalog = Catalog(app.config["CLASSES_PATH"])
    app.extensions["catalog"] = catalog
    app.extensions["articles"] = ArticleStore()
    app.extensions["predictor"] = predictor or Predictor(app.config["MODEL_PATH"], catalog.class_names)

    if app.config.get("PRELOAD_MODEL") and not app.testing:
        _schedule_preload(app)

    app.before_request(security.protect)
    app.after_request(security.set_security_headers)

    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .views import bp as main_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    cli.register(app)

    @app.context_processor
    def inject_globals():
        return {
            "site_name": app.config["SITE_NAME"],
            "site_tagline": app.config["SITE_TAGLINE"],
            "csrf_token": security.csrf_token,
            "current_year": date.today().year,
            "daily_values": DAILY_VALUES,
            "dish_count": catalog.count(),
        }

    @app.template_filter("num")
    def format_number(value, digits=0):
        """Định dạng số kiểu Việt Nam: 1.500 và 2,5"""
        if value is None:
            return "–"
        if float(value).is_integer():
            return f"{int(value):,}".replace(",", ".")
        text = f"{value:,.{digits or 1}f}"
        return text.replace(",", "§").replace(".", ",").replace("§", ".")

    @app.errorhandler(OperationalError)
    def handle_db_down(err):
        app.logger.error("Database error: %s", err.orig if hasattr(err, "orig") else err)
        db.session.rollback()
        return handle_http_error(ServiceUnavailable(
            description="Không kết nối được cơ sở dữ liệu. Nếu chạy trên máy, hãy bật MySQL trong XAMPP "
                        "rồi chạy lệnh: flask --app app setup-db"))

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=err.description, status=err.code), err.code
        try:
            return render_template("error.html", error=err), err.code
        except OperationalError:
            # CSDL lỗi trong lúc dựng trang lỗi (ví dụ đếm số món): trả về trang tối giản
            return f"<h1>{err.code}</h1><p>{err.description}</p>", err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        app.logger.exception("Unhandled error")
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify(error="Đã có lỗi xảy ra, vui lòng thử lại.", status=500), 500
        return render_template("error.html", error=None), 500

    return app


def _ensure_secret_key(app: Flask) -> None:
    """Dùng chung một SECRET_KEY cho mọi tiến trình: lấy từ biến môi trường hoặc file instance/secret_key."""
    if app.config.get("SECRET_KEY"):
        return
    path = Path(app.instance_path) / "secret_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        app.logger.warning("SECRET_KEY not set, generated %s", path)
    app.config["SECRET_KEY"] = path.read_text(encoding="utf-8").strip()


def _schedule_preload(app: Flask) -> None:
    """Nạp model ở luồng nền khi có request đầu tiên (không chạy khi dùng các lệnh flask db/seed)."""
    state = {"started": False}
    lock = threading.Lock()

    @app.before_request
    def _kick_off_preload():
        if state["started"]:
            return
        with lock:
            if state["started"]:
                return
            state["started"] = True
        threading.Thread(target=_safe_preload, args=(app.extensions["predictor"],), daemon=True).start()


def _safe_preload(predictor: Predictor):
    try:
        predictor.load()
    except Exception:  # noqa: BLE001 - lỗi đã được ghi log trong predictor
        pass
