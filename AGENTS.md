# Repository Guidelines

Automates SJTU sports venue bookings with a FastAPI backend, React control panel, and QQ bot workflow. Use these notes to collaborate smoothly.

## Project Structure & Module Organization
- `sja_booking/` hosts the booking engine, schedulers, and credential helpers used by every entry point.
- `web_api/` contains the FastAPI app, routers, and background tasks; `start_integrated.py` wires the long-running services together.
- `frontend/` is a Vite + React + TypeScript SPA; `bot/` holds the NoneBot adapters and plugins.
- `config/` and `data/` store environment-driven templates (`config/users.json`, `data/credentials.json`); `scripts/` bundles deployment helpers; docs live in `docs/`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` prepares a local virtualenv; `pip install -r requirements.txt` installs backend/bot deps.
- `uvicorn web_api.app:app --reload --port 8000` runs the API; `python start_integrated.py` launches API, worker, and bot together.
- `cd frontend && npm install` for dependencies, then `npm run dev` (hot reload) or `npm run build` for production bundles.
- `npm run lint` applies ESLint/Prettier rules to the SPA; add `--fix` locally before committing.

## Coding Style & Naming Conventions
- Python: 4-space indentation, type-hint public functions, prefer `Path` over raw strings, and format with `black` followed by `flake8` and `mypy`.
- React/TypeScript: keep components in PascalCase, hooks/utilities in camelCase, and colocate styles/assets beside the component under `frontend/src`.
- Keep environment templates (`deploy.env`, `config/*.json`) free of real secrets; example placeholders should be uppercase snake case.

## Testing Guidelines
- Add backend tests under `tests/` using `pytest`/`pytest-asyncio`; run `pytest -q` before pushing.
- Mock external services (sports API, QQ bot) via fixtures; avoid hitting production endpoints.
- Target meaningful coverage on booking flows, credential rotation, and API contracts; document any skipped scenarios in the PR.

## Commit & Pull Request Guidelines
- Follow Conventional Commits (`feat:`, `fix:`, `refactor:`) as seen in history; keep bodies imperative and scoped to one change.
- Each PR should include: summary, manual/automated test results, affected services, new env vars, and UI screenshots when touching the frontend.
- Reference related issues/tasks and note rollout steps (e.g., `scripts/deploy.sh`) so operators can execute them after merge.

## Deployment & Configuration Tips
- Never commit populated `deploy.env`, `config/users.json`, or `data/credentials.json`; share secrets via secure channels.
- Document any dependency on OCR (Tesseract) or captchas in the PR so ops can provision it.
- Prefer upgrading services via `scripts/deploy.sh` or `deploy_quick.sh`; call out schema or cache changes that require manual intervention.
