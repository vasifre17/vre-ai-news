#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
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
