"""Trycksaker: lista, redigera med förhandsvisning och skriv ut."""
import re

from markupsafe import Markup
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from . import cards as cm
from . import db as dbm
from .core import auth, csrf_form, get_settings, log, public_base, render
from .qr import QR_CENTERS, QR_STYLES, qr_svg_fancy
from .routes_mail import fill

TEXTS = ("eyebrow", "heading", "body", "footer")
DEFAULT_COPIES = {"a6": 4, "a6l": 4, "a5": 2, "a4": 1}


def _get(c, card_id: int):
    row = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def _texts(card, values: dict) -> dict:
    return {**{k: fill(card[k] or "", values) for k in TEXTS}, "mono": values.get("initialer", "")}


def _qr(card, url: str, values: dict) -> Markup:
    # SVG som vi själva genererat; initialerna escapas i qr_svg_fancy
    return Markup(qr_svg_fancy(url, card["qr_style"], card["qr_center"], values.get("initialer", "")))


def _sample(c, request: Request) -> dict:
    """Exempelvärden för förhandsvisning – aldrig en riktig gästs kod (läsare ser också förhandsvisningen)."""
    common = cm.common_values(get_settings(), public_base(request), cm.programme_text(c))
    return cm.guest_values(common, cm.SAMPLE_GUEST)


def _sample_url(request: Request) -> str:
    return f"{public_base(request)}/o/EXEMPEL"


async def cards_list(request: Request):
    user = auth(request)
    with dbm.db() as c:
        rows = c.execute("SELECT * FROM cards ORDER BY sort_no, id").fetchall()
        values = _sample(c, request)
    items = [{"card": r, "texts": _texts(r, values), "qr": _qr(r, _sample_url(request), values) if r["show_qr"] else None}
             for r in rows]
    return render(request, "cards.html", user, cards=items, kinds=cm.KINDS, can_write=user["role"] != "viewer",
                  active="cards")


