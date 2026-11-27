#!/bin/sh
set -eu
alembic -c /app/backend/alembic.ini upgrade head
exec dream1-piper-station
