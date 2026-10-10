"""Điểm khởi chạy website NutriLens.

Lần đầu:             flask --app app setup-db
Chạy thử trên máy:   python app.py
Chạy production:     waitress-serve --port=8000 app:app
"""

import os
import socket
import sys
import threading

from nutrilens import _safe_preload, create_app

app = create_app()


def port_in_use(port: int) -> bool:
    """Trên Windows, server Flask có thể chạy chồng nhiều bản trên cùng một cổng mà không báo lỗi.
    Khi đó trình duyệt bị chuyển ngẫu nhiên tới bản cũ. Kiểm tra trước để tránh."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and port_in_use(port):
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"Cổng {port} đang có một website khác chạy (có thể là bản NutriLens cũ chưa tắt).\n"
              f"Hãy tắt cửa sổ đó (Ctrl+C) rồi chạy lại, hoặc chạy cổng khác: set PORT=5001 && python app.py")
        sys.exit(1)
    if app.config.get("PRELOAD_MODEL") and (not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        # Nạp model AI ngay khi khởi động để lần nhận dạng đầu tiên không phải chờ
        threading.Thread(target=_safe_preload, args=(app.extensions["predictor"],), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=debug)
