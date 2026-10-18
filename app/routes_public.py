"""Gästportalen. Allt nås via gästens personliga, ogissbara token – inga konton för gäster."""
import re

from markupsafe import Markup
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .entities import TIMELINE_ORDER
from .core import (
    MAX_UPLOAD_MB, TOKEN_RE, client_ip, flag, get_settings, log, normalize_swish, parse_date, public_base, public_rate_limit, read_form, render,
    swish_payload, sync_speech_from_guest, today,
)
from .qr import qr_svg
from .people import parse_people, people_for, save_people
from .questions import answers_for, enabled_questions, parse_answers, save_answers
from .routes_mail import notify_couple
from .security import RateLimiter, normalize_code
from .routes_photos import GREETING_MAX, GREETING_RESULTS, active_challenges, handle_upload, save_greeting, saved_count, serve_photo, visible_photos


def guest_by_token(request: Request):
    public_rate_limit(request)
    token = request.path_params["token"]
    if not TOKEN_RE.fullmatch(token):
        raise HTTPException(404)
    with dbm.db() as c:
        g = c.execute("SELECT * FROM guests WHERE rsvp_token = ?", (token,)).fetchone()
    if not g:
        raise HTTPException(404)
    return g


# ======================================================================= OSA-kod (tryckta inbjudningar)
CODE_FAIL_IP = RateLimiter(15, 15 * 60)       # felaktiga koder per IP
CODE_FAIL_GLOBAL = RateLimiter(400, 60 * 60)  # felaktiga koder totalt – stoppar gissning från många IP


def _lookup_code(request: Request, raw: str):
    """Returnerar (gäst, felmeddelande)."""
    ip = client_ip(request)
    if CODE_FAIL_IP.blocked(ip) or CODE_FAIL_GLOBAL.blocked("all"):
        log.warning("osa_code_blocked ip=%s", ip)
        return None, "För många felaktiga försök. Vänta en stund och försök igen."
    code = normalize_code(raw)
    g = None
    if code:
        with dbm.db() as c:
            g = c.execute("SELECT id, rsvp_token FROM guests WHERE rsvp_code = ?", (code,)).fetchone()
    if not g:
        CODE_FAIL_IP.hit(ip)
        CODE_FAIL_GLOBAL.hit("all")
        log.warning("osa_code_failed ip=%s", ip)
        return None, "Vi hittade ingen inbjudan med den koden. Kontrollera att du skrivit av den rätt."
    return g, None


async def osa_code(request: Request):
    public_rate_limit(request)
    error = None
    if request.method == "POST":
        form = await read_form(request)
        g, error = _lookup_code(request, str(form.get("code", "")))
        if g:
            return RedirectResponse(f"/r/{g['rsvp_token']}", 303)
    s = get_settings()
    return render(request, "osa_code.html", status=429 if error and "många" in error else (400 if error else 200),
                  settings=s, guest=None, error=error, wedding_date=parse_date(s.get("wedding_date")))


async def osa_code_link(request: Request):
    """Mål för QR-koden: /o/KOD → gästens portal."""
    public_rate_limit(request)
    g, error = _lookup_code(request, request.path_params["code"])
    if g:
        return RedirectResponse(f"/r/{g['rsvp_token']}", 303)
    s = get_settings()
    return render(request, "osa_code.html", status=404, settings=s, guest=None, error=error,
                  wedding_date=parse_date(s.get("wedding_date")))


def _portal_ctx(g, tab: str) -> dict:
    s = get_settings()
    with dbm.db() as c:
        has_gifts = (bool(c.execute("SELECT 1 FROM wishlist LIMIT 1").fetchone()) or bool(s.get("gift_info"))
                     or bool(s.get("swish_number")))
        programme = c.execute(f"SELECT time, title, location FROM timeline WHERE public = 1 ORDER BY {TIMELINE_ORDER}").fetchall()
    deadline = parse_date(s.get("rsvp_deadline"))
    return dict(settings=s, guest=g, tab=tab, base=f"/r/{g['rsvp_token']}", has_gifts=has_gifts,
                has_photos=flag(s, "photos_enabled"), programme=programme,
                wedding_date=parse_date(s.get("wedding_date")), deadline=deadline,
                closed=bool(deadline and today() > deadline), max_count=g["invited_count"] or 1)


