"""Gemensamma delar: konfiguration, mallar, sessioner/behörighet, validering och hjälpfunktioner."""
import calendar
import datetime as dt
import hashlib
import hmac
import logging
import os
import re
import time
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.convertors import Convertor, register_url_convertor
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from . import db as dbm
from .entities import ENTITIES, SETTINGS_DEFAULTS
from .security import RateLimiter, new_token, token_hash


class IdConvertor(Convertor):
    """Som {x:int} men max 18 siffror – större tal får SQLite att kasta OverflowError (500)."""
    regex = "[0-9]{1,18}"

    def convert(self, value: str) -> int:
        return int(value)

    def to_string(self, value: int) -> str:
        return str(int(value))


register_url_convertor("id", IdConvertor())  # måste ske innan routes_*-modulerna bygger sina Route

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wedding")

BASE = Path(__file__).parent
# auto (standard): säker __Host-cookie när förfrågan kom via HTTPS (från betrodd proxy), annars vanlig
# cookie så att direkt LAN-åtkomst över http fungerar. true: kräv alltid HTTPS. false: aldrig Secure.
COOKIE_MODE = os.environ.get("COOKIE_SECURE", "auto").strip().lower()
if COOKIE_MODE not in ("auto", "true", "false"):
    COOKIE_MODE = "auto"
APP_VERSION = os.environ.get("APP_VERSION", "dev")
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))
IDLE_MINUTES = int(os.environ.get("SESSION_IDLE_MINUTES", "120"))
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
MAX_BODY = 256 * 1024
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))       # per bild
MAX_UPLOAD_BODY = int(os.environ.get("MAX_UPLOAD_REQUEST_MB", "120")) * 1024 * 1024  # per förfrågan
ROLES = [("admin", "Administratör"), ("editor", "Redigerare"), ("viewer", "Läsare")]

LOGIN_IP = RateLimiter(10, 15 * 60)      # misslyckade inloggningar per IP
LOGIN_USER = RateLimiter(5, 15 * 60)     # misslyckade inloggningar per användarnamn
PUBLIC_IP = RateLimiter(120, 10 * 60)    # anrop mot publika token-sidor per IP
UPLOAD_IP = RateLimiter(80, 10 * 60)     # uppladdade bilder per IP
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")

templates = Jinja2Templates(directory=str(BASE / "templates"))


class Redirect(Exception):
    def __init__(self, url: str):
        self.url = url


# ======================================================================= små hjälpare
def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers ersätter client med X-Forwarded-For – men bara från TRUSTED_PROXIES
    return request.client.host if request.client else "unknown"


def safe_log(s) -> str:
    return re.sub(r"[^\w.@-]", "?", str(s))[:64]


def get_settings() -> dict:
    with dbm.db() as c:
        stored = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}
    return {**SETTINGS_DEFAULTS, **stored}


def set_settings(values: dict) -> None:
    with dbm.db() as c:
        c.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, "" if v is None else str(v)) for k, v in values.items()],
        )


def flag(settings: dict, key: str) -> bool:
    return settings.get(key) == "1"


def today() -> dt.date:
    return dt.date.today()


def parse_date(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def add_months(d: dt.date, months: int) -> dt.date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti",
          "september", "oktober", "november", "december"]


def sv_date(d, year: bool = True, short: bool = False) -> str:
    if isinstance(d, str):
        d = parse_date(d)
    if not d:
        return ""
    m = MONTHS[d.month - 1][:3] if short else MONTHS[d.month - 1]
    return f"{d.day} {m}" + (f" {d.year}" if year else "")


