# NutriLens: Flask + Waitress. Mặc định có AI (TensorFlow); build nhẹ hơn với: --build-arg WITH_ML=0
FROM python:3.10-slim

ARG WITH_ML=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production TRUST_PROXY=1 LOG_DIR=/app/logs

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
RUN if [ "$WITH_ML" = "1" ]; then pip install -r requirements-ml.txt; else pip install -r requirements.txt; fi

COPY . .
RUN useradd --create-home --uid 1000 app && mkdir -p logs instance backups nutrilens/static/uploads \
    && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD curl -fsS http://localhost:8000/healthz || exit 1

# Chạy migration rồi mới phục vụ request
CMD ["sh", "-c", "flask --app app setup-db && waitress-serve --host=0.0.0.0 --port=8000 --threads=8 app:app"]
