#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

IMAGE_NAME="${IMAGE_NAME:-mlx-ui}"
IMAGE_TAG="${IMAGE_TAG:-local}"
IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="${CONTAINER_NAME:-mlx-ui}"
PORT="${PORT:-8000}"
BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1}"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/data}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-}"
DOCKER_PULL="${DOCKER_PULL:-}"
TRANSCRIBER_BACKEND="${TRANSCRIBER_BACKEND:-whisper}"
WHISPER_MODEL="${WHISPER_MODEL:-large-v3-turbo}"
WHISPER_DEVICE="${WHISPER_DEVICE:-cpu}"
WHISPER_CACHE_DIR="${WHISPER_CACHE_DIR:-/app/data/.cache/whisper}"

log() {
  printf '%s\n' "==> $*"
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  fail "Docker not found. Install Docker Desktop and re-run."
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker daemon not running. Start Docker Desktop and re-run."
fi

if [[ "$TRANSCRIBER_BACKEND" =~ ^(wtm|mlx|wtm-cli)$ ]]; then
  fail "TRANSCRIBER_BACKEND=$TRANSCRIBER_BACKEND is not supported in Docker. Use ./run.sh on macOS or set TRANSCRIBER_BACKEND=whisper."
fi

mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/results" "$DATA_DIR/logs" "$DATA_DIR/.cache/whisper"

cleanup_containers() {
  local ids
  ids="$(docker ps -a --filter "name=^/${CONTAINER_NAME}$" -q)"
  if [[ -n "$ids" ]]; then
    log "Removing existing container $CONTAINER_NAME"
    docker rm -f $ids >/dev/null
  fi

  for status in exited created dead; do
    ids="$(docker ps -a --filter "ancestor=$IMAGE" --filter "status=$status" -q)"
    if [[ -n "$ids" ]]; then
      log "Removing stale containers for image $IMAGE ($status)"
      docker rm $ids >/dev/null
    fi
  done
}

build_image() {
  local args=()
  if [[ -n "$DOCKER_PLATFORM" ]]; then
    args+=(--platform "$DOCKER_PLATFORM")
  fi
  if [[ "$DOCKER_PULL" == "1" ]]; then
    args+=(--pull)
  fi
  log "Building image $IMAGE"
  if [[ ${#args[@]} -gt 0 ]]; then
    docker build "${args[@]}" -t "$IMAGE" .
  else
    docker build -t "$IMAGE" .
  fi
}

run_container() {
  local user_args=()
  if command -v id >/dev/null 2>&1; then
    user_args+=(--user "$(id -u):$(id -g)")
  fi
  log "Starting container $CONTAINER_NAME"
  if [[ ${#user_args[@]} -gt 0 ]]; then
    docker run --rm --init \
      --name "$CONTAINER_NAME" \
      -p "${BIND_ADDRESS}:${PORT}:8000" \
      -v "${DATA_DIR}:/app/data" \
      -e "HOME=/app/data" \
      -e "XDG_CACHE_HOME=/app/data/.cache" \
      -e "TRANSCRIBER_BACKEND=${TRANSCRIBER_BACKEND}" \
      -e "WHISPER_MODEL=${WHISPER_MODEL}" \
      -e "WHISPER_DEVICE=${WHISPER_DEVICE}" \
      -e "WHISPER_FP16=${WHISPER_FP16:-0}" \
      -e "WHISPER_CACHE_DIR=${WHISPER_CACHE_DIR}" \
      -e "LOG_DIR=/app/data/logs" \
      -e "DISABLE_UPDATE_CHECK=${DISABLE_UPDATE_CHECK:-}" \
      -e "UPDATE_CHECK_URL=${UPDATE_CHECK_URL:-}" \
      -e "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}" \
      -e "TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}" \
      "${user_args[@]}" \
      "$IMAGE"
  else
    docker run --rm --init \
      --name "$CONTAINER_NAME" \
      -p "${BIND_ADDRESS}:${PORT}:8000" \
      -v "${DATA_DIR}:/app/data" \
      -e "HOME=/app/data" \
      -e "XDG_CACHE_HOME=/app/data/.cache" \
      -e "TRANSCRIBER_BACKEND=${TRANSCRIBER_BACKEND}" \
      -e "WHISPER_MODEL=${WHISPER_MODEL}" \
      -e "WHISPER_DEVICE=${WHISPER_DEVICE}" \
      -e "WHISPER_FP16=${WHISPER_FP16:-0}" \
      -e "WHISPER_CACHE_DIR=${WHISPER_CACHE_DIR}" \
      -e "LOG_DIR=/app/data/logs" \
      -e "DISABLE_UPDATE_CHECK=${DISABLE_UPDATE_CHECK:-}" \
      -e "UPDATE_CHECK_URL=${UPDATE_CHECK_URL:-}" \
      -e "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}" \
      -e "TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}" \
      "$IMAGE"
  fi
}

cleanup_containers
build_image
cleanup_containers
run_container
