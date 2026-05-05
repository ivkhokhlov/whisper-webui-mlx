#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

IMAGE_NAME="${IMAGE_NAME:-mlx-ui-parakeet-cuda}"
IMAGE_TAG="${IMAGE_TAG:-spark}"
IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="${CONTAINER_NAME:-mlx-ui-parakeet-cuda}"
NEMO_BASE_IMAGE="${NEMO_BASE_IMAGE:-nvcr.io/nvidia/nemo:26.02.01}"
PORT="${PORT:-32000}"
BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1}"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/data-spark}"
HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"
PARAKEET_MODEL="${PARAKEET_MODEL:-nvidia/parakeet-tdt-0.6b-v3}"
PARAKEET_BATCH_SIZE="${PARAKEET_BATCH_SIZE:-1}"
PARAKEET_CHUNK_DURATION="${PARAKEET_CHUNK_DURATION:-30}"
PARAKEET_OVERLAP_DURATION="${PARAKEET_OVERLAP_DURATION:-5}"
PARAKEET_DECODING_MODE="${PARAKEET_DECODING_MODE:-greedy}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-}"
DOCKER_PULL="${DOCKER_PULL:-}"
RUN_AS_ROOT="${RUN_AS_ROOT:-1}"

log() {
  printf '%s\n' "==> $*"
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  fail "Docker not found."
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker daemon not running."
fi

mkdir -p \
  "$DATA_DIR/uploads" \
  "$DATA_DIR/results" \
  "$DATA_DIR/logs" \
  "$DATA_DIR/.cache" \
  "$HF_CACHE_DIR"

SETTINGS_FILE="$DATA_DIR/settings.json"
if [[ "${SPARK_PRESEED_SETTINGS:-1}" == "1" && ! -f "$SETTINGS_FILE" ]]; then
  log "Writing initial Spark settings to $SETTINGS_FILE"
  PARAKEET_MODEL="$PARAKEET_MODEL" \
  PARAKEET_BATCH_SIZE="$PARAKEET_BATCH_SIZE" \
  PARAKEET_CHUNK_DURATION="$PARAKEET_CHUNK_DURATION" \
  PARAKEET_OVERLAP_DURATION="$PARAKEET_OVERLAP_DURATION" \
  PARAKEET_DECODING_MODE="$PARAKEET_DECODING_MODE" \
  python3 - "$SETTINGS_FILE" <<'PY'
import json
import os
import sys

settings_path = sys.argv[1]
settings = {
    "engine": "parakeet_tdt_v3",
    "output_formats": ["txt", "srt", "vtt", "json"],
    "default_language": "auto",
    "update_check_enabled": False,
    "parakeet_model": os.environ["PARAKEET_MODEL"],
    "parakeet_chunk_duration": float(os.environ["PARAKEET_CHUNK_DURATION"]),
    "parakeet_overlap_duration": float(os.environ["PARAKEET_OVERLAP_DURATION"]),
    "parakeet_decoding_mode": os.environ["PARAKEET_DECODING_MODE"],
    "parakeet_batch_size": int(os.environ["PARAKEET_BATCH_SIZE"]),
}
with open(settings_path, "w", encoding="utf-8") as handle:
    json.dump(settings, handle, indent=2, ensure_ascii=True)
    handle.write("\n")
PY
fi

build_args=(
  -f Dockerfile.spark
  --build-arg "NEMO_BASE_IMAGE=$NEMO_BASE_IMAGE"
  -t "$IMAGE"
)
if [[ -n "$DOCKER_PLATFORM" ]]; then
  build_args=(--platform "$DOCKER_PLATFORM" "${build_args[@]}")
fi
if [[ "$DOCKER_PULL" == "1" ]]; then
  build_args+=(--pull)
fi

log "Building image $IMAGE from $NEMO_BASE_IMAGE"
docker build "${build_args[@]}" .

existing="$(docker ps -a --filter "name=^/${CONTAINER_NAME}$" -q)"
if [[ -n "$existing" ]]; then
  log "Removing existing container $CONTAINER_NAME"
  docker rm -f "$existing" >/dev/null
fi

user_args=()
if [[ "$RUN_AS_ROOT" != "1" ]] && command -v id >/dev/null 2>&1; then
  user_args+=(--user "$(id -u):$(id -g)")
fi

log "Starting $CONTAINER_NAME on ${BIND_ADDRESS}:${PORT}"
docker run -d --init \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --gpus all \
  --ipc=host \
  --shm-size="${SHM_SIZE:-16g}" \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  --log-driver=json-file \
  --log-opt max-size="${LOG_MAX_SIZE:-200m}" \
  --log-opt max-file="${LOG_MAX_FILE:-3}" \
  -p "${BIND_ADDRESS}:${PORT}:8000" \
  -v "${DATA_DIR}:/app/data" \
  -v "${HF_CACHE_DIR}:/app/hf-cache" \
  -e "HOME=/app/data" \
  -e "XDG_CACHE_HOME=/app/data/.cache" \
  -e "HF_HOME=/app/hf-cache" \
  -e "TRANSCRIBER_BACKEND=parakeet_nemo_cuda" \
  -e "PARAKEET_NEMO_CUDA_EXPERIMENTAL=1" \
  -e "DISABLE_UPDATE_CHECK=1" \
  -e "LOG_DIR=/app/data/logs" \
  --health-cmd "python3 -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/state', timeout=5).read()\" || exit 1" \
  --health-interval 30s \
  --health-timeout 8s \
  --health-retries 5 \
  --health-start-period 5m \
  "${user_args[@]}" \
  "$IMAGE"

log "Open http://${BIND_ADDRESS}:${PORT}"
