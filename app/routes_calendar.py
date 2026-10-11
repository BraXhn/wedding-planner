"""iCalendar-export (RFC 5545). Tider skrivs som lokal "flytande" tid – rätt för gäster i samma tidszon."""
import datetime as dt
import hashlib

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import db as dbm
from .core import TOKEN_RE, get_settings, log, parse_date, public_rate_limit
from .security import token_hash


def _esc(s) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", ""))


def _fold(line: str) -> str:
    """Radbryt efter 75 oktetter enligt RFC 5545."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > 74:
            out.append(cur.decode())
            cur = b" " + b
        else:
            cur += b
    out.append(cur.decode())
    return "\r\n".join(out)


def _uid(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24] + "@brollopsplaneraren"


def event(uid: str, summary: str, date: dt.date, time: str | None = None, minutes: int = 60,
          location: str = "", description: str = "", alarm_days: int | None = None) -> list[str]:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"SUMMARY:{_esc(summary)}"]
    if time:
        start = dt.datetime.combine(date, dt.time.fromisoformat(time))
        end = start + dt.timedelta(minutes=minutes)
        lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}"]
    else:
        lines += [f"DTSTART;VALUE=DATE:{date:%Y%m%d}", f"DTEND;VALUE=DATE:{date + dt.timedelta(days=1):%Y%m%d}"]
    if location:
        lines.append(f"LOCATION:{_esc(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if alarm_days is not None:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(summary)}",
                  f"TRIGGER:-P{alarm_days}D", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def calendar(name: str, events: list[list[str]]) -> Response:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Brollopsplaneraren//SV", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}", "X-PUBLISHED-TTL:PT1H"]
    for ev in events:
        lines += ev
    lines.append("END:VCALENDAR")
    body = "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="brollop.ics"'})


def wedding_event(s: dict, public_only: bool) -> list[list[str]]:
    wd = parse_date(s.get("wedding_date"))
    if not wd:
        return []
    couple = s.get("couple_names") or "Bröllop"
    loc = ", ".join(x for x in (s.get("venue"), s.get("address")) if x)
    desc = "\n".join(x for x in (s.get("dress_code") and f"Klädkod: {s['dress_code']}", s.get("info_text")) if x)
    evs = [event(_uid("wedding", wd), f"Bröllop: {couple}", wd, s.get("wedding_time") or None, 600, loc, desc,
                 alarm_days=7)]
    with dbm.db() as c:
        q = "SELECT * FROM timeline" + (" WHERE public = 1" if public_only else "") + " ORDER BY time"
        for t in c.execute(q):
            evs.append(event(_uid("tl", t["id"]), t["title"], wd, t["time"], 30, t["location"] or loc,
                             "" if public_only else t["notes"] or ""))
    return evs


async def guest_ics(request: Request):
    from .routes_public import guest_by_token
    guest_by_token(request)  # validerar token + rate limit
    s = get_settings()
    return calendar(s.get("couple_names") or "Bröllop", wedding_event(s, public_only=True))


async def user_feed(request: Request):
    """Personlig prenumerationslänk: bröllopet, körschema, deadlines och obetalda räkningar."""
    public_rate_limit(request)
    token = request.path_params["token"]
    if not TOKEN_RE.fullmatch(token):
        raise HTTPException(404)
    with dbm.db() as c:
        u = c.execute("SELECT username FROM users WHERE ics_token_hash = ?", (token_hash(token),)).fetchone()
        if not u:
            raise HTTPException(404)
        tasks = c.execute("SELECT * FROM tasks WHERE done = 0 AND COALESCE(due_date,'') <> ''").fetchall()
        bills = c.execute("SELECT * FROM budget WHERE paid = 0 AND COALESCE(due_date,'') <> ''").fetchall()
    s = get_settings()
    evs = wedding_event(s, public_only=False)
    rd = parse_date(s.get("rsvp_deadline"))
    if rd:
        evs.append(event(_uid("rsvp", rd), "Sista dag för OSA", rd))
    for t in tasks:
        d = parse_date(t["due_date"])
        if d:
            evs.append(event(_uid("task", t["id"]), f"Att göra: {t['title']}", d, description=t["notes"] or "",
                             alarm_days=3))
    for b in bills:
        d = parse_date(b["due_date"])
        if d:
            amount = b["actual"] or b["estimated"]
            evs.append(event(_uid("bill", b["id"]), f"Betala: {b['item']}" + (f" ({amount} kr)" if amount else ""),
                             d, alarm_days=3))
    log.info("ics_feed user=%s events=%s", u["username"], len(evs))
    return calendar(f"Bröllopsplanering – {s.get('couple_names') or ''}".strip(" –"), evs)


routes = [
    Route("/r/{token}/brollop.ics", guest_ics),
    Route("/cal/{token}.ics", user_feed),
]
