import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(BASE_DIR, os.getenv("DATABASE_PATH", os.path.join("data", "aviator.db")))
MIN_DEPOSIT = Decimal("1.00")
MAX_DEPOSIT = Decimal("100000.00")
DEMO_START_USD = Decimal("100.00")
CENTS = Decimal("0.01")

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_HTTPS", "0") == "1"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH) or DATA_DIR, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS demo_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            guest_key TEXT UNIQUE,
            balance_usd TEXT NOT NULL DEFAULT '100.00',
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS real_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            guest_key TEXT UNIQUE,
            balance_usd TEXT NOT NULL DEFAULT '0.00',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS demo_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            demo_account_id INTEGER NOT NULL,
            amount_usd TEXT NOT NULL,
            tx_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SIMULATED',
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(demo_account_id) REFERENCES demo_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS real_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            real_account_id INTEGER NOT NULL,
            amount_usd TEXT NOT NULL,
            tx_type TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(real_account_id) REFERENCES real_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_username TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            details TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "admin123")
    row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            (username, generate_password_hash(password), utcnow()),
        )
        db.commit()
    db.close()


def money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def parse_deposit_amount(raw):
    amount = money(raw)
    if amount is None or amount < MIN_DEPOSIT or amount > MAX_DEPOSIT:
        return None
    return amount


def json_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def current_guest_key():
    key = session.get("guest_key")
    if not key:
        key = os.urandom(16).hex()
        session["guest_key"] = key
    return key