def kr(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ") + " kr"


def display(f: dict, v, refs: dict | None = None):
    if v is None or v == "":
        return ""
    t = f["type"]
    if t == "bool":
        return "✓" if v else ""
    if t == "money":
        return kr(v)
    if t == "select":
        return dict(f["options"]).get(v, v)
    if t == "date":
        return sv_date(v, short=True) or v
    if t == "ref":
        return (refs or {}).get(f["ref"], {}).get(v, "")
    return v


def load_refs(spec: dict) -> dict:
    """Hämtar id→namn för alla ref-fält i en entitet (t.ex. bord för gäster)."""
    out = {}
    with dbm.db() as c:
        for f in spec["fields"]:
            if f["type"] == "ref" and f["ref"] not in out:
                ref_spec = ENTITIES[f["ref"]]
                label = ref_spec["fields"][0]["name"]
                out[f["ref"]] = {r["id"]: r[label] for r in c.execute(
                    f"SELECT id, {label} FROM {f['ref']} ORDER BY {ref_spec['order']}")}
    return out


def cookie_secure(request: Request) -> bool:
    if COOKIE_MODE == "auto":
        return request.url.scheme == "https"
    return COOKIE_MODE == "true"


def cookie_name(request: Request) -> str:
    return "__Host-wp_session" if cookie_secure(request) else "wp_session"


def public_base(request: Request) -> str:
    return BASE_URL or str(request.base_url).rstrip("/")


_ASSET_VERSIONS: dict[str, str] = {}


def asset(path: str) -> str:
    """URL till en statisk fil med innehållshash, t.ex. /static/style.css?v=3f9a1c… – byts automatiskt
    när filen ändras, så webbläsare och Cloudflare aldrig visar en gammal version efter en uppdatering."""
    if path not in _ASSET_VERSIONS:
        try:
            _ASSET_VERSIONS[path] = hashlib.sha256((BASE / "static" / path).read_bytes()).hexdigest()[:12]
        except OSError:
            _ASSET_VERSIONS[path] = APP_VERSION
    return f"/static/{path}?v={_ASSET_VERSIONS[path]}"


templates.env.globals.update(asset=asset)
templates.env.globals.update(display=display, kr=kr, sv_date=sv_date, ENTITIES=ENTITIES, flag=flag,
                             APP_VERSION=APP_VERSION)


def render(request: Request, name: str, user=None, status: int = 200, **ctx) -> Response:
    ctx.setdefault("settings", get_settings())
    ctx.update(user=user)
    return templates.TemplateResponse(request, name, ctx, status_code=status)


# ======================================================================= validering
def parse_form(fields: list, form, refs: dict | None = None) -> tuple[dict, list]:
    vals, errors = {}, []
    for f in fields:
        name, t, label = f["name"], f["type"], f["label"]
        if t == "section":
            continue
        raw = form.get(name)
        if t == "bool":
            vals[name] = 1 if raw in ("on", "1", "true") else 0
            continue
        raw = raw.strip() if isinstance(raw, str) else ""
        if not raw:
            if f.get("required"):
                errors.append(f"{label} måste fyllas i.")
            if t == "int":
                vals[name] = f.get("default", 0)
            elif t in ("money", "ref"):
                vals[name] = None
            elif t == "select":
                vals[name] = f.get("default", f["options"][0][0])
            else:
                vals[name] = ""
            continue
        try:
            if t == "textarea":
                if len(raw) > 4000:
                    raise ValueError("för lång text")
                vals[name] = raw.replace("\r\n", "\n")
            elif t in ("text", "email", "url"):
                if len(raw) > 200 or "\n" in raw or "\r" in raw:
                    raise ValueError("för lång text")
                if t == "email" and not re.fullmatch(r"[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+", raw):
                    raise ValueError("ogiltig e-postadress")
                if t == "url" and not re.fullmatch(r"https?://[^\s<>\"']+", raw):
                    raise ValueError("måste börja med https://")
                vals[name] = raw
            elif t == "int":
                n = int(raw)
                if not (f.get("min", 0) <= n <= f.get("max", 100_000)):
                    raise ValueError(f"ska vara mellan {f.get('min', 0)} och {f.get('max', 100_000)}")
                vals[name] = n
            elif t == "money":
                x = float(raw.replace(" ", "").replace(" ", "").replace("kr", "").replace(",", "."))
                if not 0 <= x <= 1_000_000_000:  # stoppar även inf och nan
                    raise ValueError("orimligt belopp")
                vals[name] = round(x)
            elif t == "date":
                d = dt.date.fromisoformat(raw)
                if not 1900 <= d.year <= 2100:  # annars kraschar deadline-beräkningen (år 0 / 10000)
                    raise ValueError("orimligt datum")
                vals[name] = d.isoformat()
            elif t == "time":
                if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", raw):
                    raise ValueError("ange tid som HH:MM")
                vals[name] = raw
            elif t == "select":
                if raw not in dict(f["options"]):
                    raise ValueError("ogiltigt val")
                vals[name] = raw
            elif t == "ref":
                n = int(raw)
                if n not in (refs or {}).get(f["ref"], {}):
                    raise ValueError("ogiltigt val")
                vals[name] = n
        except ValueError as e:
            msg = str(e) if str(e) and not str(e).startswith(("invalid", "could not", "Invalid")) else "ogiltigt värde"
            errors.append(f"{label}: {msg}.")
            vals[name] = raw
    return vals, errors


async def read_form(request: Request):
    return await request.form(max_files=0, max_fields=100, max_part_size=64 * 1024)


# ======================================================================= sessioner & behörighet
def get_session(request: Request) -> dict | None:
    tok = request.cookies.get(cookie_name(request))
    if not tok or len(tok) > 100:
        return None
    th, now = token_hash(tok), int(time.time())
    with dbm.db() as c:
        row = c.execute(
            "SELECT s.*, u.username, u.role, u.must_change_pw, u.totp_secret IS NOT NULL AS has_totp, "
            "u.ics_token_hash IS NOT NULL AS has_ics "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (th,)
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] < now or row["last_seen"] + IDLE_MINUTES * 60 < now:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
            return None
        if now - row["last_seen"] > 60:
            c.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now, th))
        return dict(row)


