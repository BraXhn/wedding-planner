import os
import re
import tempfile
import time
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import backup
from . import db as dbm
from . import routes_account, routes_backup, routes_api, routes_invites, routes_calendar, routes_cards, routes_crud, routes_day, routes_mail, routes_photos, routes_public, routes_reports, routes_seating, routes_thanks
from .core import APP_VERSION, BASE, COOKIE_MODE, MAX_BODY, MAX_UPLOAD_BODY, Redirect, get_session, log, render, today
from .routes_mail import configured as smtp_configured

UPLOAD_PATH = re.compile(r"^/(p/[A-Za-z0-9_-]+|r/[A-Za-z0-9_-]+/photos)$")


async def healthz(request: Request):
    return PlainTextResponse("ok")


# ======================================================================= felhantering
async def on_redirect(request: Request, exc: Redirect):
    return RedirectResponse(exc.url, 303)


ERROR_TEXT = {400: "Felaktig förfrågan", 403: "Åtkomst nekad", 404: "Sidan finns inte", 405: "Metoden stöds inte",
              409: "Konflikt", 413: "För stor förfrågan", 415: "Fel innehållstyp",
              429: "För många förfrågningar – vänta en stund"}
_GENERIC = {"Not Found", "Forbidden", "Method Not Allowed", "Bad Request", "Too Many Requests", "Unsupported Media Type"}


async def on_http_error(request: Request, exc: HTTPException):
    detail = exc.detail if exc.detail and exc.detail not in _GENERIC else None
    return render(request, "error.html", get_session(request), status=exc.status_code,
                  code=exc.status_code, title=ERROR_TEXT.get(exc.status_code, "Något gick fel"), detail=detail)


async def on_server_error(request: Request, exc: Exception):
    log.exception("server_error path=%s", request.url.path)
    return PlainTextResponse("Internt fel", status_code=500)


# ======================================================================= säkerhetsmiddleware
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class SecurityMiddleware:
    """Ren ASGI-middleware: storleksgräns på request body + säkerhetsheaders på alla svar."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        path = scope["path"]
        limit = MAX_UPLOAD_BODY if scope["method"] == "POST" and UPLOAD_PATH.match(path) else MAX_BODY
        cl = headers.get(b"content-length")
        if cl is not None and (not cl.isdigit() or int(cl) > limit):
            return await PlainTextResponse("För stor förfrågan", 413)(scope, receive, send)
        if b"chunked" in headers.get(b"transfer-encoding", b""):
            return await PlainTextResponse("Length Required", 411)(scope, receive, send)

        # skydda även mot klienter som ljuger om content-length
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413)
            return message

        is_static = path.startswith("/static/")
        versioned = is_static and b"v=" in scope.get("query_string", b"")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                h = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"server"]
                has_cache = any(k.lower() == b"cache-control" for k, _ in h)
                h += [
                    (b"content-security-policy", CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"x-robots-tag", b"noindex, nofollow"),
                ]
                if not path.startswith("/api/"):
                    h.append((b"cross-origin-resource-policy", b"same-origin"))
                if not has_cache:
                    if versioned:    # adressen byts när filen ändras → kan cachas länge
                        cc = b"public, max-age=31536000, immutable"
                    elif is_static:  # utan version: kontrollera alltid mot servern (ETag → 304)
                        cc = b"no-cache"
                    else:
                        cc = b"no-store"
                    h.append((b"cache-control", cc))
                if scope.get("scheme") == "https" or COOKIE_MODE == "true":
                    h.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = h
            await send(message)

        await self.app(scope, limited_receive, send_wrapper)


# ======================================================================= uppstart
@asynccontextmanager
async def lifespan(app):
    dbm.init_db()
    tempfile.tempdir = dbm.TMP_DIR  # uppladdningar spoolas till disk, inte till RAM-/tmp
    routes_account.bootstrap_admin()
    backup.start_scheduler(today, log)
    log.info("Bröllopsplaneraren %s startar (COOKIE_SECURE=%s)", APP_VERSION, COOKIE_MODE)
    if COOKIE_MODE == "false":
        log.warning("COOKIE_SECURE=false – använd bara så här på ett betrott LAN, aldrig mot internet.")
    tz = os.environ.get("TZ", "")
    if tz and not os.path.exists(os.path.join("/usr/share/zoneinfo", tz.lstrip(":"))):
        log.warning("Tidszonen TZ=%s finns inte i containern – appen räknar i UTC.", tz)
    log.info("Tidszon: %s (%s)", time.tzname[0], time.strftime("%Y-%m-%d %H:%M"))
    log.info("smtp %s", "konfigurerat" if smtp_configured() else "inte konfigurerat – e-postutskick avstängt")
    yield


routes = [
    *routes_account.routes,
    *routes_backup.routes,
    *routes_invites.routes,    # före routes_crud så /m/guests/qr inte tolkas som en post
    *routes_crud.routes,
    *routes_reports.routes,
    *routes_day.routes,
    *routes_thanks.routes,
    *routes_cards.routes,
    *routes_seating.routes,
    *routes_calendar.routes,   # före routes_public så /r/{token}/brollop.ics matchar
    *routes_public.routes,
    *routes_photos.routes,
    *routes_mail.routes,
    *routes_api.routes,
    Route("/healthz", healthz),
    Mount("/static", StaticFiles(directory=str(BASE / "static")), name="static"),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(SecurityMiddleware)],
    exception_handlers={Redirect: on_redirect, HTTPException: on_http_error, Exception: on_server_error},
    lifespan=lifespan,
)