# ======================================================================= OSA
async def rsvp(request: Request):
    g = guest_by_token(request)
    ctx = _portal_ctx(g, "rsvp")
    with dbm.db() as c:
        people = people_for(c, g)
        questions = enabled_questions(c)
        answers = answers_for(c, g["id"])
    if len(people) == 1 and not people[0]["name"]:
        people[0]["name"] = g["name"]  # ensamhushåll: förifyll med namnet på inbjudan
    ctx.update(questions=questions, answers=answers)
    if request.method == "GET":
        return render(request, "rsvp.html", saved=request.query_params.get("ok") == "1", people=people, **ctx)
    if ctx["closed"]:
        return render(request, "rsvp.html", status=403, error="Sista dag för OSA har passerat. Kontakta brudparet.",
                      people=people, **ctx)

    form = await read_form(request)
    answer = form.get("answer")
    errors = []
    if answer not in ("yes", "no"):
        errors.append("Välj om ni kommer eller inte.")
    new_people, count, new_answers = None, 0, None
    if answer == "yes":
        new_people, perr = parse_people(form, ctx["max_count"])
        errors += perr
        new_answers, aerr = parse_answers(form, questions)
        errors += aerr
        ctx["answers"] = new_answers
        count = sum(p["attending"] for p in new_people)
        if not count:
            errors.append("Kryssa i vem eller vilka som kommer.")
    song = str(form.get("song", "")).strip().replace("\n", " ").replace("\r", " ")[:200]
    message = str(form.get("message", "")).strip()[:2000]
    speech = 1 if form.get("speech") == "on" and answer == "yes" else 0
    if errors:
        return render(request, "rsvp.html", status=400, errors=errors, people=new_people or people, **ctx)
    with dbm.db() as c:
        c.execute("UPDATE guests SET rsvp=?, attending=?, song=?, message=?, speech=?, rsvp_at=datetime('now') "
                  "WHERE id = ?", (answer, count, song, message, speech, g["id"]))
        if new_people is not None:
            save_people(c, g["id"], new_people)
        if new_answers is not None:
            save_answers(c, g["id"], new_answers)
        sync_speech_from_guest(c, g["id"])
    log.info("rsvp guest_id=%s answer=%s count=%s", g["id"], answer, count)
    _notify_rsvp(request, g, answer, count, new_people, speech, song, message,
                 [(q["label"], new_answers[q["id"]]) for q in questions if new_answers and new_answers.get(q["id"])])
    return RedirectResponse(f"/r/{g['rsvp_token']}?ok=1", 303)


def _notify_rsvp(request: Request, g, answer: str, count: int, people, speech: int, song: str, message: str,
                 qa: list[tuple[str, str]] = ()) -> None:
    changed = g["rsvp"] != "pending"
    what = f"kommer ({count} av {g['invited_count']})" if answer == "yes" else "kommer inte"
    lines = [f"{g['name']} har {'ändrat sitt svar' if changed else 'svarat'}: {what}.", ""]
    for p in people or []:
        if p["attending"]:
            lines.append(f"- {p['name']}" + (f" (allergi/specialkost: {p['allergies']})" if p["allergies"] else ""))
    if qa:
        lines.append("")
        lines += [f"{label} {value}" for label, value in qa]
    if speech:
        lines.append("\nVill hålla tal.")
    if song:
        lines.append(f"\nLåtönskemål: {song}")
    if message:
        lines.append(f"\nHälsning:\n{message}")
    lines.append(f"\nSe gästen: {public_base(request)}/m/guests/{g['id']}")
    notify_couple(f"OSA: {g['name']} {what}" + (" (ändrat)" if changed else ""), "\n".join(lines))


# ======================================================================= information
async def info(request: Request):
    g = guest_by_token(request)
    with dbm.db() as c:
        faq = c.execute("SELECT question, answer FROM faq ORDER BY sort_no, id").fetchall()
    return render(request, "portal_info.html", faq=faq, **_portal_ctx(g, "info"))


# ======================================================================= önskelista
def _gifts(guest_id: int):
    with dbm.db() as c:
        return c.execute(
            """SELECT w.*,
                      (SELECT COALESCE(SUM(qty),0) FROM gift_reservations r WHERE r.gift_id = w.id) AS reserved,
                      (SELECT COALESCE(SUM(qty),0) FROM gift_reservations r WHERE r.gift_id = w.id AND r.guest_id = ?) AS mine
               FROM wishlist w ORDER BY sort_no, title COLLATE NOCASE""", (guest_id,)).fetchall()


