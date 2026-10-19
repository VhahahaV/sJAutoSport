#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -c constraints.txt -e '.[web]'
npm --prefix frontend ci
npm --prefix frontend run build
printf '%s\n' 'Build complete. Start/restart the core and API using README.md.'
