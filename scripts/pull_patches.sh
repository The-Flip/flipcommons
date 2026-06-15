#!/bin/sh
# Pull data patches from Cloudflare R2 (the flippatch/ prefix) to local
# data/ingest_sources/flippatch/. Thin wrapper around the Django mgmt command.
set -e

cd "$(git rev-parse --show-toplevel)"

DEST="$(pwd)/${1:-data/ingest_sources}"

# Load .env if present
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

exec uv run --directory backend python manage.py pull_patches --dest "$DEST"
