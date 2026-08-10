#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build.sh — build (and optionally push) the Portcullis Docker images.
#
#   <registry>/portcullis:<tag>           — FastAPI backend (root Dockerfile)
#   <registry>/portcullis-frontend:<tag>  — Streamlit UI (frontend/Dockerfile)
#
# Usage:
#   ./build.sh                    # build both; tag from src/main.py + latest
#   ./build.sh -t 3.2.0 -p        # build and push
#   ./build.sh -s frontend        # frontend only
#
# Options:
#   -t <tag>        image tag (default: version in src/main.py)
#   -r <registry>   Docker Hub namespace (default: simplitics1)
#   -s <service>    all | api | frontend (default: all)
#   -p              push after building (run 'docker login' first)
#   -n              build with --no-cache
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TAG=""
REGISTRY="simplitics1"
SERVICE="all"
PUSH=0
NO_CACHE=0

while getopts ":t:r:s:pnh" opt; do
  case "$opt" in
    t) TAG="$OPTARG" ;;
    r) REGISTRY="$OPTARG" ;;
    s) SERVICE="$OPTARG" ;;
    p) PUSH=1 ;;
    n) NO_CACHE=1 ;;
    h) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: -$OPTARG" >&2; exit 1 ;;
  esac
done

case "$SERVICE" in
  all|api|frontend) ;;
  *) echo "Invalid -s '$SERVICE' (expected: all, api, frontend)" >&2; exit 1 ;;
esac

if [ -z "$TAG" ]; then
  TAG="$(grep -oE 'version[[:space:]]*=[[:space:]]*"[^"]+"' "$ROOT/src/main.py" 2>/dev/null \
         | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
  TAG="${TAG:-latest}"
fi

TAGS=("$TAG")
[ "$TAG" != "latest" ] && TAGS+=("latest")

build_image() {
  local name="$1" context="$2" dockerfile="$3"
  local image="$REGISTRY/$name"

  local args=(build -f "$dockerfile")
  for t in "${TAGS[@]}"; do args+=(-t "$image:$t"); done
  [ "$NO_CACHE" -eq 1 ] && args+=(--no-cache)
  args+=("$context")

  echo "==> Building $image (${TAGS[*]})"
  docker "${args[@]}"

  if [ "$PUSH" -eq 1 ]; then
    for t in "${TAGS[@]}"; do
      echo "==> Pushing $image:$t"
      docker push "$image:$t"
    done
  fi
}

if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "api" ]; then
  build_image "portcullis" "$ROOT" "$ROOT/Dockerfile"
fi
if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "frontend" ]; then
  build_image "portcullis-frontend" "$ROOT/frontend" "$ROOT/frontend/Dockerfile"
fi

echo
echo "Done. Tags: ${TAGS[*]}"
[ "$PUSH" -eq 1 ] || echo "Not pushed. Re-run with -p (after 'docker login') to publish."
echo "Run with: IMAGE_TAG=$TAG docker compose up -d"