def auth(request: Request, write: bool = False, admin: bool = False) -> dict:
    s = get_session(request)
    if not s:
        raise Redirect("/login")
    if s["must_change_pw"] and request.url.path not in ("/account", "/account/password", "/logout"):
        raise Redirect("/account")
    if (write and s["role"] == "viewer") or (admin and s["role"] != "admin"):
        raise HTTPException(403)
    return s


def _csrf_fail(request: Request, user: dict):
    log.warning("csrf_failed ip=%s user=%s", client_ip(request), user["username"])
    raise HTTPException(403, "Ogiltig eller utgången formulärtoken. Ladda om sidan och försök igen.")


async def csrf_form(request: Request, user: dict, form=None):
    form = form if form is not None else await read_form(request)
    if not hmac.compare_digest(str(form.get("csrf", "")).encode(), user["csrf"].encode()):
        _csrf_fail(request, user)
    return form


def csrf_header(request: Request, user: dict) -> None:
    """För fetch()-anrop: token i header + krav på JSON (kan inte skickas av ett vanligt formulär)."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415)
    if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), user["csrf"].encode()):
        _csrf_fail(request, user)


def set_session_cookie(resp: Response, token: str, request: Request) -> None:
    resp.set_cookie(cookie_name(request), token, max_age=SESSION_HOURS * 3600, httponly=True,
                    secure=cookie_secure(request), samesite="strict", path="/")


def create_session(c, user_id: int) -> str:
    token, now = new_token(), int(time.time())
    c.execute("DELETE FROM sessions WHERE expires_at < ? OR last_seen < ?", (now, now - IDLE_MINUTES * 60))
    c.execute(
        "INSERT INTO sessions (token_hash, user_id, csrf, created_at, last_seen, expires_at) VALUES (?,?,?,?,?,?)",
        (token_hash(token), user_id, new_token(), now, now, now + SESSION_HOURS * 3600),
    )
    return token


def public_rate_limit(request: Request) -> None:
    if not PUBLIC_IP.hit(client_ip(request)):
        log.warning("public_ratelimited ip=%s path=%s", client_ip(request), safe_log(request.url.path))
        raise HTTPException(429)


# ======================================================================= domänlogik som delas
SWISH_MSG_RE = re.compile(r"[0-9A-Za-zÅÄÖåäö!?(),.:\"@ -]{0,50}")  # Swish tillåtna tecken, utan ;


def normalize_swish(raw: str) -> str | None:
    """"070-123 45 67", "+46701234567" → "0701234567"; Swish-nummer 123xxxxxxx. None om ogiltigt."""
    n = re.sub(r"[\s-]", "", raw or "")
    if n.startswith("+46"):
        n = "0" + n[3:]
    return n if re.fullmatch(r"07[0-9]{8}|(123|900)[0-9]{7}", n) else None


def swish_payload(number: str, message: str) -> str:
    """Innehållet i en förifylld Swish-QR: C<mottagare>;<belopp>;<meddelande>;<redigerbart>.
    Sista fältet är en bitmask för vad betalaren får ändra (1 mottagare, 2 belopp, 4 meddelande):
    6 = mottagaren är låst, belopp och meddelande går att ändra. Beloppet lämnas tomt."""
    return f"C{number};;{message};6"


def period_deadline(wd: dt.date, period: str) -> dt.date:
    from .entities import PERIOD_OFFSETS
    months, days = PERIOD_OFFSETS.get(period, (0, 0))
    return add_months(wd, months) + dt.timedelta(days=days)


def fill_task_deadlines(only_empty: bool = True) -> int:
    """Sätter deadlines på uppgifter utifrån bröllopsdatum och tidsperiod."""
    wd = parse_date(get_settings().get("wedding_date"))
    if not wd:
        return 0
    n = 0
    with dbm.db() as c:
        rows = c.execute("SELECT id, period, due_date FROM tasks").fetchall()
        for r in rows:
            if only_empty and r["due_date"]:
                continue
            c.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (period_deadline(wd, r["period"]).isoformat(), r["id"]))
            n += 1
    return n


def move_task_deadlines(old: dt.date, new: dt.date) -> int:
    """Nytt bröllopsdatum: flyttar deadlines som räknats fram från det gamla datumet.
    Deadlines som någon satt själv (avviker från det uträknade) lämnas orörda."""
    n = 0
    with dbm.db() as c:
        for r in c.execute("SELECT id, period, due_date FROM tasks WHERE COALESCE(due_date,'') <> ''").fetchall():
            if r["due_date"] == period_deadline(old, r["period"]).isoformat():
                c.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (period_deadline(new, r["period"]).isoformat(), r["id"]))
                n += 1
    return n


def sync_speech_from_guest(c, guest_id: int) -> None:
    """Gäst som anmält tal via OSA → rad i talarlistan (och tvärtom stryks om de ångrar sig)."""
    g = c.execute("SELECT id, name, speech, rsvp FROM guests WHERE id = ?", (guest_id,)).fetchone()
    if not g:
        return
    existing = c.execute("SELECT id, status FROM speeches WHERE guest_id = ?", (guest_id,)).fetchone()
    wants = bool(g["speech"]) and g["rsvp"] != "no"
    if wants and not existing:
        c.execute("INSERT INTO speeches (speaker, guest_id, part, order_no, minutes, status) "
                  "VALUES (?, ?, 'Under varmrätten', 0, 5, 'Anmäld')", (g["name"], guest_id))
    elif wants and existing and existing["status"] == "Struken":
        c.execute("UPDATE speeches SET status = 'Anmäld' WHERE id = ?", (existing["id"],))
    elif not wants and existing and existing["status"] == "Anmäld":
        c.execute("UPDATE speeches SET status = 'Struken' WHERE id = ?", (existing["id"],))
