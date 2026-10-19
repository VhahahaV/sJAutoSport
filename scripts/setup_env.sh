#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
mkdir -p "$PROJECT_ROOT/data"
chmod 700 "$PROJECT_ROOT/data"
if [[ ! -f "$PROJECT_ROOT/frontend/.env.local" ]]; then
  printf '%s\n' 'VITE_API_BASE_URL=/api' > "$PROJECT_ROOT/frontend/.env.local"
fi
printf '%s\n' 'Runtime directory ready. See README.md for login and launch commands.'
