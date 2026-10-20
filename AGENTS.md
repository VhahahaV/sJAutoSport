# sJAutoSport project map

Single-account SJTU sports booking: one Python core and two heads (CLI + React).

- `sja_booking/operations.py`: canonical operation names, Pydantic input contracts and dispatch. Run `sja schema` before using an operation. No duplicate protocol in Web.
- `sja_booking/service.py`: verified password/captcha and QR login, queries, booking, orders, live monitors and session keepalive.
- `sja_booking/auth.py`, `api.py`, `order.py`: campus protocol. `auth.py` persists scoped sports/jAccount cookies; `keep_alive.py` serializes session verification and SSO recovery for both heads and monitors. Preserve newer credentials on concurrent login/logout; never replay booking/refund requests. Never log passwords/cookies or recognize captchas automatically; return images for the user.
- `sja_booking/database.py`: SQLite state/history/events. `config.py`: public presets, environment configuration.
- Booking attempts are persisted before submission. Reuse `request_id` for transport retries; `orders.reconcile` checks uncertain results without replaying POSTs. An empty list never proves failure. Only explicit user confirmation authorizes `confirm_not_created`.
- `OrderResult.response_info` preserves bounded, redacted HTTP/business response evidence across replay and reconciliation. Keep raw responses and credentials private. Error text does not prove rollback; no campus rejection code is currently verified for automatic continuation.
- `slots.list` retains a session-bound 60-second snapshot; `orders.create` accepts its ID. `orders.cascade` uses one snapshot for ordered preferences, explicit price/attempt limits, and at most one success. No automatic continuation codes are assumed; code 500 must remain uncertain. See README for the protocol and timing fields.
- `sja_booking/daemon.py`: singleton core process and private Unix socket. Both CLI and HTTP use this process; stopping a head must not stop monitors.
- `sja_booking/cli.py`: `sja`, also `python -m sja_booking`.
- `web_api/app.py`: thin localhost HTTP gateway; `frontend/`: Vite + React + TypeScript.
- `frontend/src/pages/Order.tsx`: canonical `/slots` booking flow, from venue/date/slots through confirmation. `/order` redirects here.
- `frontend/src/pages/Dashboard.tsx` and `components/AvailabilityCard.tsx`: saved availability cards; `dashboard.*` core operations persist config and screen date summaries before loading slots. Fixed card height, daily chart, scrollable full details.
- Other protected pages: overview `/dashboard`, orders `/orders`, live monitors `/monitor`, account and keepalive `/keep-alive`. `/` shows login only when unauthenticated.
- `data/`: ignored private runtime state. Keep the same `SJA_DATA_DIR` for core, CLI and HTTP. Do not commit this directory or `deploy.env`.

## Commands

Python 3.11+, Linux. See [README.md](README.md) for installation/login/deployment.

- Install: `python -m pip install -c constraints.txt -e '.[web,test]'` inside `.venv`.
- CLI: `.venv/bin/sja daemon start`, `.venv/bin/sja schema`.
- API: `.venv/bin/python -m uvicorn web_api.app:app --host 127.0.0.1 --port 8000`.
- Frontend: `cd frontend && npm ci && npm run dev`; `npm run build` typechecks and builds.
- Tests: `.venv/bin/python -m pytest -q`; mock campus mutations. Never make real bookings/refunds during validation.

## Boundaries

One account, one credential record, one core runtime. No QQ bot, account pools, scheduled reservations, browser automation or OCR. Live monitoring may optionally book immediately when a slot appears; keepalive periodically maintains the saved login. These are the only background workflows.

Preserve user edits, stage specific files, and commit/push only when requested. Use public placeholder identities in tests/docs. Update this map and README when operation or page boundaries change.

Write all commit subjects and bodies in English. Follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
