"""Users, auth tokens, guests, billing."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.database import get_conn, utc_now as _utc_now


def _migrate_users(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
    if "guest_id" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN guest_id TEXT")


def init_users_schema() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                email_verified INTEGER DEFAULT 0,
                role TEXT DEFAULT 'user',
                balance_usd TEXT DEFAULT '0',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                revoked INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guest_profiles (
                guest_id TEXT PRIMARY KEY,
                runs_started INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                guest_id TEXT,
                session_id TEXT,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                provider_cost_usd TEXT NOT NULL,
                client_cost_usd TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS balance_transactions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount_usd TEXT NOT NULL,
                tx_type TEXT NOT NULL,
                description TEXT,
                stripe_session_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        _migrate_users(conn)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_logs(user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stripe_session_unique
                ON balance_transactions(stripe_session_id)
                WHERE stripe_session_id IS NOT NULL;
            """
        )


def create_user(
    *,
    email: str | None = None,
    password_hash: str | None = None,
    google_id: str | None = None,
    email_verified: bool = False,
    role: str = "user",
    balance_usd: Decimal | None = None,
) -> dict[str, Any]:
    uid = str(uuid.uuid4())
    now = _utc_now()
    bal = str(balance_usd if balance_usd is not None else Decimal("0"))
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, google_id, email_verified, role, balance_usd, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                email.lower() if email else None,
                password_hash,
                google_id,
                1 if email_verified else 0,
                role,
                bal,
                now,
                now,
            ),
        )
    return get_user_by_id(uid) or {}


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    return dict(row) if row else None


def get_user_by_google(google_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    return dict(row) if row else None


def update_user_balance(user_id: str, new_balance: Decimal) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance_usd = ?, updated_at = ? WHERE id = ?",
            (str(new_balance.quantize(Decimal("0.000001"))), _utc_now(), user_id),
        )


def get_or_create_master_user() -> dict[str, Any]:
    email = "master@consilium.local"
    existing = get_user_by_email(email)
    if existing:
        if existing.get("role") != "master":
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET role = 'master', balance_usd = '999999999', updated_at = ? WHERE id = ?",
                    (_utc_now(), existing["id"]),
                )
        return get_user_by_id(existing["id"]) or existing
    return create_user(
        email=email,
        email_verified=True,
        role="master",
        balance_usd=Decimal("999999999"),
    )


def save_refresh_token(user_id: str, token_hash: str, expires_at: datetime) -> str:
    tid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tid, user_id, token_hash, expires_at.isoformat(), _utc_now()),
        )
    return tid


def get_refresh_token(token_hash: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ? AND revoked = 0",
            (token_hash,),
        ).fetchone()
    return dict(row) if row else None


def revoke_refresh_token(token_hash: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?", (token_hash,))


def revoke_all_refresh_tokens_for_user(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        )


def save_email_verification_token(user_id: str, token: str, expires_at: datetime) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO email_verification_tokens (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires_at.isoformat(), _utc_now()),
        )


def consume_email_verification(token: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM email_verification_tokens WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None
        exp = datetime.fromisoformat(row["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
        conn.execute("UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?", (_utc_now(), row["user_id"]))
        conn.execute("DELETE FROM email_verification_tokens WHERE token = ?", (token,))
    return row["user_id"]


def save_password_reset_token(user_id: str, token: str, expires_at: datetime) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO password_reset_tokens (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires_at.isoformat(), _utc_now()),
        )


def consume_password_reset(token: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token = ? AND used = 0", (token,)
        ).fetchone()
        if not row:
            return None
        exp = datetime.fromisoformat(row["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
        conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
    return row["user_id"]


def get_or_create_guest(guest_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM guest_profiles WHERE guest_id = ?", (guest_id,)).fetchone()
        if row:
            return dict(row)
        now = _utc_now()
        conn.execute(
            "INSERT INTO guest_profiles (guest_id, runs_started, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (guest_id, now, now),
        )
    return get_or_create_guest(guest_id)


def increment_guest_runs(guest_id: str) -> int:
    get_or_create_guest(guest_id)
    now = _utc_now()
    with get_conn() as conn:
        conn.execute(
            "UPDATE guest_profiles SET runs_started = runs_started + 1, updated_at = ? WHERE guest_id = ?",
            (now, guest_id),
        )
        row = conn.execute(
            "SELECT runs_started FROM guest_profiles WHERE guest_id = ?", (guest_id,)
        ).fetchone()
    return int(row["runs_started"]) if row else 1


def guest_runs_started(guest_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT runs_started FROM guest_profiles WHERE guest_id = ?", (guest_id,)
        ).fetchone()
    return int(row["runs_started"]) if row else 0


def record_usage(
    *,
    user_id: str | None,
    guest_id: str | None,
    session_id: str | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    provider_cost: Decimal,
    client_cost: Decimal,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO usage_logs
            (user_id, guest_id, session_id, model, prompt_tokens, completion_tokens, provider_cost_usd, client_cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                guest_id,
                session_id,
                model,
                prompt_tokens,
                completion_tokens,
                str(provider_cost),
                str(client_cost),
                _utc_now(),
            ),
        )


def deduct_balance(user_id: str, amount: Decimal, *, description: str, session_id: str | None = None) -> Decimal:
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")
    current = Decimal(user["balance_usd"])
    new_bal = (current - amount).quantize(Decimal("0.000001"))
    if new_bal < 0:
        raise ValueError("INSUFFICIENT_BALANCE")
    update_user_balance(user_id, new_bal)
    tx_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO balance_transactions (id, user_id, amount_usd, tx_type, description, created_at)
            VALUES (?, ?, ?, 'usage', ?, ?)
            """,
            (tx_id, user_id, str(-amount), description or session_id or "council run", _utc_now()),
        )
    return new_bal


def stripe_topup_exists(stripe_session_id: str) -> bool:
    if not stripe_session_id:
        return False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM balance_transactions WHERE stripe_session_id = ? LIMIT 1",
            (stripe_session_id,),
        ).fetchone()
    return row is not None


def add_balance(user_id: str, amount: Decimal, *, tx_type: str, description: str, stripe_session_id: str | None = None) -> Decimal:
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")
    if stripe_session_id and stripe_topup_exists(stripe_session_id):
        return Decimal(user["balance_usd"])
    current = Decimal(user["balance_usd"])
    new_bal = (current + amount).quantize(Decimal("0.000001"))
    update_user_balance(user_id, new_bal)
    tx_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO balance_transactions (id, user_id, amount_usd, tx_type, description, stripe_session_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tx_id, user_id, str(amount), tx_type, description, stripe_session_id, _utc_now()),
        )
    return new_bal


def list_balance_transactions(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM balance_transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def list_usage_logs(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM usage_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
