"""Bröllopsdagen: vad händer nu och härnäst, och talarordningen – för toastmaster och brudpar i mobilen."""
import datetime as dt
import re

from starlette.requests import Request
from starlette.routing import Route

from . import db as dbm
from .core import auth, get_settings, parse_date, render
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
                  wedding_date=wd, preview=preview, active="day")


routes = [Route("/dagen", day_view)]