def get_or_create_demo_account(db):
    user_id = session.get("user_id")
    guest_key = current_guest_key()
    if user_id:
        row = db.execute("SELECT * FROM demo_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return row
        db.execute(
            "INSERT INTO demo_accounts (user_id, guest_key, balance_usd, is_enabled, created_at) VALUES (?, ?, ?, 1, ?)",
            (user_id, guest_key, str(DEMO_START_USD), utcnow()),
        )
        db.commit()
        return db.execute("SELECT * FROM demo_accounts WHERE user_id = ?", (user_id,)).fetchone()
    row = db.execute("SELECT * FROM demo_accounts WHERE guest_key = ?", (guest_key,)).fetchone()
    if row:
        return row
    db.execute(
        "INSERT INTO demo_accounts (user_id, guest_key, balance_usd, is_enabled, created_at) VALUES (?, ?, ?, 1, ?)",
        (None, guest_key, str(DEMO_START_USD), utcnow()),
    )
    db.commit()
    return db.execute("SELECT * FROM demo_accounts WHERE guest_key = ?", (guest_key,)).fetchone()


def get_or_create_real_account(db):
    user_id = session.get("user_id")
    guest_key = current_guest_key()
    if user_id:
        row = db.execute("SELECT * FROM real_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return row
        db.execute(
            "INSERT INTO real_accounts (user_id, guest_key, balance_usd, created_at) VALUES (?, ?, '0.00', ?)",
            (user_id, guest_key, utcnow()),
        )
        db.commit()
        return db.execute("SELECT * FROM real_accounts WHERE user_id = ?", (user_id,)).fetchone()
    row = db.execute("SELECT * FROM real_accounts WHERE guest_key = ?", (guest_key,)).fetchone()
    if row:
        return row
    db.execute(
        "INSERT INTO real_accounts (user_id, guest_key, balance_usd, created_at) VALUES (?, ?, '0.00', ?)",
        (None, guest_key, utcnow()),
    )
    db.commit()
    return db.execute("SELECT * FROM real_accounts WHERE guest_key = ?", (guest_key,)).fetchone()


def demo_enabled(account):
    return bool(account["is_enabled"])


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return json_error("Admin authentication required", 401)
        return fn(*args, **kwargs)

    return wrapper


def audit(action, target=None, details=None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (admin_username, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (session.get("admin_username") or "unknown", action, target, details, utcnow()),
    )
    db.commit()


@app.route("/")
def index_page():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/deposit.html")
@app.route("/public/deposit")
@app.route("/deposit")
@app.route("/public/deposit/index.html")
def deposit_page():
    return send_from_directory(BASE_DIR, "deposit.html")


@app.route("/mpesa.html")
@app.route("/public/deposit/mpesa.html")
def mpesa_page():
    return send_from_directory(BASE_DIR, "mpesa.html")


@app.route("/admin.html")
@app.route("/admin")
def admin_page():
    return send_from_directory(BASE_DIR, "admin.html")


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if len(username) < 3 or len(password) < 6:
        return json_error("Username must be 3+ characters and password 6+ characters")
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
            (username, generate_password_hash(password), utcnow()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return json_error("Username already exists", 409)
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    get_or_create_demo_account(db)
    get_or_create_real_account(db)
    return jsonify({"ok": True, "username": username})


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return json_error("Invalid credentials", 401)
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    if user["is_admin"]:
        session["is_admin"] = True
        session["admin_username"] = user["username"]
    get_or_create_demo_account(db)
    get_or_create_real_account(db)
    return jsonify({"ok": True, "username": username, "is_admin": bool(user["is_admin"])})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/demo/session")
def demo_session():
    db = get_db()
    account = get_or_create_demo_account(db)
    get_or_create_real_account(db)
    return jsonify(
        {
            "ok": True,
            "demo_account_id": account["id"],
            "balance_usd": str(money(account["balance_usd"])),
            "is_enabled": demo_enabled(account),
            "account_kind": "DEMO",
        }
    )


@app.get("/api/demo/balance")
def demo_balance():
    db = get_db()
    account = get_or_create_demo_account(db)
    return jsonify(
        {
            "ok": True,
            "account_kind": "DEMO",
            "balance_usd": str(money(account["balance_usd"])),
            "is_enabled": demo_enabled(account),
        }
    )


@app.get("/api/real/balance")
def real_balance():
    db = get_db()
    account = get_or_create_real_account(db)
    return jsonify(
        {
            "ok": True,
            "account_kind": "REAL",
            "balance_usd": str(money(account["balance_usd"])),
        }
    )


def add_demo_tx(db, account_id, amount, tx_type, note):
    db.execute(
        """INSERT INTO demo_transactions (demo_account_id, amount_usd, tx_type, status, note, created_at)
           VALUES (?, ?, ?, 'SIMULATED', ?, ?)""",
        (account_id, str(amount), tx_type, note, utcnow()),
    )


@app.post("/api/demo/deposit")
def demo_deposit():
    amount = parse_deposit_amount((request.get_json(silent=True) or {}).get("amount_usd"))
    if amount is None:
        return json_error(f"Enter a USD amount between {MIN_DEPOSIT} and {MAX_DEPOSIT}")
    db = get_db()
    account = get_or_create_demo_account(db)
    if not demo_enabled(account):
        return json_error("This demo account is disabled", 403)
    new_balance = money(account["balance_usd"]) + amount
    db.execute("UPDATE demo_accounts SET balance_usd = ? WHERE id = ?", (str(new_balance), account["id"]))
    add_demo_tx(db, account["id"], amount, "DEPOSIT", "Simulated USD demo deposit")
    db.commit()
    return jsonify(
        {
            "ok": True,
            "simulated": True,
            "status": "SIMULATED",
            "message": "Demo deposit recorded. This is not a real payment.",
            "amount_usd": str(amount),
            "balance_usd": str(new_balance),
            "account_kind": "DEMO",
        }
    )


@app.post("/api/real/deposit")
def real_deposit():
    amount = parse_deposit_amount((request.get_json(silent=True) or {}).get("amount_usd"))
    if amount is None:
        return json_error(f"Enter a USD amount between {MIN_DEPOSIT} and {MAX_DEPOSIT}")
    db = get_db()
    account = get_or_create_real_account(db)
    db.execute(
        """INSERT INTO real_transactions (real_account_id, amount_usd, tx_type, status, note, created_at)
           VALUES (?, ?, 'DEPOSIT_REQUEST', 'PENDING', ?, ?)""",
        (account["id"], str(amount), "Real deposit request — not an actual payment confirmation", utcnow()),
    )
    db.commit()
    return jsonify(
        {
            "ok": True,
            "simulated": False,
            "status": "PENDING",
            "message": "Real deposit request saved as pending. It does not credit real balance automatically.",
            "amount_usd": str(amount),
            "balance_usd": str(money(account["balance_usd"])),
            "account_kind": "REAL",
        }
    )


@app.post("/api/payhero/stk-push")
def payhero_stk_push():
    data = request.get_json(silent=True) or {}
    if (data.get("account") or localStorage_mode()) == "demo":
        return jsonify(
            {
                "success": False,
                "ok": False,
                "message": "M-Pesa STK is a real payment path. It cannot credit demo balances. Use a SIMULATED demo deposit instead.",
            }
        ), 400
    amount = parse_deposit_amount(data.get("amount") or data.get("amount_usd"))
    phone = "".join(ch for ch in str(data.get("phone_number") or "") if ch.isdigit())
    if not phone:
        return jsonify({"success": False, "ok": False, "message": "Phone number required"}), 400
    db = get_db()
    account = get_or_create_real_account(db)
    note = f"M-Pesa STK request for {phone} — pending, not a confirmed payment"
    if amount is not None:
        db.execute(
            """INSERT INTO real_transactions (real_account_id, amount_usd, tx_type, status, note, created_at)
               VALUES (?, ?, 'MPESA_STK_REQUEST', 'PENDING', ?, ?)""",
            (account["id"], str(amount), note, utcnow()),
        )
        db.commit()
    if not os.getenv("PAYHERO_API_KEY"):
        return jsonify(
            {
                "success": False,
                "ok": False,
                "message": "PayHero is not configured on the server. The request was stored as PENDING and did not credit any balance.",
            }
        ), 503
    return jsonify(
        {
            "success": True,
            "ok": True,
            "message": "STK request accepted for processing. Balance is not credited until a real callback confirms payment.",
        }
    )


def localStorage_mode():
    return (request.get_json(silent=True) or {}).get("account_mode") or "real"


@app.get("/api/demo/transactions")
def demo_transactions():
    db = get_db()
    account = get_or_create_demo_account(db)
    rows = db.execute(
        """SELECT id, amount_usd, tx_type, status, note, created_at
           FROM demo_transactions WHERE demo_account_id = ? ORDER BY id DESC LIMIT 100""",
        (account["id"],),
    ).fetchall()
    return jsonify(
        {
            "ok": True,
            "account_kind": "DEMO",
            "transactions": [dict(r) for r in rows],
        }
    )


@app.post("/api/demo/wager")
def demo_wager():
    amount = money((request.get_json(silent=True) or {}).get("amount_usd"))
    if amount is None or amount <= 0:
        return json_error("Invalid wager amount")
    db = get_db()
    account = get_or_create_demo_account(db)
    if not demo_enabled(account):
        return json_error("This demo account is disabled", 403)
    balance = money(account["balance_usd"])
    if amount > balance:
        return json_error("Not enough demo balance", 400)
    new_balance = balance - amount
    db.execute("UPDATE demo_accounts SET balance_usd = ? WHERE id = ?", (str(new_balance), account["id"]))
    add_demo_tx(db, account["id"], amount, "WAGER", "Simulated demo wager")
    db.commit()
    return jsonify({"ok": True, "status": "SIMULATED", "balance_usd": str(new_balance)})


@app.post("/api/demo/payout")
def demo_payout():
    amount = money((request.get_json(silent=True) or {}).get("amount_usd"))
    if amount is None or amount < 0:
        return json_error("Invalid payout amount")
    db = get_db()
    account = get_or_create_demo_account(db)
    if not demo_enabled(account):
        return json_error("This demo account is disabled", 403)
    new_balance = money(account["balance_usd"]) + amount
    db.execute("UPDATE demo_accounts SET balance_usd = ? WHERE id = ?", (str(new_balance), account["id"]))
    add_demo_tx(db, account["id"], amount, "PAYOUT", "Simulated demo cash-out")
    db.commit()
    return jsonify({"ok": True, "status": "SIMULATED", "balance_usd": str(new_balance)})


@app.post("/api/demo/reset")
def demo_reset_own():
    db = get_db()
    account = get_or_create_demo_account(db)
    if not demo_enabled(account):
        return json_error("This demo account is disabled", 403)
    db.execute("UPDATE demo_accounts SET balance_usd = ? WHERE id = ?", (str(DEMO_START_USD), account["id"]))
    add_demo_tx(db, account["id"], DEMO_START_USD, "RESET", "Player reset demo balance to $100 USD")
    db.commit()
    return jsonify({"ok": True, "status": "SIMULATED", "balance_usd": str(DEMO_START_USD)})


@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ? AND is_admin = 1", (username,)).fetchone()
    env_user = os.getenv("ADMIN_USERNAME", "admin")
    env_pass = os.getenv("ADMIN_PASSWORD", "admin123")
    ok = False
    if user and check_password_hash(user["password_hash"], password):
        ok = True
    elif username == env_user and password == env_pass:
        ok = True
        if user is None:
            db.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
                (username, generate_password_hash(password), utcnow()),
            )
            db.commit()
    if not ok:
        return json_error("Invalid admin credentials", 401)
    session["is_admin"] = True
    session["admin_username"] = username
    audit("ADMIN_LOGIN", username, "Administrator signed in")
    return jsonify({"ok": True})


@app.get("/api/admin/demo-accounts")
@admin_required
def admin_demo_accounts():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    if q:
        like = f"%{q}%"
        rows = db.execute(
            """SELECT d.id, d.balance_usd, d.is_enabled, d.created_at, d.guest_key, u.username
               FROM demo_accounts d LEFT JOIN users u ON u.id = d.user_id
               WHERE CAST(d.id AS TEXT) LIKE ? OR IFNULL(u.username,'') LIKE ? OR IFNULL(d.guest_key,'') LIKE ?
               ORDER BY d.id DESC""",
            (like, like, like),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT d.id, d.balance_usd, d.is_enabled, d.created_at, d.guest_key, u.username
               FROM demo_accounts d LEFT JOIN users u ON u.id = d.user_id
               ORDER BY d.id DESC"""
        ).fetchall()
    return jsonify({"ok": True, "accounts": [dict(r) for r in rows]})


@app.get("/api/admin/demo-accounts/<int:account_id>/transactions")
@admin_required
def admin_demo_txs(account_id):
    db = get_db()
    rows = db.execute(
        """SELECT id, amount_usd, tx_type, status, note, created_at
           FROM demo_transactions WHERE demo_account_id = ? ORDER BY id DESC""",
        (account_id,),
    ).fetchall()
    return jsonify({"ok": True, "transactions": [dict(r) for r in rows]})


@app.post("/api/admin/demo-accounts/<int:account_id>/credit")
@admin_required
def admin_credit(account_id):
    amount = parse_deposit_amount((request.get_json(silent=True) or {}).get("amount_usd"))
    if amount is None:
        return json_error("Invalid USD amount")
    return _admin_adjust(account_id, amount, "ADMIN_CREDIT", f"Admin added ${amount} demo funds")


@app.post("/api/admin/demo-accounts/<int:account_id>/debit")
@admin_required
def admin_debit(account_id):
    amount = parse_deposit_amount((request.get_json(silent=True) or {}).get("amount_usd"))
    if amount is None:
        return json_error("Invalid USD amount")
    return _admin_adjust(account_id, -amount, "ADMIN_DEBIT", f"Admin deducted ${amount} demo funds")


@app.post("/api/admin/demo-accounts/<int:account_id>/reset")
@admin_required
def admin_reset(account_id):
    db = get_db()
    account = db.execute("SELECT * FROM demo_accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        return json_error("Demo account not found", 404)
    db.execute("UPDATE demo_accounts SET balance_usd = ? WHERE id = ?", (str(DEMO_START_USD), account_id))
    add_demo_tx(db, account_id, DEMO_START_USD, "ADMIN_RESET", "Admin reset demo balance to $100 USD")
    db.commit()
    audit("DEMO_RESET", str(account_id), "Reset to $100.00 USD")
    return jsonify({"ok": True, "balance_usd": str(DEMO_START_USD)})


@app.post("/api/admin/demo-accounts/<int:account_id>/toggle")
@admin_required
def admin_toggle(account_id):
    db = get_db()
    account = db.execute("SELECT * FROM demo_accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        return json_error("Demo account not found", 404)
    new_val = 0 if account["is_enabled"] else 1
    db.execute("UPDATE demo_accounts SET is_enabled = ? WHERE id = ?", (new_val, account_id))
    db.commit()
    audit("DEMO_TOGGLE", str(account_id), f"enabled={new_val}")
    return jsonify({"ok": True, "is_enabled": bool(new_val)})


@app.get("/api/admin/audit")
@admin_required
def admin_audit():
    db = get_db()
    rows = db.execute(
        "SELECT id, admin_username, action, target, details, created_at FROM audit_log ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return jsonify({"ok": True, "entries": [dict(r) for r in rows]})


def _admin_adjust(account_id, signed_amount, tx_type, note):
    db = get_db()
    account = db.execute("SELECT * FROM demo_accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        return json_error("Demo account not found", 404)
    new_balance = money(account["balance_usd"]) + signed_amount
    if new_balance < Decimal("0.00"):
        return json_error("Insufficient demo funds to deduct")
    db.execute("UPDATE demo_accounts SET balance_usd = ? WHERE id = ?", (str(new_balance), account_id))
    add_demo_tx(db, account_id, abs(signed_amount), tx_type, note)
    db.commit()
    audit(tx_type, str(account_id), note)
    return jsonify({"ok": True, "balance_usd": str(new_balance), "status": "SIMULATED"})


@app.post("/api/signals/telegram")
def telegram_signal():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or ""
    if not token or not chat_id:
        return jsonify({"ok": False, "error": "Telegram is not configured on the server"}), 503
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return json_error("Missing signal text")
    import urllib.error
    import urllib.request

    payload = (
        f"chat_id={chat_id}&text="
        + __import__("urllib.parse").parse.quote(f"Aviator next signal: {text}")
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=8)
    except urllib.error.URLError:
        return json_error("Telegram send failed", 502)
    return jsonify({"ok": True})


os.makedirs(os.path.dirname(DB_PATH) or DATA_DIR, exist_ok=True)
init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "0") == "1")
