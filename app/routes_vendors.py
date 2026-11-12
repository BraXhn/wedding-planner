"""Leverantörer: delat körschema (/v/{token}), dokument (avtal och offerter som PDF) och betalningsplan."""
import datetime as dt
import os
import secrets
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import MAX_UPLOAD_MB, TOKEN_RE, auth, csrf_form, get_settings, log, parse_date, public_base, public_rate_limit, render, today
from .entities import TIMELINE_ORDER
from .security import new_token

MAX_DOCS_PER_VENDOR = 30


def _vendor(c, vid: int):
    v = c.execute("SELECT * FROM vendors WHERE id = ?", (vid,)).fetchone()
    if not v:
        raise HTTPException(404)
    return v


def vendor_extras(request: Request, c, vendor, writer: bool) -> dict:
    """Det som visas under leverantörens formulär: delad länk, dokument och betalningar."""
    docs = c.execute("SELECT id, name, bytes, created_at FROM vendor_docs WHERE vendor_id = ? ORDER BY id", (vendor["id"],)).fetchall()
    pays = c.execute("SELECT * FROM payments WHERE vendor_id = ? ORDER BY paid, due_date, id", (vendor["id"],)).fetchall()
    link = f"{public_base(request)}/v/{vendor['share_token']}" if writer and vendor["share_token"] else None
    return {"docs": docs, "payments": pays, "share_link": link, "shared": bool(vendor["share_token"]), "max_mb": MAX_UPLOAD_MB}


# ======================================================================= delat körschema
async def share_toggle(request: Request):
    user = auth(request, write=True, area="vendors")
    form = await csrf_form(request, user)
    vid = request.path_params["item_id"]
    with dbm.db() as c:
        _vendor(c, vid)
        token = None if form.get("action") == "revoke" else new_token(24)
        c.execute("UPDATE vendors SET share_token = ? WHERE id = ?", (token, vid))
    log.info("vendor_share id=%s on=%s by=%s", vid, bool(token), user["username"])
    return RedirectResponse(f"/m/vendors/{vid}#dela", 303)


async def shared_schedule(request: Request):
    """Läslänk till en leverantör: hela körschemat, men anteckningar bara för leverantörens egna punkter."""
    public_rate_limit(request)
    token = request.path_params["token"]
    if not TOKEN_RE.fullmatch(token):
        raise HTTPException(404)
    with dbm.db() as c:
        v = c.execute("SELECT id, name, category FROM vendors WHERE share_token = ?", (token,)).fetchone()
        if not v:
            raise HTTPException(404)
        items = [dict(t) for t in c.execute(f"SELECT id, time, title, location, responsible, notes, vendor_id FROM timeline "
                                            f"ORDER BY {TIMELINE_ORDER}")]
    for t in items:
        t["mine"] = t["vendor_id"] == v["id"]
        if not t["mine"]:
            t["notes"] = None
    s = get_settings()
    return render(request, "vendor_share.html", settings=s, vendor=v, schedule=items, public_page=True,
                  wedding_date=parse_date(s.get("wedding_date")))


# ======================================================================= dokument
def _save_pdf(src, dest_dir: str) -> tuple[str, int]:
    head = src.read(5)
    if head != b"%PDF-":
        raise ValueError("format")
    src.seek(0)
    name = secrets.token_hex(16) + ".pdf"
    path = os.path.join(dest_dir, name)
    size = 0
    with open(path + ".part", "wb") as out:
        while chunk := src.read(1024 * 1024):
            size += len(chunk)
            out.write(chunk)
    os.replace(path + ".part", path)
    return name, size


async def doc_upload(request: Request):
    user = auth(request, write=True, area="vendors")
    vid = request.path_params["item_id"]
    form = await request.form(max_files=1, max_fields=5, max_part_size=16 * 1024)
    await csrf_form(request, user, form)
    up = form.get("doc")
    with dbm.db() as c:
        _vendor(c, vid)
        count = c.execute("SELECT COUNT(*) FROM vendor_docs WHERE vendor_id = ?", (vid,)).fetchone()[0]
    error = None
    if not isinstance(up, UploadFile) or not up.size:
        error = "tom"
    elif up.size > MAX_UPLOAD_MB * 1024 * 1024:
        error = "stor"
    elif count >= MAX_DOCS_PER_VENDOR:
        error = "manga"
    else:
        try:
            await up.seek(0)
            file, size = await run_in_threadpool(_save_pdf, up.file, dbm.DOC_DIR)
        except ValueError:
            error = "format"
    if error:
        return RedirectResponse(f"/m/vendors/{vid}?dok={error}#dokument", 303)
    label = "".join(ch for ch in os.path.basename(up.filename or "") if ch.isprintable()).strip()[:120] or "Dokument.pdf"
    with dbm.db() as c:
        c.execute("INSERT INTO vendor_docs (vendor_id, name, file, bytes, uploaded_by) VALUES (?, ?, ?, ?, ?)",
                  (vid, label, file, size, user["username"]))
    log.info("vendor_doc_added vendor=%s bytes=%s by=%s", vid, size, user["username"])
    return RedirectResponse(f"/m/vendors/{vid}#dokument", 303)


