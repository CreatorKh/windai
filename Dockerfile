# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/kredit.db

WORKDIR /srv

# Bog'liqliklar alohida qatlam — kod o'zgarganda qayta o'rnatilmasin.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/
COPY tests/ ./tests/
COPY data/ ./data/

RUN mkdir -p /data /srv/natija

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=25s --retries=4 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/meta',timeout=3)"

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
