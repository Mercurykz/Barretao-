"""
Barretão Auth & Device Manager
================================
SQLite-based authentication + device registry + cross-device command queue.
"""
import hashlib
import secrets
import sqlite3
import datetime
import pathlib
from typing import Optional

DB_PATH = pathlib.Path(__file__).parent / "barretao.db"


# ── DB helpers ─────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           TEXT PRIMARY KEY,
            username     TEXT UNIQUE NOT NULL,
            display_name TEXT DEFAULT '',
            email        TEXT DEFAULT '',
            password_hash TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS devices (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'other',
            last_seen   TEXT,
            is_online   INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS pending_commands (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            to_device_id TEXT NOT NULL,
            command      TEXT NOT NULL,
            answer       TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            executed     INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS integrations (
            name         TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            config       TEXT NOT NULL DEFAULT '{}',
            connected_at TEXT NOT NULL,
            PRIMARY KEY (name, user_id)
        );
        """)


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


# ── Users ───────────────────────────────────────────────────────────────────

def user_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def register_user(username: str, password: str, email: str = "", display_name: str = "") -> Optional[dict]:
    """Returns user dict or None if username already taken."""
    user_id = secrets.token_hex(12)
    uname   = username.lower().strip()
    dname   = display_name.strip() or uname.capitalize()
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO users (id, username, display_name, email, password_hash, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, uname, dname, email, _hash(password), _now()),
            )
        return {"id": user_id, "username": uname, "display_name": dname}
    except sqlite3.IntegrityError:
        return None


def login_user(username: str, password: str) -> Optional[str]:
    """Returns session token string or None on failure."""
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM users WHERE username=? AND password_hash=?",
            (username.lower().strip(), _hash(password)),
        ).fetchone()
    if not row:
        return None
    token   = secrets.token_hex(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(days=90)).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, row["id"], _now(), expires),
        )
    return token


def get_user_by_token(token: str) -> Optional[dict]:
    """Returns user dict if token is valid, else None."""
    with _conn() as con:
        row = con.execute(
            """SELECT u.id, u.username, u.display_name, u.email
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.token=? AND s.expires_at > ?""",
            (token, _now()),
        ).fetchone()
    return dict(row) if row else None


def logout_token(token: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (token,))


def change_password(user_id: str, new_password: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (_hash(new_password), user_id),
        )
        # Invalidate all existing sessions
        con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


# ── Devices ─────────────────────────────────────────────────────────────────

_STALE_SECONDS = 90  # offline after 90s without heartbeat


def register_device(user_id: str, device_id: str, name: str, device_type: str) -> dict:
    """Upsert device record and mark online."""
    with _conn() as con:
        con.execute(
            """INSERT INTO devices (id, user_id, name, type, last_seen, is_online)
               VALUES (?,?,?,?,?,1)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 type=excluded.type,
                 last_seen=excluded.last_seen,
                 is_online=1""",
            (device_id, user_id, name, device_type, _now()),
        )
    return {"id": device_id, "name": name, "type": device_type, "is_online": True}


def heartbeat_device(device_id: str, user_id: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE devices SET last_seen=?, is_online=1 WHERE id=? AND user_id=?",
            (_now(), device_id, user_id),
        )


def _mark_stale() -> None:
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(seconds=_STALE_SECONDS)).isoformat()
    with _conn() as con:
        con.execute("UPDATE devices SET is_online=0 WHERE last_seen < ?", (cutoff,))


def get_devices(user_id: str) -> list[dict]:
    _mark_stale()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, name, type, last_seen, is_online FROM devices "
            "WHERE user_id=? ORDER BY is_online DESC, last_seen DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def rename_device(device_id: str, user_id: str, new_name: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "UPDATE devices SET name=? WHERE id=? AND user_id=?",
            (new_name.strip(), device_id, user_id),
        )
    return cur.rowcount > 0


def delete_device(device_id: str, user_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM devices WHERE id=? AND user_id=?", (device_id, user_id))
    return cur.rowcount > 0


# ── Cross-device commands ────────────────────────────────────────────────────

def queue_command(user_id: str, to_device_id: str, command: str) -> str:
    cmd_id = secrets.token_hex(8)
    with _conn() as con:
        con.execute(
            "INSERT INTO pending_commands (id, user_id, to_device_id, command, created_at) "
            "VALUES (?,?,?,?,?)",
            (cmd_id, user_id, to_device_id, command, _now()),
        )
    return cmd_id


def get_pending_commands(device_id: str, user_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT id, command, created_at FROM pending_commands
               WHERE to_device_id=? AND user_id=? AND executed=0
               ORDER BY created_at ASC""",
            (device_id, user_id),
        ).fetchall()
    return [dict(r) for r in rows]


def ack_command(cmd_id: str, answer: str = "") -> None:
    with _conn() as con:
        con.execute(
            "UPDATE pending_commands SET executed=1, answer=? WHERE id=?",
            (answer, cmd_id),
        )


# ── Integrations ─────────────────────────────────────────────────────────────

import json as _json


def save_integration(user_id: str, name: str, config: dict) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO integrations (name, user_id, config, connected_at)
               VALUES (?,?,?,?)
               ON CONFLICT(name, user_id) DO UPDATE SET
                 config=excluded.config,
                 connected_at=excluded.connected_at""",
            (name, user_id, _json.dumps(config), _now()),
        )


def get_integration(user_id: str, name: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT name, config, connected_at FROM integrations WHERE name=? AND user_id=?",
            (name, user_id),
        ).fetchone()
    if not row:
        return None
    return {"name": row["name"], "config": _json.loads(row["config"]), "connected_at": row["connected_at"]}


def list_integrations(user_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT name, config, connected_at FROM integrations WHERE user_id=? ORDER BY name",
            (user_id,),
        ).fetchall()
    return [{"name": r["name"], "config": _json.loads(r["config"]), "connected_at": r["connected_at"]} for r in rows]


def delete_integration(user_id: str, name: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM integrations WHERE name=? AND user_id=?", (name, user_id))
    return cur.rowcount > 0


# ── Autonomous helpers ────────────────────────────────────────────────────────

def get_all_users() -> list[dict]:
    """Returns all registered users (id, username, display_name)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT id, username, display_name FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_online_devices() -> list[dict]:
    """Returns all devices that sent a heartbeat in the last 5 minutes."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=5)).isoformat()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, user_id, name, type, last_seen FROM devices "
            "WHERE last_seen > ? ORDER BY last_seen DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]
