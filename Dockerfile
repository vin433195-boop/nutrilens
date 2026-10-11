# NutriLens: Flask + Waitress.
# ML=lite (mặc định): AI chạy bằng LiteRT + food_model.tflite, vừa máy chủ 512 MB RAM (Render free)
# ML=full: TensorFlow đầy đủ (~1 GB RAM)    ML=none: không có AI
FROM python:3.10-slim

ARG ML=lite
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production TRUST_PROXY=1 LOG_DIR=/app/logs PORT=8000

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
RUN case "$ML" in \
      full) pip install -r requirements-ml.txt ;; \
      lite) pip install -r requirements-lite.txt ;; \
      *) pip install -r requirements.txt ;; \
    esac

COPY . .
# Bản lite không cần file .h5 (51 MB)
RUN if [ "$ML" = "lite" ]; then rm -f food_model.h5; fi \
    && useradd --create-home --uid 1000 app && mkdir -p logs instance backups nutrilens/static/uploads \
    && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD curl -fsS http://localhost:${PORT}/healthz || exit 1

# Chạy migration rồi mới phục vụ request. Render/Railway... tự đặt biến PORT.
CMD ["sh", "-c", "flask --app app setup-db && waitress-serve --host=0.0.0.0 --port=${PORT} --threads=4 app:app"]