async def gifts(request: Request):
    g = guest_by_token(request)
    ctx = _portal_ctx(g, "gifts")
    error = None
    if request.method == "POST":
        form = await read_form(request)
        raw_id = form.get("gift_id", "")
        if not re.fullmatch(r"[0-9]{1,9}", raw_id):
            raise HTTPException(400)
        gift_id = int(raw_id)
        action = form.get("action")
        with dbm.db() as c:
            c.execute("BEGIN IMMEDIATE")  # lås så två gäster inte kan ta sista exemplaret samtidigt
            w = c.execute("SELECT quantity, title FROM wishlist WHERE id = ?", (gift_id,)).fetchone()
            if not w:
                raise HTTPException(404)
            taken = c.execute("SELECT COALESCE(SUM(qty),0) FROM gift_reservations WHERE gift_id = ?", (gift_id,)).fetchone()[0]
            if action == "reserve":
                if taken >= w["quantity"]:
                    error = f"”{w['title']}” hann tyvärr bli reserverad av någon annan."
                else:
                    c.execute("INSERT INTO gift_reservations (gift_id, guest_id, qty) VALUES (?, ?, 1)", (gift_id, g["id"]))
                    log.info("gift_reserved gift=%s guest=%s", gift_id, g["id"])
            elif action == "release":
                r = c.execute("SELECT id FROM gift_reservations WHERE gift_id = ? AND guest_id = ? ORDER BY id DESC LIMIT 1",
                              (gift_id, g["id"])).fetchone()
                if r:
                    c.execute("DELETE FROM gift_reservations WHERE id = ?", (r["id"],))
                    log.info("gift_released gift=%s guest=%s", gift_id, g["id"])
            else:
                raise HTTPException(400)
        if not error:
            return RedirectResponse(f"/r/{g['rsvp_token']}/gifts#g{gift_id}", 303)
    swish = None
    number = normalize_swish(ctx["settings"].get("swish_number", ""))
    if number:
        msg = ctx["settings"].get("swish_message") or ""
        swish = {"number": f"{number[:3]}-{number[3:6]} {number[6:8]} {number[8:]}", "message": msg,
                 "qr": Markup(qr_svg(swish_payload(number, msg), "M"))}  # SVG som vi själva genererat
    return render(request, "portal_gifts.html", status=409 if error else 200, gifts=_gifts(g["id"]), error=error,
                  swish=swish, **ctx)


# ======================================================================= bilder
async def photos(request: Request):
    g = guest_by_token(request)
    ctx = _portal_ctx(g, "photos")
    if not ctx["has_photos"]:
        raise HTTPException(404)
    saved, errors = 0, []
    if request.method == "POST":
        saved, errors = await handle_upload(request, guest=g)
        if saved and not errors:
            return RedirectResponse(f"/r/{g['rsvp_token']}/photos?ok={saved}", 303)
    gr = request.query_params.get("halsning")
    return render(request, "photos_public.html", saved=saved or saved_count(request), errors=errors, challenges=active_challenges(),
                  greeting=gr if gr in GREETING_RESULTS else None, greeting_results=GREETING_RESULTS, greeting_max=GREETING_MAX,
                  photos=visible_photos() if flag(ctx["settings"], "gallery_public") else [], max_mb=MAX_UPLOAD_MB, **ctx)


async def greeting(request: Request):
    g = guest_by_token(request)
    result = await save_greeting(request, guest=g)
    return RedirectResponse(f"/r/{g['rsvp_token']}/photos?halsning={result}#gastbok", 303)


async def photo_img(request: Request):
    guest_by_token(request)
    if not flag(get_settings(), "gallery_public"):
        raise HTTPException(404)
    return serve_photo(request.path_params["file"], public=True)


routes = [
    Route("/osa", osa_code, methods=["GET", "POST"]),
    Route("/o/{code}", osa_code_link),
    Route("/r/{token}", rsvp, methods=["GET", "POST"]),
    Route("/r/{token}/info", info),
    Route("/r/{token}/gifts", gifts, methods=["GET", "POST"]),
    Route("/r/{token}/photos", photos, methods=["GET", "POST"]),
    Route("/r/{token}/img/{file}", photo_img),
    Route("/r/{token}/halsning", greeting, methods=["POST"]),
]
