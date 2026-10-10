"""Chống CSRF tối giản dựa trên session, không cần thư viện ngoài."""

import hmac
import secrets

from flask import abort, request, session

TOKEN_KEY = "_csrf_token"


def csrf_token() -> str:
    token = session.get(TOKEN_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[TOKEN_KEY] = token
    return token


def protect():
    """Gắn vào before_request: mọi request ghi dữ liệu phải mang token hợp lệ."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get(TOKEN_KEY, "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Phiên làm việc đã hết hạn. Vui lòng tải lại trang và thử lại.")


def set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response
