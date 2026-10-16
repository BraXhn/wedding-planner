"""Säkerhetskopior: lista de automatiska kopiorna och ladda ner (bara administratörer)."""
import os
import sqlite3
import tempfile

from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route

from . import backup
from . import db as dbm
from .core import auth, log, render, today


async def backup_view(request: Request):
    user = auth(request, admin=True)
    return render(request, "backup.html", user, backups=backup.list_backups(), keep=backup.KEEP, active="backup")


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


async def backup_now(request: Request):
    """Färsk kopia att ladda ner. Inloggningssessioner tas bort ur kopian."""
    user = auth(request, admin=True)
    fd, path = tempfile.mkstemp(suffix=".db", dir=dbm.TMP_DIR)
    os.close(fd)
    backup.backup_to(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM sessions")
        conn.commit()
    finally:
        conn.close()
    log.info("backup_download kind=now by=%s", user["username"])
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=f"wedding-{today().isoformat()}.db",
                        background=BackgroundTask(_remove, path))


async def backup_file(request: Request):
    user = auth(request, admin=True)
    name = request.path_params["name"]
    path = os.path.join(backup.BACKUP_DIR, name)
    if not backup.NAME_RE.fullmatch(name) or not os.path.isfile(path):
        raise HTTPException(404)
    log.info("backup_download file=%s by=%s", name, user["username"])
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=name)


routes = [
    Route("/backup", backup_view),
    Route("/backup/now.db", backup_now),
    Route("/backup/files/{name}", backup_file),
]
