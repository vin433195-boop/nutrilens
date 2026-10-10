"""Gửi email qua SMTP. Khi chưa cấu hình MAIL_SERVER, nội dung email được ghi ra log."""

import re
import smtplib
from email.message import EmailMessage

from flask import current_app


def mail_configured() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def send_mail(to: str, subject: str, body: str) -> bool:
    cfg = current_app.config
    if not mail_configured():
        # Chế độ phát triển: in link trong email ra console (chỉ ASCII để console Windows hiển thị đúng)
        links = re.findall(r"https?://\S+", body) or ["(no link)"]
        current_app.logger.warning("MAIL_SERVER not configured, email NOT sent. To: %s | Link: %s",
                                   to, " ".join(links))
        return False

    msg = EmailMessage()
    msg["From"] = cfg["MAIL_SENDER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as smtp:
            if cfg["MAIL_USE_TLS"]:
                smtp.starttls()
            if cfg["MAIL_USERNAME"]:
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        current_app.logger.exception("Failed to send email to %s", to)
        return False
