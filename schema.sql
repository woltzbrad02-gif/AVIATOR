-- SQLite schema for the Aviator demo/real ledger.
-- Demo and real money never share a balance column.

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
