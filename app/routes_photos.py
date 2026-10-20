"""Gästernas bilduppladdning (via QR-kod på borden eller gästportalen) och administration av galleriet.

Säkerhet: varje bild avkodas och kodas om till ny JPEG med Pillow. Det tar bort EXIF (GPS-position m.m.),
neutraliserar polyglot-/skadliga filer och normaliserar storleken. Filnamn är slumpade – aldrig från användaren."""
import os
import re
import secrets
import tempfile
import threading
import warnings
import zipfile

from markupsafe import Markup
from PIL import Image, ImageOps
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .entities import TIMELINE_ORDER
from .core import (
    MAX_UPLOAD_MB, TOKEN_RE, UPLOAD_IP, auth, client_ip, csrf_form, flag, get_settings, log, parse_date, public_base,
    public_rate_limit, read_form, render, set_settings, today,
)
from .security import RateLimiter
from .qr import qr_svg, qr_svg_fancy

Image.MAX_IMAGE_PIXELS = 50_000_000      # skydd mot dekomprimeringsbomber
MAX_SIDE, THUMB_SIDE = 2560, 640
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "GIF"}
FILE_RE = re.compile(r"[0-9a-f]{32}(_t)?\.jpg")
_PROCESS_SLOTS = threading.BoundedSemaphore(2)  # max två bilder avkodas samtidigt (minne)


# ======================================================================= bildbehandling
def _process_image(src, dest_dir: str) -> dict:
    with _PROCESS_SLOTS, warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(src) as im:
            if im.format not in ALLOWED_FORMATS:
                raise ValueError("format")
            if im.format in ("JPEG", "MPO"):
                im.draft("RGB", (MAX_SIDE, MAX_SIDE))  # avkoda nedskalat – sparar minne
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            name = secrets.token_hex(16)
            main, thumb = os.path.join(dest_dir, name + ".jpg"), os.path.join(dest_dir, name + "_t.jpg")
            im.save(main + ".part", "JPEG", quality=85, optimize=True, progressive=True)  # ingen exif= → ingen metadata
            t = im.copy()
            t.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
            t.save(thumb + ".part", "JPEG", quality=78, optimize=True)
            os.replace(main + ".part", main)
            os.replace(thumb + ".part", thumb)
            return {"file": name + ".jpg", "width": im.width, "height": im.height,
                    "bytes": os.path.getsize(main) + os.path.getsize(thumb)}


def _used_bytes() -> int:
    with dbm.db() as c:
        return c.execute("SELECT COALESCE(SUM(bytes),0) FROM photos").fetchone()[0]


GREETING_IP = RateLimiter(10, 10 * 60)  # hälsningar per IP
GREETING_MAX = 280


async def save_greeting(request: Request, guest=None) -> str:
    """Sparar en hälsning från gästboken. Returnerar en kod för sidan: ok, tom, lang eller manga."""
    s = get_settings()
    if not flag(s, "photos_enabled"):
        raise HTTPException(403)
    form = await read_form(request)
    text = " ".join(str(form.get("greeting", "")).split())
    name = " ".join(str(guest["name"] if guest else form.get("name", "")).split())[:60]
    if not text:
        return "tom"
    if len(text) > GREETING_MAX:
        return "lang"
    if not GREETING_IP.hit(client_ip(request)):
        log.warning("greeting_ratelimited ip=%s", client_ip(request))
        return "manga"
    with dbm.db() as c:
        c.execute("INSERT INTO greetings (name, text, guest_id, hidden) VALUES (?,?,?,?)",
                  (name or None, text, guest["id"] if guest else None, 1 if flag(s, "photo_moderation") else 0))
    log.info("greeting_saved guest=%s", guest["id"] if guest else "-")
    return "ok"


GREETING_RESULTS = {"ok": None, "tom": "Skriv en hälsning först.", "lang": f"Hälsningen får vara högst {GREETING_MAX} tecken.",
                    "manga": "För många hälsningar på kort tid – vänta en stund."}


