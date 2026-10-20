"""Talarens egen sida: /t/{token}. Talaren ser när hen talar och kan ändra ämne, längd och önskemål –
inget annat. Länken ges av toastmastern (eller syns i gästportalen för den som anmält tal via OSA)."""
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import TOKEN_RE, get_settings, log, parse_date, public_rate_limit, read_form, render
from .entities import ENTITIES

MAX_MINUTES = 15


def speech_by_token(request: Request):
    public_rate_limit(request)
    token = request.path_params["token"]
    if not TOKEN_RE.fullmatch(token):
        raise HTTPException(404)
    with dbm.db() as c:
        sp = c.execute("SELECT * FROM speeches WHERE token = ? AND status <> 'Struken'", (token,)).fetchone()
    if not sp:
        raise HTTPException(404)
    return sp


def _place(sp) -> tuple[int, int]:
    with dbm.db() as c:
        ids = [r["id"] for r in c.execute(f"SELECT id FROM speeches WHERE part = ? AND status <> 'Struken' "
                                          f"ORDER BY {ENTITIES['speeches']['order']}", (sp["part"],))]
    return (ids.index(sp["id"]) + 1 if sp["id"] in ids else 0), len(ids)


async def speaker_page(request: Request):
    sp = speech_by_token(request)
    s = get_settings()
    errors, vals = [], dict(sp)
    locked = sp["status"] == "Hållen"
    if request.method == "POST" and not locked:
        form = await read_form(request)
        topic = " ".join(str(form.get("topic", "")).split())[:200]
        notes = str(form.get("notes", "")).strip()[:2000]
        try:
            minutes = int(form.get("minutes", ""))
        except ValueError:
            minutes = 0
        if not 1 <= minutes <= MAX_MINUTES:
            errors.append(f"Ange hur många minuter talet tar (1–{MAX_MINUTES}).")
        vals.update(topic=topic, notes=notes, minutes=minutes or sp["minutes"])
        if not errors:
            with dbm.db() as c:
                c.execute("UPDATE speeches SET topic = ?, minutes = ?, notes = ? WHERE id = ?",
                          (topic, minutes, notes, sp["id"]))
            log.info("speaker_updated id=%s", sp["id"])
            return RedirectResponse(f"/t/{sp['token']}?ok=1", 303)
    place, total = _place(sp)
    return render(request, "speaker.html", status=400 if errors else 200, settings=s, guest=None, sp=vals, place=place,
                  total=total, errors=errors, locked=locked, saved=request.query_params.get("ok") == "1",
                  max_minutes=MAX_MINUTES, wedding_date=parse_date(s.get("wedding_date")))


routes = [Route("/t/{token}", speaker_page, methods=["GET", "POST"])]
