import os
import sqlite3
from contextlib import contextmanager

from .entities import ENTITIES, TASK_SEED

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "wedding.db")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")
TMP_DIR = os.path.join(DATA_DIR, ".tmp")

_SQL_TYPE = {"int": "INTEGER", "money": "INTEGER", "bool": "INTEGER", "ref": "INTEGER"}

_CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'editor',
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    totp_secret TEXT,
    totp_last_step INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    totp_pending TEXT,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS gift_reservations (
    id INTEGER PRIMARY KEY,
    gift_id INTEGER NOT NULL,
    guest_id INTEGER NOT NULL,
    qty INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS gift_res_gift ON gift_reservations(gift_id);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    file TEXT NOT NULL UNIQUE,
    width INTEGER, height INTEGER, bytes INTEGER NOT NULL,
    uploader TEXT,
    guest_id INTEGER,
    hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS mail_log (
    id INTEGER PRIMARY KEY,
    guest_id INTEGER,
    recipient TEXT,
    kind TEXT,
    ok INTEGER,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_CORE_EXTRA = {"users": {"ics_token_hash": "TEXT"}}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_missing_columns(c, table: str, wanted: dict) -> None:
    existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    for col, typ in wanted.items():
        if col not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def init_db() -> None:
    os.umask(0o077)  # databasen och bilderna blir bara läsbara för containerns användare
    if not os.access(DATA_DIR, os.W_OK):
        raise SystemExit(
            f"Kan inte skriva till {DATA_DIR}. På Unraid: chown -R 99:100 /mnt/user/appdata/wedding-planner"
        )
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(_CORE_SCHEMA)
        for table, cols in _CORE_EXTRA.items():
            _add_missing_columns(c, table, cols)
        for table, spec in ENTITIES.items():
            c.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT (datetime('now')))"
            )
            wanted = {f["name"]: _SQL_TYPE.get(f["type"], "TEXT") for f in spec["fields"] if f["type"] != "section"}
            wanted.update(spec.get("extra_columns", {}))
            _add_missing_columns(c, table, wanted)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS guests_token ON guests(rsvp_token)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS guests_code ON guests(rsvp_code)")
        from .security import new_code, new_token
        for g in c.execute("SELECT id, rsvp_token, rsvp_code FROM guests WHERE rsvp_code IS NULL OR rsvp_token IS NULL").fetchall():
            c.execute("UPDATE guests SET rsvp_code = COALESCE(rsvp_code, ?), rsvp_token = COALESCE(rsvp_token, ?) WHERE id = ?",
                      (new_code(), new_token(24), g["id"]))
        c.execute("CREATE INDEX IF NOT EXISTS guests_table ON guests(table_id)")
        c.execute("""CREATE TABLE IF NOT EXISTS guest_people (
            id INTEGER PRIMARY KEY,
            guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
            pos INTEGER NOT NULL,
            name TEXT,
            attending INTEGER NOT NULL DEFAULT 1,
            allergies TEXT,
            UNIQUE (guest_id, pos))""")

        # migrering: gamla fritextfältet "Bord" → riktiga bord
        for row in c.execute("SELECT DISTINCT table_no FROM guests WHERE COALESCE(table_no,'') <> '' AND table_id IS NULL").fetchall():
            name = row["table_no"]
            t = c.execute("SELECT id FROM tables WHERE name = ?", (name,)).fetchone()
            tid = t["id"] if t else c.execute("INSERT INTO tables (name, seats, shape, sort_no) VALUES (?, 8, 'Runt', 0)", (name,)).lastrowid
            c.execute("UPDATE guests SET table_id = ?, table_no = NULL WHERE table_no = ?", (tid, name))

        # "Kommer" utan antal betyder att hela hushållet kommer
        c.execute("UPDATE guests SET attending = COALESCE(invited_count, 1) "
                  "WHERE rsvp = 'yes' AND COALESCE(attending, 0) = 0")

        if not c.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            c.executemany(
                "INSERT INTO tasks (title, period, done) VALUES (?, ?, 0)",
                [(t, p) for p, t in TASK_SEED],
            )
            c.execute("INSERT INTO settings (key, value) VALUES ('seeded', '1')")