def visible_greetings(limit: int = 300):
    with dbm.db() as c:
        return c.execute("SELECT name, text FROM greetings WHERE hidden = 0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def _capsule_ctx(request: Request, s: dict) -> dict:
    from . import capsule as cap
    res = request.query_params.get("brev")
    return {"capsule_open": cap.is_open(s), "capsule_result": res if res in cap.RESULTS else None,
            "capsule_results": cap.RESULTS, "capsule_max": cap.CAPSULE_MAX, "capsule_date": cap.open_date()}


def active_challenges():
    with dbm.db() as c:
        return c.execute("SELECT id, text FROM challenges WHERE enabled = 1 ORDER BY sort_no, id").fetchall()


async def handle_upload(request: Request, guest=None) -> tuple[int, list[str]]:
    s = get_settings()
    if not flag(s, "photos_enabled"):
        raise HTTPException(403, "Bilduppladdning är avstängd.")
    form = await request.form(max_files=20, max_fields=10, max_part_size=16 * 1024)
    uploader = re.sub(r"[\r\n\t]", " ", str(guest["name"] if guest else form.get("name", "")))[:60].strip()
    files = [f for f in form.getlist("photos") if isinstance(f, UploadFile)]
    raw_ch = str(form.get("challenge", ""))
    challenge = int(raw_ch) if raw_ch in {str(ch["id"]) for ch in active_challenges()} else None
    quota = int(s.get("photo_quota_mb") or 5000) * 1024 * 1024
    ip = client_ip(request)
    saved, errors = 0, []
    try:
        for up in files:
            if not up.filename and not up.size:
                continue
            if not UPLOAD_IP.hit(ip):
                errors.append("För många bilder på kort tid – vänta en stund.")
                log.warning("upload_ratelimited ip=%s", ip)
                break
            if (up.size or 0) > MAX_UPLOAD_MB * 1024 * 1024:
                errors.append(f"En bild var större än {MAX_UPLOAD_MB} MB.")
                continue
            if _used_bytes() + (up.size or 0) > quota:
                errors.append("Lagringsutrymmet för bilder är fullt.")
                log.warning("photo_quota_full")
                break
            try:
                await up.seek(0)
                info = await run_in_threadpool(_process_image, up.file, dbm.PHOTO_DIR)
            except Exception as e:  # noqa: BLE001 – alla avkodningsfel behandlas lika
                errors.append("En fil kunde inte läsas som bild (JPEG, PNG, WEBP eller GIF).")
                log.info("upload_rejected ip=%s reason=%s", ip, type(e).__name__)
                continue
            with dbm.db() as c:
                c.execute("INSERT INTO photos (file, width, height, bytes, uploader, guest_id, hidden, challenge_id) "
                          "VALUES (?,?,?,?,?,?,?,?)",
                          (info["file"], info["width"], info["height"], info["bytes"], uploader or None,
                           guest["id"] if guest else None, 1 if flag(s, "photo_moderation") else 0, challenge))
            saved += 1
    finally:
        await form.close()
    if saved:
        log.info("photos_uploaded n=%s ip=%s guest=%s", saved, ip, guest["id"] if guest else "-")
    return saved, sorted(set(errors))


def saved_count(request: Request) -> int:
    """Antal sparade bilder från ?ok= efter redirect; ogiltigt värde → 0."""
    ok = request.query_params.get("ok", "")
    return int(ok) if re.fullmatch(r"[0-9]{1,3}", ok) else 0


def visible_photos(limit: int = 500):
    with dbm.db() as c:
        return c.execute("SELECT * FROM photos WHERE hidden = 0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def serve_photo(file: str, public: bool) -> FileResponse:
    if not FILE_RE.fullmatch(file):
        raise HTTPException(404)
    main = file.replace("_t.jpg", ".jpg")
    with dbm.db() as c:
        p = c.execute("SELECT hidden FROM photos WHERE file = ?", (main,)).fetchone()
    if not p or (public and p["hidden"]):
        raise HTTPException(404)
    path = os.path.join(dbm.PHOTO_DIR, file)
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def photo_token() -> str:
    s = get_settings()
    tok = s.get("photo_token")
    if not tok or not TOKEN_RE.fullmatch(tok):
        tok = secrets.token_urlsafe(18)
        set_settings({"photo_token": tok})
    return tok


def _public_programme():
    with dbm.db() as c:
        return c.execute(f"SELECT time, title, location FROM timeline WHERE public = 1 ORDER BY {TIMELINE_ORDER}").fetchall()


# ======================================================================= publik sida (QR på borden)
def _check_photo_token(request: Request) -> None:
    public_rate_limit(request)
    tok = request.path_params["token"]
    if not TOKEN_RE.fullmatch(tok) or not secrets.compare_digest(tok, photo_token()):
        raise HTTPException(404)


async def public_upload(request: Request):
    _check_photo_token(request)
    s = get_settings()
    saved, errors = 0, []
    if request.method == "POST":
        saved, errors = await handle_upload(request)
        if saved and not errors:
            return RedirectResponse(f"/p/{request.path_params['token']}?ok={saved}", 303)
    return render(request, "photos_public.html", settings=s, base=f"/p/{request.path_params['token']}",
                  guest=None, wedding_date=parse_date(s.get("wedding_date")),
                  saved=saved or saved_count(request), errors=errors, programme=_public_programme(), challenges=active_challenges(),
                  greeting=request.query_params.get("halsning") if request.query_params.get("halsning") in GREETING_RESULTS else None,
                  greeting_results=GREETING_RESULTS, greeting_max=GREETING_MAX, **_capsule_ctx(request, s),
                  photos=visible_photos() if flag(s, "gallery_public") else [], max_mb=MAX_UPLOAD_MB)


async def public_greeting(request: Request):
    _check_photo_token(request)
    result = await save_greeting(request)
    return RedirectResponse(f"/p/{request.path_params['token']}?halsning={result}#gastbok", 303)


async def public_capsule(request: Request):
    from .capsule import save_letter
    _check_photo_token(request)
    result = save_letter(await read_form(request), client_ip(request))
    return RedirectResponse(f"/p/{request.path_params['token']}?brev={result}#tidskapsel", 303)


async def public_img(request: Request):
    _check_photo_token(request)
    if not flag(get_settings(), "gallery_public"):
        raise HTTPException(404)
    return serve_photo(request.path_params["file"], public=True)


# ======================================================================= admin
async def admin_photos(request: Request):
    user = auth(request)
    with dbm.db() as c:
        photos = c.execute("SELECT p.*, g.name AS guest_name, ch.text AS challenge FROM photos p "
                           "LEFT JOIN guests g ON g.id = p.guest_id LEFT JOIN challenges ch ON ch.id = p.challenge_id "
                           "ORDER BY p.hidden DESC, p.id DESC").fetchall()
    s = get_settings()
    url = f"{public_base(request)}/p/{photo_token()}"
    used = _used_bytes()
    with dbm.db() as c:
        greetings = c.execute("SELECT * FROM greetings ORDER BY hidden DESC, id DESC").fetchall()
    return render(request, "photos_admin.html", user, settings=s, photos=photos, upload_url=url, greetings=greetings,
                  qr=Markup(qr_svg(url, "Q")), used_mb=round(used / 1024 / 1024, 1),
                  quota_mb=int(s.get("photo_quota_mb") or 5000), can_write=not user["readonly"], active="photos")


async def admin_img(request: Request):
    auth(request)
    return serve_photo(request.path_params["file"], public=False)


async def admin_photo_action(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    pid, action = request.path_params["photo_id"], form.get("action")
    with dbm.db() as c:
        p = c.execute("SELECT * FROM photos WHERE id = ?", (pid,)).fetchone()
        if not p:
            raise HTTPException(404)
        if action == "toggle":
            c.execute("UPDATE photos SET hidden = 1 - hidden WHERE id = ?", (pid,))
        elif action == "delete":
            c.execute("DELETE FROM photos WHERE id = ?", (pid,))
            for f in (p["file"], p["file"].replace(".jpg", "_t.jpg")):
                try:
                    os.remove(os.path.join(dbm.PHOTO_DIR, f))
                except FileNotFoundError:
                    pass
            log.info("photo_deleted id=%s by=%s", pid, user["username"])
        else:
            raise HTTPException(400)
    return RedirectResponse(f"/photos#p{pid}" if action == "toggle" else "/photos", 303)


async def admin_greeting(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    gid, action = request.path_params["greeting_id"], form.get("action")
    with dbm.db() as c:
        if not c.execute("SELECT 1 FROM greetings WHERE id = ?", (gid,)).fetchone():
            raise HTTPException(404)
        if action == "toggle":
            c.execute("UPDATE greetings SET hidden = 1 - hidden WHERE id = ?", (gid,))
        elif action == "delete":
            c.execute("DELETE FROM greetings WHERE id = ?", (gid,))
        else:
            raise HTTPException(400)
    log.info("greeting_%s id=%s by=%s", action, gid, user["username"])
    return RedirectResponse("/photos#halsningar", 303)


async def admin_bulk(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    action = form.get("action")
    with dbm.db() as c:
        if action == "approve_all":
            c.execute("UPDATE photos SET hidden = 0")
        elif action == "new_token":
            set_settings({"photo_token": secrets.token_urlsafe(18)})
            log.info("photo_token_rotated by=%s", user["username"])
        else:
            raise HTTPException(400)
    return RedirectResponse("/photos", 303)


async def admin_zip(request: Request):
    user = auth(request)
    with dbm.db() as c:
        photos = c.execute("SELECT file, uploader, created_at FROM photos ORDER BY id").fetchall()
    fd, path = tempfile.mkstemp(suffix=".zip", dir=dbm.TMP_DIR)
    os.close(fd)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for i, p in enumerate(photos, 1):
            src = os.path.join(dbm.PHOTO_DIR, p["file"])
            if os.path.isfile(src):
                who = re.sub(r"[^\w-]+", "_", p["uploader"] or "gast")[:30]
                z.write(src, f"{i:04d}_{who}.jpg")
    log.info("photos_zip n=%s by=%s", len(photos), user["username"])
    return FileResponse(path, media_type="application/zip", filename=f"brollopsbilder-{today().isoformat()}.zip",
                        background=BackgroundTask(os.remove, path))


async def slideshow(request: Request):
    """Helskärmsbildspel för projektor/TV på festen. Hämtar nya bilder av sig själv."""
    user = auth(request)
    url = f"{public_base(request)}/p/{photo_token()}"
    return render(request, "slideshow.html", user, public_page=True, qr=Markup(qr_svg_fancy(url, "rundad", "kamera")))


async def slideshow_json(request: Request):
    auth(request)
    with dbm.db() as c:
        ch = {r["id"]: r["text"] for r in c.execute("SELECT id, text FROM challenges")}
    return JSONResponse({"photos": [{"id": p["id"], "src": f"/photos/img/{p['file']}", "caption": ch.get(p["challenge_id"], "")}
                                    for p in visible_photos()],
                         "greetings": [{"name": g["name"] or "", "text": g["text"]} for g in visible_greetings()]})


async def table_cards(request: Request):
    user = auth(request)
    url = f"{public_base(request)}/p/{photo_token()}"
    try:
        n = max(1, min(60, int(request.query_params.get("n", "8"))))
    except ValueError:
        n = 8
    return render(request, "photo_cards.html", user, qr=Markup(qr_svg_fancy(url, "rundad", "kamera")), url=url, n=n)


routes = [
    Route("/p/{token}", public_upload, methods=["GET", "POST"]),
    Route("/p/{token}/img/{file}", public_img),
    Route("/p/{token}/halsning", public_greeting, methods=["POST"]),
    Route("/p/{token}/tidskapsel", public_capsule, methods=["POST"]),
    Route("/photos", admin_photos),
    Route("/photos/img/{file}", admin_img),
    Route("/photos/{photo_id:id}", admin_photo_action, methods=["POST"]),
    Route("/photos/bulk", admin_bulk, methods=["POST"]),
    Route("/photos/halsning/{greeting_id:id}", admin_greeting, methods=["POST"]),
    Route("/photos/all.zip", admin_zip),
    Route("/photos/cards", table_cards),
    Route("/photos/bildspel", slideshow),
    Route("/photos/bildspel.json", slideshow_json),
]
