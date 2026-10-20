"""Kvitton till budgetposter: fotot kodas om som bilderna från gästerna (ingen EXIF/GPS) och sparas med slumpat namn."""
import os

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from . import db as dbm
from .core import MAX_UPLOAD_MB
from .routes_photos import FILE_RE, _process_image


async def save_receipt(up) -> tuple[str | None, str | None]:
    """Returnerar (filnamn, felmeddelande). Inget foto valt → (None, None)."""
    if not isinstance(up, UploadFile) or (not up.filename and not up.size):
        return None, None
    if (up.size or 0) > MAX_UPLOAD_MB * 1024 * 1024:
        return None, f"Kvittot var större än {MAX_UPLOAD_MB} MB."
    try:
        await up.seek(0)
        info = await run_in_threadpool(_process_image, up.file, dbm.RECEIPT_DIR)
    except Exception:  # noqa: BLE001 – alla avkodningsfel behandlas lika
        return None, "Kvittot kunde inte läsas som en bild."
    return info["file"], None


def receipt_path(name: str | None, thumb: bool = False) -> str | None:
    if not name or not FILE_RE.fullmatch(name):
        return None
    path = os.path.join(dbm.RECEIPT_DIR, name.replace(".jpg", "_t.jpg") if thumb else name)
    return path if os.path.isfile(path) else None


def delete_receipt(name: str | None) -> None:
    for thumb in (False, True):
        path = receipt_path(name, thumb)
        if path:
            os.remove(path)
