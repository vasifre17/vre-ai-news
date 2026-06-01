#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
IMAGE_UPLOAD_BACKUP_DIR="${IMAGE_UPLOAD_BACKUP_DIR:-${IMAGE_UPLOAD_HOST_DIR:-/opt/vre-ai-news/uploads/images}}"
mkdir -p "$BACKUP_DIR"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set."
  exit 1
fi

if [[ "$DATABASE_URL" == sqlite* ]]; then
  DB_PATH="${DATABASE_URL#sqlite:///}"
  cp "$DB_PATH" "$BACKUP_DIR/vre_news_${TIMESTAMP}.db"
  echo "SQLite backup created: $BACKUP_DIR/vre_news_${TIMESTAMP}.db"
else
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "pg_dump not found. Install postgresql-client."
    exit 1
  fi
  pg_dump "$DATABASE_URL" > "$BACKUP_DIR/vre_news_${TIMESTAMP}.sql"
  echo "PostgreSQL backup created: $BACKUP_DIR/vre_news_${TIMESTAMP}.sql"
fi

if [[ -d "$IMAGE_UPLOAD_BACKUP_DIR" ]]; then
  tar -C "$(dirname "$IMAGE_UPLOAD_BACKUP_DIR")" -czf "$BACKUP_DIR/vre_news_uploads_${TIMESTAMP}.tar.gz" "$(basename "$IMAGE_UPLOAD_BACKUP_DIR")"
  echo "Image uploads backup created: $BACKUP_DIR/vre_news_uploads_${TIMESTAMP}.tar.gz"
else
  echo "Image upload directory not found, skipping image backup: $IMAGE_UPLOAD_BACKUP_DIR"
fi
