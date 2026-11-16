FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --create-home --uid 10001 app \
 && mkdir -p /data \
 && chown app:app /data

COPY app ./app
USER app

ENV DATA_DIR=/data \
    OMP_NUM_THREADS=2 \
    MALLOC_ARENA_MAX=2 \
    PYTHONUNBUFFERED=1 \
    WHISPER_MODEL=small \
    WHISPER_THREADS=2 \
    FFMPEG_THREADS=2 \
    MAX_CLIPS=80 \
    MAX_UPLOAD_MB=1500

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=25s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
