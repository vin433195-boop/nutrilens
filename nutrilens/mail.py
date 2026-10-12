"""Gửi email (văn bản và HTML).

Thứ tự ưu tiên:
1. BREVO_API_KEY: gửi qua API HTTPS của Brevo. Dùng được trên máy chủ chặn cổng SMTP (như Render bản miễn phí).
2. MAIL_SERVER: gửi qua SMTP (Gmail, Outlook...).
3. Không cấu hình gì: link trong email được in ra log, dùng khi phát triển.
"""

import json
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from flask import current_app, render_template

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def mail_configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("BREVO_API_KEY") or cfg.get("MAIL_SERVER"))


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> bool:
    cfg = current_app.config
    if current_app.testing and not cfg.get("MAIL_REAL_IN_TESTS"):
        # Khi chạy test: lưu email vào hộp thư giả thay vì gửi
        current_app.extensions.setdefault("mail_outbox", []).append(
            {"to": to, "subject": subject, "text": text, "html": html})
        return True
    if cfg.get("BREVO_API_KEY"):
        return _send_brevo(to, subject, text, html)
    if not cfg.get("MAIL_SERVER"):
        # Chế độ phát triển: in link trong email ra console (chỉ ASCII để console Windows hiển thị đúng)
        links = re.findall(r"https?://\S+", text) or ["(no link)"]
        current_app.logger.warning("Mail not configured, email NOT sent. To: %s | Link: %s",
                                   to, " ".join(links))
        return False
    return _send_smtp(to, subject, text, html)


def _send_brevo(to: str, subject: str, text: str, html: str | None) -> bool:
    cfg = current_app.config
    name, sender = parseaddr(cfg["MAIL_SENDER"])
    payload = {"sender": {"name": name or cfg["SITE_NAME"], "email": sender},
               "to": [{"email": to}], "subject": subject, "textContent": text}
    if html:
        payload["htmlContent"] = html
    req = urllib.request.Request(
        BREVO_URL, data=json.dumps(payload).encode(), method="POST",
        headers={"api-key": cfg["BREVO_API_KEY"], "accept": "application/json", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:  # noqa: S310 - URL cố định https
            return 200 <= res.status < 300
    except urllib.error.HTTPError as exc:
        # Brevo trả lý do trong body, ví dụ người gửi chưa được xác minh hoặc API key sai
        detail = exc.read().decode("utf-8", "replace")[:300]
        current_app.logger.error("Brevo rejected email to %s: HTTP %s %s", to, exc.code, detail)
    except (urllib.error.URLError, OSError):
        current_app.logger.exception("Failed to reach Brevo for email to %s", to)
    return False


def _send_smtp(to: str, subject: str, text: str, html: str | None) -> bool:
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_SENDER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=cfg["MAIL_SENDER"].rsplit("@", 1)[-1].strip("> ") or None)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        if cfg.get("MAIL_USE_SSL"):
            smtp = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15)
        else:
            smtp = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15)
        with smtp:
            if cfg["MAIL_USE_TLS"] and not cfg.get("MAIL_USE_SSL"):
                smtp.starttls()
            if cfg["MAIL_USERNAME"]:
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        current_app.logger.exception("Failed to send email to %s", to)
        return False


def send_template(to: str, subject: str, template: str, **context) -> bool:
    """Dùng cặp template emails/<template>.txt và emails/<template>.html."""
    context.setdefault("site_name", current_app.config["SITE_NAME"])
    text = render_template(f"emails/{template}.txt", **context)
    html = render_template(f"emails/{template}.html", subject=subject, **context)
    return send_mail(to, subject, text, html)
