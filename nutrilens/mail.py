"""Gửi email qua SMTP (dạng văn bản và HTML). Khi chưa cấu hình MAIL_SERVER, link trong email được in ra log."""

import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app, render_template


def mail_configured() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> bool:
    cfg = current_app.config
    if current_app.testing:
        # Khi chạy test: lưu email vào hộp thư giả thay vì gửi
        current_app.extensions.setdefault("mail_outbox", []).append(
            {"to": to, "subject": subject, "text": text, "html": html})
        return True
    if not mail_configured():
        # Chế độ phát triển: in link trong email ra console (chỉ ASCII để console Windows hiển thị đúng)
        links = re.findall(r"https?://\S+", text) or ["(no link)"]
        current_app.logger.warning("MAIL_SERVER not configured, email NOT sent. To: %s | Link: %s",
                                   to, " ".join(links))
        return False

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
