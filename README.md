# Aviator demo deposit system

Python/Flask backend for **simulated Demo USD deposits**, kept separate from real-account balances. The original game UI is preserved.

## How the existing site worked (from `index.html`)

- Demo vs Real is a header switch (`switchAccount`).
- Demo balance started at **$100 USD equivalent** in `localStorage` key `betrush_demo_balance_v2`.
- Real balance was a **separate** `localStorage` key `betrush_real_balance_v2`, starting at `$0`.
- Bets deducted the active mode’s local balance. Real mode showed an insufficient-funds modal and sent users to `/public/deposit`.
- The menu button **reset demo balance only**.
- There was **no server ledger**, no deposit form, and no admin panel in the GitHub repo (it was empty until these files).
- A Telegram bot token was previously hardcoded in the browser script. That is **not** stored in this repo. Optional Telegram sending goes through `/api/signals/telegram` using `.env`.

This project keeps that UI and moves **demo money** onto SQLite so deposits, history, and admin actions are server-validated.

## File layout

```
AVIATOR/
  app.py              Flask app (pages + APIs)
  index.html          Game (original layout, backend wiring)
  deposit.html        Demo + Real deposit interface
  admin.html          DEMO ACCOUNT MANAGEMENT
  schema.sql          Database structure
  requirements.txt
  .env.example
  data/aviator.db     Created at runtime (not committed)
```

## Environment

```bash
copy .env.example .env
```

Set `SECRET_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD`. Never commit `.env` or GitHub/Telegram tokens.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open:

- Game: http://127.0.0.1:5000/
- Deposit: http://127.0.0.1:5000/deposit.html (also `/public/deposit`)
- Admin: http://127.0.0.1:5000/admin.html

## Connecting the frontend

Pages are served by Flask on the same origin, so `fetch(..., { credentials: 'include' })` uses the session cookie.

- Demo switch on `index.html` calls `POST /api/demo/session` and `GET /api/demo/balance`.
- Demo bets/cash-outs call `/api/demo/wager` and `/api/demo/payout` (demo ledger only).
- Deposit form posts to `/api/demo/deposit` or `/api/real/deposit`.
- Real deposit requests are **PENDING** and do **not** credit real or demo balances as a payment.

## Security rules implemented

- Demo and real balances are different tables.
- Every demo transaction is stored with status `SIMULATED`.
- Deposit amounts are validated on the server (`1.00`–`100000.00` USD).
- Users only access the demo account tied to their session/user id.
- Admin APIs require admin login and write an audit log.

## Production

Use gunicorn (Linux) or a Windows process manager:

```bash
pip install -r requirements.txt
gunicorn -b 0.0.0.0:5000 app:app
```

Put Nginx/Caddy in front with HTTPS and set `FLASK_HTTPS=1` so the session cookie is Secure.
