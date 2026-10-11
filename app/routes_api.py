"""Läs-API för andra appar (t.ex. Hemmahub) – nedräkning och valfri statistik.

Autentisering: API-nyckel i headern `Authorization: Bearer <nyckel>` eller `X-API-Key: <nyckel>`.
Nycklar visas bara en gång, lagras som SHA-256, har begränsade behörigheter och kan återkallas.
Inga nycklar i URL:en – de skulle hamna i proxy- och webbläsarloggar."""
import datetime as dt
import hmac
import os
import re

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import db as dbm
from .core import auth, client_ip, csrf_form, get_settings, log, parse_date, public_base, render, safe_log
from .security import RateLimiter, new_token, token_hash

SCOPES = {"countdown": "Nedräkning (datum, plats, dagar kvar)", "stats": "Statistik (OSA-svar, uppgifter, tal)",
          "tasks": "Att göra-lista (uppgifterna som är kvar)"}
TASKS_MAX = 50
CORS_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("API_CORS_ORIGINS", "").split(",") if o.strip()}
KEY_RE = re.compile(r"wp_[A-Za-z0-9_-]{40,60}")

API_KEY_LIMIT = RateLimiter(120, 60)     # anrop per nyckel och minut
API_FAIL_IP = RateLimiter(20, 10 * 60)   # felaktiga nycklar per IP


def _cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin", "").rstrip("/")
    if origin and origin in CORS_ORIGINS:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                "Access-Control-Allow-Headers": "Authorization, X-API-Key",
                "Access-Control-Allow-Methods": "GET, OPTIONS", "Access-Control-Max-Age": "600"}
    return {}


def _api_error(request: Request, status: int, msg: str) -> JSONResponse:
    headers = _cors_headers(request)
    if status == 401:
        headers["WWW-Authenticate"] = 'Bearer realm="api"'
    return JSONResponse({"error": msg}, status_code=status, headers=headers)


def _authenticate(request: Request):
    ip = client_ip(request)
    if API_FAIL_IP.blocked(ip):
        return None, _api_error(request, 429, "För många felaktiga försök")
    raw = request.headers.get("x-api-key", "")
    authz = request.headers.get("authorization", "")
    if not raw and authz.lower().startswith("bearer "):
        raw = authz[7:].strip()
    if not KEY_RE.fullmatch(raw or ""):
        API_FAIL_IP.hit(ip)
        return None, _api_error(request, 401, "API-nyckel saknas eller är ogiltig")
    with dbm.db() as c:
        k = c.execute("SELECT * FROM api_keys WHERE key_hash = ?", (token_hash(raw),)).fetchone()
        if not k or not hmac.compare_digest(k["key_hash"], token_hash(raw)):
            API_FAIL_IP.hit(ip)
            log.warning("api_auth_failed ip=%s", ip)
            return None, _api_error(request, 401, "API-nyckel saknas eller är ogiltig")
        if not API_KEY_LIMIT.hit(str(k["id"])):
            return None, _api_error(request, 429, "För många anrop – max 120 per minut")
        c.execute("UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ? "
                  "AND COALESCE(last_used_at,'') < datetime('now','-1 minute')", (k["id"],))
    return k, None


def countdown_payload(s: dict) -> dict:
    wd = parse_date(s.get("wedding_date"))
    now = dt.datetime.now()
    out = {
        "couple": s.get("couple_names") or None,
        "date": wd.isoformat() if wd else None,
        "time": s.get("wedding_time") or None,
        "venue": s.get("venue") or None,
        "days_left": None, "weeks_left": None, "seconds_left": None,
        "status": "unset", "label": "Inget datum satt",
        "generated_at": now.astimezone().isoformat(timespec="seconds"),
    }
    if not wd:
        return out
    days = (wd - now.date()).days
    out["days_left"] = max(days, 0)
    out["weeks_left"] = max(days, 0) // 7
    if s.get("wedding_time"):
        target = dt.datetime.combine(wd, dt.time.fromisoformat(s["wedding_time"]))
        out["datetime"] = target.astimezone().isoformat(timespec="minutes")
        out["seconds_left"] = max(int((target - now).total_seconds()), 0)
    if days > 1:
        out["status"], out["label"] = "upcoming", f"{days} dagar kvar"
    elif days == 1:
        out["status"], out["label"] = "upcoming", "I morgon!"
    elif days == 0:
        out["status"], out["label"] = "today", "Idag!"
    else:
        out["status"], out["label"] = "past", f"Gifta i {-days} dagar"
        out["days_married"] = -days
    return out


