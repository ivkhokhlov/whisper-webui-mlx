FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/app/data \
    XDG_CACHE_HOME=/app/data/.cache \
    TRANSCRIBER_BACKEND=whisper \
    WHISPER_MODEL=small \
    WHISPER_DEVICE=cpu \
    WHISPER_FP16=0 \
    WHISPER_CACHE_DIR=/app/data/.cache/whisper

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-docker.txt ./
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    torch \
    && pip install --no-cache-dir -r requirements-docker.txt

COPY mlx_ui ./mlx_ui

RUN mkdir -p /app/data /app/data/.cache

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "mlx_ui.app:app", "--host", "0.0.0.0", "--port", "8000"]
