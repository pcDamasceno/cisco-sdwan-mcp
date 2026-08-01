#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="${MCP_DOCKER_IMAGE:-cisco-sdwan-mcp}"
CONTAINER_NAME="${MCP_DOCKER_CONTAINER:-cisco-sdwan-mcp}"
HOST_PORT="${MCP_DOCKER_PORT:-8000}"
NO_BUILD="${NO_BUILD:-false}"
ENV_FILE="${MCP_ENV_FILE:-$ROOT_DIR/.env}"

if [[ "$NO_BUILD" != "true" ]]; then
    docker build -t "$IMAGE_NAME" "$ROOT_DIR"
fi

EXISTING_CONTAINER="$(docker ps -aq --filter "name=^/${CONTAINER_NAME}$")"
if [[ -n "$EXISTING_CONTAINER" ]]; then
    docker rm -f "$CONTAINER_NAME" >/dev/null
fi

# vManage credentials come from .env so they never land in shell history or
# `docker inspect` output as literal arguments.
ENV_ARGS=()
if [[ -f "$ENV_FILE" ]]; then
    ENV_ARGS+=(--env-file "$ENV_FILE")
else
    echo "warning: $ENV_FILE not found — the server will start but every tool" >&2
    echo "         will report a ConfigurationError until SDWAN_* is set." >&2
    echo "         Run: cp .env.example .env" >&2
fi

docker run --rm -it \
    --name "$CONTAINER_NAME" \
    -p "${HOST_PORT}:8000" \
    "${ENV_ARGS[@]}" \
    -e MCP_TRANSPORT=http \
    -e MCP_HOST=0.0.0.0 \
    -e MCP_PORT=8000 \
    "$IMAGE_NAME"
