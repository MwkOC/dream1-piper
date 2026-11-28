#!/bin/sh
set -eu
if [ "${RSTACK_STORAGE_BACKEND:-postgres}" = "postgres" ]; then
  attempt=1
  max_attempts=${RSTACK_DATABASE_STARTUP_ATTEMPTS:-30}
  until alembic -c /app/backend/alembic.ini upgrade head; do
    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "PostgreSQL did not become available after $attempt attempts." >&2
      exit 1
    fi
    echo "Waiting for PostgreSQL before applying migrations (attempt $attempt/$max_attempts)." >&2
    attempt=$((attempt + 1))
    sleep 2
  done
elif [ "${RSTACK_STORAGE_BACKEND}" != "memory" ]; then
  echo "Unsupported RSTACK_STORAGE_BACKEND: ${RSTACK_STORAGE_BACKEND}" >&2
  exit 2
else
  echo "Using process-local memory storage; no PostgreSQL connection or migrations." >&2
fi
exec dream1-piper-station
