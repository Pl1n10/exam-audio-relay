#!/usr/bin/env bash
set -euo pipefail

# Wait briefly for DB then run migrations. The app's lifespan also retries the DB.
echo "Running database migrations..."
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if alembic upgrade head; then
    break
  fi
  echo "Migration attempt ${attempt} failed, retrying in 2s..."
  sleep 2
done

exec "$@"
