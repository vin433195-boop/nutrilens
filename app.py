"""Điểm khởi chạy website NutriLens.

Lần đầu:             flask --app app setup-db
Chạy thử trên máy:   python app.py
Chạy production:     waitress-serve --port=8000 app:app
"""

import os
import threading

from nutrilens import _safe_preload, create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    if app.config.get("PRELOAD_MODEL") and (not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        # Nạp model AI ngay khi khởi động để lần nhận dạng đầu tiên không phải chờ
        threading.Thread(target=_safe_preload, args=(app.extensions["predictor"],), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=debug)
