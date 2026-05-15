import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.config import DATA_DIR, resolved_db_path
from app.model_registry import CouncilModelConfig
from app.models import AgentMessage, Phase


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now() -> str:
    return utc_now()


@contextmanager
def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "council_config" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN council_config TEXT")


def init_db() -> None:
    from app.users_db import init_users_schema

    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                goal TEXT,
                attachments_context TEXT,
                phase TEXT,
                verdict_version INTEGER DEFAULT 1,
                council_config TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                round INTEGER DEFAULT 0,
                content TEXT NOT NULL,
                model TEXT,
                verdict_version INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS verdicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS user_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                verdict_version_after INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT,
                stored_path TEXT NOT NULL,
                extracted_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            """
        )
        _migrate(conn)
    init_users_schema()


def create_session(
    prompt: str,
    goal: str = "",
    attachments_context: str = "",
    council_config: CouncilModelConfig | None = None,
    *,
    user_id: str | None = None,
    guest_id: str | None = None,
) -> str:
    sid = str(uuid.uuid4())
    now = _utc_now()
    cfg = council_config.to_json() if council_config else None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, prompt, goal, attachments_context, phase, council_config, user_id, guest_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sid, prompt, goal, attachments_context, Phase.INDEPENDENT.value, cfg, user_id, guest_id, now, now),
        )
    return sid


def save_council_config(session_id: str, council: CouncilModelConfig) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET council_config = ?, updated_at = ? WHERE id = ?",
            (council.to_json(), _utc_now(), session_id),
        )


def load_council_config(session_id: str) -> CouncilModelConfig:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT council_config FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if not row or not row["council_config"]:
        return CouncilModelConfig()
    return CouncilModelConfig.from_json(row["council_config"])


def update_session_meta(
    session_id: str,
    *,
    phase: str | None = None,
    verdict_version: int | None = None,
    attachments_context: str | None = None,
) -> None:
    now = _utc_now()
    with get_conn() as conn:
        if phase is not None:
            conn.execute(
                "UPDATE sessions SET phase = ?, updated_at = ? WHERE id = ?",
                (phase, now, session_id),
            )
        if verdict_version is not None:
            conn.execute(
                "UPDATE sessions SET verdict_version = ?, updated_at = ? WHERE id = ?",
                (verdict_version, now, session_id),
            )
        if attachments_context is not None:
            conn.execute(
                "UPDATE sessions SET attachments_context = ?, updated_at = ? WHERE id = ?",
                (attachments_context, now, session_id),
            )


def save_message(session_id: str, msg: AgentMessage, verdict_version: int = 1) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages (session_id, agent_id, phase, round, content, model, verdict_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                msg.agent_id.value,
                msg.phase.value,
                msg.round,
                msg.content,
                msg.model,
                verdict_version,
                _utc_now(),
            ),
        )


def save_verdict(session_id: str, content: str, version: int) -> None:
    now = _utc_now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO verdicts (session_id, version, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, version, content, now),
        )
        conn.execute(
            "UPDATE sessions SET phase = ?, verdict_version = ?, updated_at = ? WHERE id = ?",
            (Phase.COMPLETE.value, version, now, session_id),
        )


def save_user_comment(session_id: str, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO user_comments (session_id, content, created_at) VALUES (?, ?, ?)",
            (session_id, content, _utc_now()),
        )
        return int(cur.lastrowid)


def save_attachment(
    session_id: str,
    filename: str,
    mime_type: str,
    stored_path: str,
    extracted_text: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO attachments (session_id, filename, mime_type, stored_path, extracted_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, filename, mime_type, stored_path, extracted_text, _utc_now()),
        )


def load_session(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        messages = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        verdicts = conn.execute(
            "SELECT * FROM verdicts WHERE session_id = ? ORDER BY version", (session_id,)
        ).fetchall()
        comments = conn.execute(
            "SELECT * FROM user_comments WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        attachments = conn.execute(
            "SELECT * FROM attachments WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    data = {
        "session": dict(row),
        "messages": [dict(m) for m in messages],
        "verdicts": [dict(v) for v in verdicts],
        "comments": [dict(c) for c in comments],
        "attachments": [dict(a) for a in attachments],
    }
    if data["session"].get("council_config"):
        try:
            data["council_config"] = json.loads(data["session"]["council_config"])
        except json.JSONDecodeError:
            data["council_config"] = {}
    return data


def list_sessions(
    limit: int = 50,
    *,
    user_id: str | None = None,
    guest_id: str | None = None,
) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT id, prompt, phase, verdict_version, created_at, updated_at
                FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        elif guest_id:
            rows = conn.execute(
                """
                SELECT id, prompt, phase, verdict_version, created_at, updated_at
                FROM sessions WHERE guest_id = ? ORDER BY updated_at DESC LIMIT ?
                """,
                (guest_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, prompt, phase, verdict_version, created_at, updated_at
                FROM sessions ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def messages_to_state(data: dict[str, Any]) -> list[AgentMessage]:
    from app.models import AgentId

    out: list[AgentMessage] = []
    for m in data.get("messages", []):
        try:
            aid = AgentId(m["agent_id"])
        except ValueError:
            if m["agent_id"] == "owl":
                aid = AgentId.DIATOR
            else:
                continue
        out.append(
            AgentMessage(
                agent_id=aid,
                phase=Phase(m["phase"]),
                round=m["round"] or 0,
                content=m["content"],
                model=m["model"] or "",
            )
        )
    return out