def stats_payload() -> dict:
    with dbm.db() as c:
        g = c.execute("""SELECT COALESCE(SUM(invited_count),0) AS invited,
                                COALESCE(SUM(CASE WHEN rsvp='yes' THEN attending END),0) AS attending,
                                COALESCE(SUM(CASE WHEN rsvp='no' THEN invited_count END),0) AS declined,
                                COALESCE(SUM(CASE WHEN rsvp='pending' THEN invited_count END),0) AS pending
                         FROM guests""").fetchone()
        t = c.execute("SELECT COUNT(*) AS total, COALESCE(SUM(done),0) AS done FROM tasks").fetchone()
        sp = c.execute("SELECT COUNT(*) FROM speeches WHERE status <> 'Struken'").fetchone()[0]
    return {"guests": dict(g), "tasks": {"total": t["total"], "done": t["done"],
            "percent": round(100 * t["done"] / t["total"]) if t["total"] else 0}, "speeches": sp}


def tasks_payload() -> list[dict]:
    """Uppgifterna som är kvar, i samma ordning som i appen (period, deadline).
    Saknar en uppgift deadline räknas den fram från bröllopsdatumet och perioden, som i appen."""
    from .core import add_months
    from .entities import ENTITIES, PERIOD_OFFSETS
    today = dt.date.today()
    wd = parse_date(get_settings().get("wedding_date"))
    with dbm.db() as c:
        rows = c.execute(f"SELECT id, title, period, due_date, assignee FROM tasks WHERE done=0 "
                         f"ORDER BY {ENTITIES['tasks']['order']} LIMIT ?", (TASKS_MAX,)).fetchall()
    out = []
    for r in rows:
        due = parse_date(r["due_date"]) if r["due_date"] else None
        if not due and wd and r["period"] in PERIOD_OFFSETS:
            months, days = PERIOD_OFFSETS[r["period"]]
            due = add_months(wd, months) + dt.timedelta(days=days)
        out.append({"id": r["id"], "title": r["title"], "period": r["period"] or None,
                    "due_date": due.isoformat() if due else None, "assignee": r["assignee"] or None,
                    "overdue": bool(due and due < today)})
    return out


async def api_countdown(request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers(request))
    key, err = _authenticate(request)
    if err:
        return err
    scopes = set(key["scopes"].split(","))
    if "countdown" not in scopes:
        return _api_error(request, 403, "Nyckeln saknar behörighet")
    data = countdown_payload(get_settings())
    if "stats" in scopes:
        data["stats"] = stats_payload()
    if "tasks" in scopes:
        data["tasks"] = tasks_payload()
    return JSONResponse(data, headers=_cors_headers(request))


async def api_spec(request: Request):
    """Liten självbeskrivning (ingen nyckel krävs, inga data)."""
    return JSONResponse({"name": "Bröllopsplaneraren API", "version": 1,
                         "endpoints": {"GET /api/v1/countdown": "Nedräkning (+ stats och tasks om nyckeln har de behörigheterna)"},
                         "auth": "Authorization: Bearer <api-nyckel>  eller  X-API-Key: <api-nyckel>"})


# ======================================================================= nyckelhantering (admin)
def _keys():
    with dbm.db() as c:
        return c.execute("SELECT id, name, prefix, scopes, created_by, created_at, last_used_at FROM api_keys ORDER BY id").fetchall()


async def keys_view(request: Request):
    user = auth(request, admin=True)
    new_key = None
    if request.method == "POST":
        form = await csrf_form(request, user)
        if form.get("action") == "delete":
            try:
                kid = int(form.get("id", ""))
            except ValueError:
                raise HTTPException(400)
            with dbm.db() as c:
                c.execute("DELETE FROM api_keys WHERE id = ?", (kid,))
            log.info("api_key_deleted id=%s by=%s", kid, user["username"])
            return RedirectResponse("/api-keys", 303)
        name = " ".join(str(form.get("name", "")).split())[:60]
        scopes = [s for s in SCOPES if form.get("scope_" + s) == "on"]
        if not name or "countdown" not in scopes:
            return render(request, "api_keys.html", user, status=400, keys=_keys(), scopes=SCOPES, active="api",
                          base=public_base(request), cors=sorted(CORS_ORIGINS), error="Ange ett namn.")
        new_key = "wp_" + new_token(32)
        with dbm.db() as c:
            c.execute("INSERT INTO api_keys (name, key_hash, prefix, scopes, created_by) VALUES (?,?,?,?,?)",
                      (name, token_hash(new_key), new_key[:9], ",".join(scopes), user["username"]))
        log.info("api_key_created name=%s scopes=%s by=%s", safe_log(name), scopes, user["username"])
    return render(request, "api_keys.html", user, keys=_keys(), scopes=SCOPES, new_key=new_key, active="api",
                  base=public_base(request), cors=sorted(CORS_ORIGINS),
                  example=countdown_payload(get_settings()))


routes = [
    Route("/api/v1/countdown", api_countdown, methods=["GET", "OPTIONS"]),
    Route("/api/v1", api_spec),
    Route("/api-keys", keys_view, methods=["GET", "POST"]),
]
