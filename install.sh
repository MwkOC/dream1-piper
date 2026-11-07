#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
umask 077

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dream-test.txt

if [[ ! -e .env ]]; then
  cp .env.example .env
fi
chmod 600 .env

printf 'Listo. Usa: source %s/.venv/bin/activate\n' "$root"