async def card_new(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    kind = form.get("kind")
    if kind not in dict(cm.KINDS):
        raise HTTPException(400)
    seed = cm.seed_for(kind)
    with dbm.db() as c:
        n = c.execute("SELECT COALESCE(MAX(sort_no), 0) + 1 FROM cards").fetchone()[0]
        card_id = c.execute(
            f"INSERT INTO cards ({', '.join(cm.FIELDS)}, sort_no) VALUES ({', '.join('?' * len(cm.FIELDS))}, ?)",
            [seed[f] for f in cm.FIELDS] + [n]).lastrowid
    log.info("card_new kind=%s id=%s by=%s", kind, card_id, user["username"])
    return RedirectResponse(f"/kort/{card_id}", 303)


def _parse(form) -> tuple[dict, list[str]]:
    vals, errors = {}, []
    vals["title"] = " ".join(str(form.get("title", "")).split())[:80]
    if not vals["title"]:
        errors.append("Ge trycksaken ett namn.")
    defaults = {"paper": "vit", "qr_style": "prickar", "qr_center": "hjarta", "qr_color": "kort"}  # saknas i äldre formulär
    for name, options in (("design", cm.DESIGNS), ("color", cm.COLORS), ("paper", cm.PAPERS), ("size", cm.SIZES),
                          ("audience", cm.AUDIENCES), ("qr_style", QR_STYLES), ("qr_center", QR_CENTERS),
                          ("qr_color", cm.QR_COLORS)):
        vals[name] = str(form.get(name, "") or defaults.get(name, ""))
        if vals[name] not in dict(options):
            errors.append("Ogiltigt val.")
    vals["show_qr"] = 1 if form.get("show_qr") == "on" else 0
    for k in TEXTS:
        v = str(form.get(k, "")).replace("\r\n", "\n")
        v = v.strip() if k == "body" else " ".join(v.split())
        if len(v) > cm.LIMITS[k]:
            errors.append(f"För lång text (högst {cm.LIMITS[k]} tecken).")
        vals[k] = v[:cm.LIMITS[k]]
    return vals, errors


async def card_edit(request: Request):
    write = request.method == "POST"
    user = auth(request, write=write)
    card_id = request.path_params["card_id"]
    errors = []
    with dbm.db() as c:
        card = dict(_get(c, card_id))
        values = _sample(c, request)
    if write:
        form = await csrf_form(request, user)
        vals, errors = _parse(form)
        if not errors:
            with dbm.db() as c:
                c.execute(f"UPDATE cards SET {', '.join(f'{k} = ?' for k in vals)}, updated_at = datetime('now') WHERE id = ?",
                          [*vals.values(), card_id])
            log.info("card_saved id=%s by=%s", card_id, user["username"])
            return RedirectResponse(f"/kort/{card_id}?sparat=1", 303)
        card = {**card, **vals}
    qr = _qr(card if card.get("qr_style") in dict(QR_STYLES) else {**card, "qr_style": "prickar"}, _sample_url(request), values)
    return render(request, "card_edit.html", user, status=400 if errors else 200, card=card,
                  texts=_texts(card, values), values=values, qr=qr, qr_styles=QR_STYLES, qr_centers=QR_CENTERS,
                  qr_colors=cm.QR_COLORS, errors=errors, saved=request.query_params.get("sparat") == "1",
                  designs=cm.DESIGNS, colors=cm.COLORS, papers=cm.PAPERS, sizes=cm.SIZES, audiences=cm.AUDIENCES,
                  placeholders=cm.PLACEHOLDERS, limits=cm.LIMITS, can_write=user["role"] != "viewer", active="cards")


async def card_delete(request: Request):
    user = auth(request, write=True)
    await csrf_form(request, user)
    with dbm.db() as c:
        _get(c, request.path_params["card_id"])
        c.execute("DELETE FROM cards WHERE id = ?", (request.path_params["card_id"],))
    log.info("card_deleted id=%s by=%s", request.path_params["card_id"], user["username"])
    return RedirectResponse("/kort", 303)


async def card_print(request: Request):
    user = auth(request)
    with dbm.db() as c:
        card = _get(c, request.path_params["card_id"])
        personal = card["audience"] != "none"
        if personal and card["show_qr"] and user["role"] == "viewer":
            raise HTTPException(403)  # personliga QR-koder ger skrivrätt till gästens OSA-svar
        common = cm.common_values(get_settings(), public_base(request), cm.programme_text(c))
        guests = cm.recipients(c, card["audience"]) if personal else []
    base = public_base(request)
    sheet = []
    if personal:
        for g in guests:
            qr = _qr(card, f"{base}/o/{g['rsvp_code']}", common) if card["show_qr"] and g["rsvp_code"] else None
            sheet.append({"texts": _texts(card, cm.guest_values(common, g)), "qr": qr})
    else:
        raw = request.query_params.get("antal", "")
        n = int(raw) if re.fullmatch(r"[0-9]{1,3}", raw) and 1 <= int(raw) <= 200 else DEFAULT_COPIES[card["size"]]
        qr = _qr(card, f"{base}/osa", common) if card["show_qr"] else None
        sheet = [{"texts": _texts(card, common), "qr": qr}] * n
    log.info("card_print id=%s n=%s by=%s", card["id"], len(sheet), user["username"])
    return render(request, "card_print.html", user, card=card, sheet=sheet, personal=personal,
                  audience=dict(cm.AUDIENCES)[card["audience"]], active="cards")


async def qr_preview(request: Request):
    """Exempel-QR i vald stil för förhandsvisningen (pekar aldrig på en riktig gäst)."""
    auth(request)
    style, center = request.query_params.get("stil", ""), request.query_params.get("mitt", "")
    if style not in dict(QR_STYLES) or center not in dict(QR_CENTERS):
        raise HTTPException(400)
    with dbm.db() as c:
        values = _sample(c, request)
    return Response(qr_svg_fancy(_sample_url(request), style, center, values["initialer"]), media_type="image/svg+xml")


routes = [
    Route("/kort", cards_list),
    Route("/kort/qr.svg", qr_preview),
    Route("/kort/ny", card_new, methods=["POST"]),
    Route("/kort/{card_id:id}", card_edit, methods=["GET", "POST"]),
    Route("/kort/{card_id:id}/delete", card_delete, methods=["POST"]),
    Route("/kort/{card_id:id}/skriv-ut", card_print),
]
