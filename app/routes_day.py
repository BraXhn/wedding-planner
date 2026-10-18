"""Bröllopsdagen: vad händer nu och härnäst, och talarordningen – för toastmaster och brudpar i mobilen."""
import datetime as dt
import re

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, get_settings, log, parse_date, render
from .entities import ENTITIES, NIGHT_CUTOFF, SPEECH_PARTS, TIMELINE_ORDER


def _at(wd: dt.date, time: str) -> dt.datetime:
    day = wd + dt.timedelta(days=1) if time < NIGHT_CUTOFF else wd
    return dt.datetime.combine(day, dt.time.fromisoformat(time))


async def day_view(request: Request):
    user = auth(request)
    s = get_settings()
    wd = parse_date(s.get("wedding_date"))
    now = dt.datetime.now().replace(second=0, microsecond=0)
    # ?tid=19:30 förhandsvisar hur sidan ser ut vid den tiden på bröllopsdagen
    preview = request.query_params.get("tid", "")
    if wd and re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", preview):
        now = _at(wd, preview)
    else:
        preview = ""
    with dbm.db() as c:
        items = [dict(t) for t in c.execute(f"SELECT * FROM timeline ORDER BY {TIMELINE_ORDER}")]
        speeches = c.execute(f"SELECT * FROM speeches WHERE status <> 'Struken' ORDER BY {ENTITIES['speeches']['order']}").fetchall()
    live = bool(wd) and wd <= now.date() <= wd + dt.timedelta(days=1)
    current, upcoming = None, []
    if wd:
        for t in items:
            t["at"] = _at(wd, t["time"])
            t["past"] = live and t["at"] <= now
            if t["past"]:
                current = t
            elif live and len(upcoming) < 3:
                t["in_min"] = int((t["at"] - now).total_seconds() // 60)
                upcoming.append(t)
        if current:
            current["past"] = False
    parts = []
    for part in SPEECH_PARTS:
        rows = [sp for sp in speeches if sp["part"] == part]
        if rows:
            parts.append({"part": part, "speeches": rows, "minutes": sum(sp["minutes"] or 0 for sp in rows)})
    return render(request, "day.html", user, schedule=items, current=current, upcoming=upcoming, live=live,
                  parts=parts, total_minutes=sum(sp["minutes"] or 0 for sp in speeches), now=now,
                  held=sum(1 for sp in speeches if sp["status"] == "Hållen"), n_speeches=len(speeches),
                  wedding_date=wd, preview=preview, active="day")


async def speech_done(request: Request):
    """Toastmastern bockar av ett tal. Undantag från läsarrollen: alla inloggade får växla Hållen ↔ Bekräftad
    (toastmastern har ofta en läsare-inloggning). Inget annat på talet kan ändras härifrån."""
    user = auth(request)
    await csrf_form(request, user)
    sid = request.path_params["speech_id"]
    with dbm.db() as c:
        sp = c.execute("SELECT status FROM speeches WHERE id = ?", (sid,)).fetchone()
        if not sp or sp["status"] == "Struken":
            raise HTTPException(404)
        new = "Bekräftad" if sp["status"] == "Hållen" else "Hållen"
        c.execute("UPDATE speeches SET status = ? WHERE id = ?", (new, sid))
    log.info("speech_status id=%s status=%s by=%s", sid, new, user["username"])
    return RedirectResponse(f"/dagen#tal{sid}", 303)


routes = [
    Route("/dagen", day_view),
    Route("/dagen/tal/{speech_id:id}", speech_done, methods=["POST"]),
]
