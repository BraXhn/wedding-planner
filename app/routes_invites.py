"""QR-koder för tryckta inbjudningar.

Varje hushåll har en OSA-kod (10 tecken). QR-koden pekar på /o/KOD, och samma kod kan skrivas in
manuellt på /osa av den som inte kan skanna. Koden roteras med "Skapa ny länk" på gästen."""
import csv
import io
import re
import unicodedata
import zipfile

from markupsafe import Markup
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, get_settings, log, parse_date, public_base, render, set_settings, sv_date, today
from .routes_crud import csv_cell
from .routes_mail import fill
from .qr import qr_png, qr_svg, qr_svg_fancy
from .security import format_code


def code_url(request: Request, code: str) -> str:
    return f"{public_base(request)}/o/{code}"


def short_host(request: Request) -> str:
    return re.sub(r"^https?://", "", public_base(request))


def _guests(scope: str):
    where = {"pending": "WHERE rsvp = 'pending'", "all": ""}.get(scope, "")
    with dbm.db() as c:
        return c.execute(f"SELECT id, name, invited_count, rsvp, rsvp_code, group_name, street, postcode, city FROM guests {where} "
                         "ORDER BY group_name COLLATE NOCASE, name COLLATE NOCASE").fetchall()


_NO_DECOMPOSE = str.maketrans({"Ł": "L", "ł": "l", "Ø": "O", "ø": "o", "Đ": "D", "đ": "d", "ß": "ss",
                               "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "Þ": "Th", "þ": "th"})


def _safe_filename(i: int, name: str) -> str:
    # bara ASCII: filnamnet hamnar i Content-Disposition, som måste vara latin-1 (Ł, ć … gav 500)
    ascii_name = unicodedata.normalize("NFKD", name.translate(_NO_DECOMPOSE)).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_")[:40] or "gast"
    return f"{i:03d}_{base}"


FOOTER_MAX = 300


def footer_values(s: dict) -> dict:
    """Gemensamma platshållare för texten under koden ({namn} och {antal} sätts per kort)."""
    return {"osa_senast": sv_date(s.get("rsvp_deadline")) or "", "datum": sv_date(s.get("wedding_date")) or "",
            "brudpar": s.get("couple_names") or "", "plats": s.get("venue") or ""}


async def qr_sheet(request: Request):
    """Utskriftsark: ett A7-kort per hushåll (8 per A4). POST sparar texten under koden."""
    write = request.method == "POST"
    user = auth(request, write=True)  # läsare får inte se gästernas OSA-koder
    scope = request.query_params.get("scope", "all")
    scope = scope if scope in ("all", "pending") else "all"
    saved, error = False, None
    if write:
        form = await csrf_form(request, user)
        text = str(form.get("osa_card_footer", "")).replace("\r\n", "\n").strip()
        if len(text) > FOOTER_MAX:
            error = f"Texten får vara högst {FOOTER_MAX} tecken."
        else:
            set_settings({"osa_card_footer": text})
            saved = True
            log.info("osa_card_footer_saved by=%s", user["username"])
    s = get_settings()
    footer = s.get("osa_card_footer", "")
    if error:
        footer = str(form.get("osa_card_footer", ""))[:FOOTER_MAX * 2]
    common = footer_values(s)
    cards = [{"name": g["name"], "code": format_code(g["rsvp_code"]), "count": g["invited_count"] or 1,
              "footer": fill(footer, {**common, "namn": g["name"], "antal": str(g["invited_count"] or 1)}),
              "qr": Markup(qr_svg_fancy(code_url(request, g["rsvp_code"]), "prickar", "hjarta"))} for g in _guests(scope) if g["rsvp_code"]]
    return render(request, "invite_cards.html", user, status=400 if error else 200, settings=s, cards=cards,
                  scope=scope, host=short_host(request), footer=footer, common=common, saved=saved, error=error,
                  footer_max=FOOTER_MAX, can_write=not user["readonly"], active="guests")


async def qr_zip(request: Request):
    """QR-koder som PNG + SVG och en CSV för koppling (Word, InDesign, Canva Bulk Create)."""
    user = auth(request, write=True)
    scope = request.query_params.get("scope", "all")
    guests = [g for g in _guests(scope if scope in ("all", "pending") else "all") if g["rsvp_code"]]
    host = short_host(request)
    buf = io.BytesIO()
    rows = io.StringIO()
    w = csv.writer(rows, delimiter=";")
    w.writerow(["Namn", "Gatuadress", "Postnummer", "Ort", "Antal inbjudna", "Grupp", "OSA-kod", "OSA-länk", "Svara på", "QR-fil"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, g in enumerate(guests, 1):
            fn = _safe_filename(i, g["name"])
            url = code_url(request, g["rsvp_code"])
            z.writestr(f"png/{fn}.png", qr_png(url, "M"))
            z.writestr(f"svg/{fn}.svg", qr_svg(url, "M"))
            w.writerow([csv_cell(g["name"]), csv_cell(g["street"]), csv_cell(g["postcode"]), csv_cell(g["city"]),
                        g["invited_count"], csv_cell(g["group_name"]), format_code(g["rsvp_code"]), url,
                        f"{host}/osa", f"png/{fn}.png"])
        z.writestr("gaster.csv", "﻿" + rows.getvalue())
        z.writestr("LASMIG.txt",
                   "QR-koder för OSA\r\n\r\n"
                   "png/  – för Word, Canva m.fl. (300 dpi, minst 2 x 2 cm i tryck)\r\n"
                   "svg/  – vektorformat för tryckeri och InDesign\r\n"
                   "gaster.csv – för koppling (dokumentkoppling): namn, postadress, kod, länk och filnamn per hushåll\r\n\r\n"
                   f"Den som inte kan skanna går till {host}/osa och skriver in sin kod.\r\n")
    log.info("invite_qr_zip n=%s by=%s", len(guests), user["username"])
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="osa-qr-{today().isoformat()}.zip"'})


async def qr_single(request: Request):
    auth(request, write=True)
    fmt = request.path_params["fmt"]
    with dbm.db() as c:
        g = c.execute("SELECT name, rsvp_code FROM guests WHERE id = ?", (request.path_params["item_id"],)).fetchone()
    if not g or not g["rsvp_code"] or fmt not in ("svg", "png"):
        raise HTTPException(404)
    url = code_url(request, g["rsvp_code"])
    fn = _safe_filename(request.path_params["item_id"], g["name"])
    if fmt == "svg":
        return Response(qr_svg(url, "M"), media_type="image/svg+xml",
                        headers={"Content-Disposition": f'attachment; filename="{fn}.svg"'})
    return Response(qr_png(url, "M"), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="{fn}.png"'})


routes = [
    Route("/m/guests/qr", qr_sheet, methods=["GET", "POST"]),
    Route("/m/guests/qr.zip", qr_zip),
    Route("/m/guests/{item_id:id}/qr.{fmt}", qr_single),
]
