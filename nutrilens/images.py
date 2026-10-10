"""Xử lý ảnh: kiểm tra, xoay theo EXIF, thu nhỏ và lưu dạng WebP vào thư mục static."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_UPLOAD_BYTES = 6 * 1024 * 1024


class ImageError(ValueError):
    pass


def process_image(data: bytes, max_width: int = 1200, quality: int = 82) -> bytes:
    """Trả về ảnh WebP đã chuẩn hóa. Ném ImageError nếu file không phải ảnh hợp lệ."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("Ảnh lớn hơn 6 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageError("File không phải ảnh hợp lệ.") from exc
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("Chỉ hỗ trợ ảnh JPG, PNG hoặc WEBP.")
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def save_image(data: bytes, folder: str, basename: str, **kwargs) -> str:
    """Lưu ảnh vào static/<folder>/ và trả về đường dẫn tương đối dùng cho url_for('static', ...)."""
    webp = process_image(data, **kwargs)
    digest = hashlib.sha1(webp, usedforsecurity=False).hexdigest()[:10]  # Chỉ để đặt tên file
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in basename.lower())[:60] or "image"
    rel = f"{folder}/{safe}-{digest}.webp"
    path = Path(current_app.static_folder) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(webp)
    return rel


def delete_image(rel_path: str | None) -> None:
    """Xóa ảnh do người dùng tải lên (chỉ trong thư mục uploads, không đụng ảnh gốc của website)."""
    if not rel_path or not rel_path.startswith("uploads/"):
        return
    path = Path(current_app.static_folder) / rel_path
    try:
        path.resolve().relative_to(Path(current_app.static_folder).resolve())
        path.unlink(missing_ok=True)
    except (ValueError, OSError):
        pass
