"""Säkerhetskopior av databasen.

En kopia per dygn sparas i DATA_DIR/backups (de senaste BACKUP_KEEP behålls). Kopian tas med
SQLites backup-API, så den blir konsistent även medan appen skriver. Bilderna ingår inte – de
ligger redan som filer i DATA_DIR/photos och säkerhetskopieras bäst med Unraids appdata-backup."""
import os
import re
import sqlite3
import threading
import time

from . import db as dbm

BACKUP_DIR = os.path.join(dbm.DATA_DIR, "backups")
KEEP = max(1, int(os.environ.get("BACKUP_KEEP", "14")))
NAME_RE = re.compile(r"wedding-[0-9]{4}-[0-9]{2}-[0-9]{2}\.db")


def backup_to(path: str) -> None:
    src = sqlite3.connect(dbm.DB_PATH, timeout=15)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def daily_backup(day) -> str | None:
    """Tar dagens kopia om den saknas. Returnerar filnamnet om en ny kopia skapades."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"wedding-{day.isoformat()}.db"
    path = os.path.join(BACKUP_DIR, name)
    if os.path.exists(path):
        return None
    tmp = path + ".tmp"
    backup_to(tmp)
    os.replace(tmp, path)  # en halvfärdig kopia får aldrig dagens namn
    prune()
    return name


def prune() -> None:
    for name in list_backups()[KEEP:]:
        os.remove(os.path.join(BACKUP_DIR, name["name"]))


def list_backups() -> list[dict]:
    """Nyast först."""
    try:
        names = sorted((n for n in os.listdir(BACKUP_DIR) if NAME_RE.fullmatch(n)), reverse=True)
    except FileNotFoundError:
        return []
    out = []
    for n in names:
        st = os.stat(os.path.join(BACKUP_DIR, n))
        out.append({"name": n, "bytes": st.st_size, "date": n[7:17]})
    return out


def start_scheduler(today, log) -> None:
    """Bakgrundstråd som en gång i timmen ser till att dagens kopia finns."""
    def loop():
        while True:
            try:
                name = daily_backup(today())
                if name:
                    log.info("backup_created file=%s", name)
            except (OSError, sqlite3.Error) as e:
                log.error("backup_failed error=%s: %s", type(e).__name__, e)
            time.sleep(3600)

    threading.Thread(target=loop, name="backup", daemon=True).start()