def _doc(c, doc_id: int):
    d = c.execute("SELECT * FROM vendor_docs WHERE id = ?", (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404)
    return d


async def doc_download(request: Request):
    auth(request)
    with dbm.db() as c:
        d = _doc(c, request.path_params["doc_id"])
    path = os.path.join(dbm.DOC_DIR, d["file"])
    if not os.path.isfile(path):
        raise HTTPException(404)
    # alltid som nedladdning, aldrig öppnad i appens origin
    return FileResponse(path, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"dokument-{d['id']}.pdf\"; filename*=UTF-8''{quote(d['name'])}",
        "Cache-Control": "private, no-store"})


def delete_doc_files(c, vendor_id: int | None = None, doc_id: int | None = None) -> None:
    rows = c.execute("SELECT id, file FROM vendor_docs WHERE " + ("vendor_id = ?" if doc_id is None else "id = ?"),
                     (vendor_id if doc_id is None else doc_id,)).fetchall()
    for r in rows:
        try:
            os.remove(os.path.join(dbm.DOC_DIR, r["file"]))
        except FileNotFoundError:
            pass
        c.execute("DELETE FROM vendor_docs WHERE id = ?", (r["id"],))


async def doc_delete(request: Request):
    user = auth(request, write=True, area="vendors")
    await csrf_form(request, user)
    with dbm.db() as c:
        d = _doc(c, request.path_params["doc_id"])
        delete_doc_files(c, doc_id=d["id"])
    log.info("vendor_doc_deleted id=%s by=%s", d["id"], user["username"])
    return RedirectResponse(f"/m/vendors/{d['vendor_id']}#dokument", 303)


# ======================================================================= betalningsplan
def payment_plan(c, td: dt.date) -> dict:
    rows = [dict(r) for r in c.execute(
        "SELECT p.*, v.name AS vendor, COALESCE(v.category, 'Övrigt') AS category FROM payments p "
        "LEFT JOIN vendors v ON v.id = p.vendor_id ORDER BY p.paid, p.due_date IS NULL OR p.due_date = '', p.due_date, p.id")]
    months, cats = {}, {}
    for r in rows:
        r["amount"] = r["amount"] or 0
        r["late"] = bool(not r["paid"] and r["due_date"] and r["due_date"] < td.isoformat())
        cat = cats.setdefault(r["category"], {"total": 0, "paid": 0})
        cat["total"] += r["amount"]
        cat["paid"] += r["amount"] if r["paid"] else 0
        if not r["paid"]:
            key = r["due_date"][:7] if r["due_date"] else ""
            months[key] = months.get(key, 0) + r["amount"]
    return {"rows": rows, "months": sorted(months.items(), key=lambda kv: (kv[0] == "", kv[0])),
            "cats": sorted(cats.items()), "total": sum(r["amount"] for r in rows),
            "paid": sum(r["amount"] for r in rows if r["paid"]),
            "late": sum(r["amount"] for r in rows if r["late"])}


async def payments_view(request: Request):
    user = auth(request)
    with dbm.db() as c:
        plan = payment_plan(c, today())
    return render(request, "payments.html", user, can_write=not user["readonly"], active="budget", today=today().isoformat(), **plan)


async def payment_toggle(request: Request):
    user = auth(request, write=True, area="payments")
    await csrf_form(request, user)
    pid = request.path_params["item_id"]
    with dbm.db() as c:
        if not c.execute("UPDATE payments SET paid = 1 - COALESCE(paid, 0) WHERE id = ?", (pid,)).rowcount:
            raise HTTPException(404)
    return RedirectResponse(f"/betalningar#b{pid}", 303)


routes = [
    Route("/m/vendors/{item_id:id}/dela", share_toggle, methods=["POST"]),
    Route("/m/vendors/{item_id:id}/dokument", doc_upload, methods=["POST"]),
    Route("/dokument/{doc_id:id}", doc_download),
    Route("/dokument/{doc_id:id}/ta-bort", doc_delete, methods=["POST"]),
    Route("/v/{token}", shared_schedule),
    Route("/betalningar", payments_view),
    Route("/betalningar/{item_id:id}/betald", payment_toggle, methods=["POST"]),
]
