"""Chống CSRF tối giản dựa trên session, không cần thư viện ngoài."""

import hmac
import secrets

from flask import abort, current_app, g, request, session

TOKEN_KEY = "_csrf_token"  # noqa: S105 - tên khóa trong session, không phải mật khẩu


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


def csp_nonce() -> str:
    """Nonce ngẫu nhiên cho mỗi request, gắn vào các thẻ <script> inline được phép chạy."""
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def set_security_headers(response):
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    if response.mimetype == "text/html":
        h.setdefault("Content-Security-Policy", "; ".join([
            "default-src 'self'",
            f"script-src 'self' 'nonce-{csp_nonce()}'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'self'",
        ]))
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
