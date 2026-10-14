"""E-postutskick: inbjudningar med personlig OSA-länk och påminnelser till dem som inte svarat.

Skickas i en bakgrundstråd (en körning i taget) med kort paus mellan mejlen så att SMTP-servern inte
spärrar kontot. Mallarna fylls i med enkel strängersättning – aldrig str.format – så att en mall inte
kan läsa ut interna objekt."""
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .security import format_code
from .core import auth, csrf_form, get_settings, log, public_base, render, safe_log, sv_date

SMTP = {
    "host": os.environ.get("SMTP_HOST", ""),
    "port": int(os.environ.get("SMTP_PORT", "587")),
    "user": os.environ.get("SMTP_USER", ""),
    "password": os.environ.get("SMTP_PASSWORD", ""),
    "from": os.environ.get("SMTP_FROM", ""),
    "from_name": os.environ.get("SMTP_FROM_NAME", ""),
    "security": os.environ.get("SMTP_SECURITY", "starttls").lower(),  # starttls | ssl | none
}
DELAY = float(os.environ.get("SMTP_DELAY_SECONDS", "1.5"))

_job_lock = threading.Lock()
_job = {"running": False, "kind": None, "total": 0, "sent": 0, "failed": 0, "started": None, "finished": None}


def configured() -> bool:
    return bool(SMTP["host"] and SMTP["from"])


def fill(template: str, values: dict) -> str:
    out = template or ""
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def _values(s: dict, guest, base: str) -> dict:
    return {
        "namn": guest["name"] if guest else "Testmottagare",
        "länk": f"{base}/r/{guest['rsvp_token']}" if guest else f"{base}/r/exempel",
        "brudpar": s.get("couple_names") or "",
        "datum": sv_date(s.get("wedding_date")) or "",
        "plats": s.get("venue") or "",
        "osa_senast": sv_date(s.get("rsvp_deadline")) or "så snart ni kan",
        "kod": format_code(guest["rsvp_code"]) if guest and guest["rsvp_code"] else "ABCDE-FGH23",
        "osa_adress": f"{base}/osa",
    }


def build_message(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()  # vägrar radbrytningar i headers → ingen header-injektion
    msg["From"] = formataddr((SMTP["from_name"], SMTP["from"])) if SMTP["from_name"] else SMTP["from"]
    msg["To"] = to
    msg["Subject"] = " ".join(subject.split())[:200]
    msg["Message-ID"] = make_msgid(domain=SMTP["from"].split("@")[-1])
    msg.set_content(body)
    return msg


def _connect():
    ctx = ssl.create_default_context()
    if SMTP["security"] == "ssl":
        server = smtplib.SMTP_SSL(SMTP["host"], SMTP["port"], timeout=30, context=ctx)
    else:
        server = smtplib.SMTP(SMTP["host"], SMTP["port"], timeout=30)
        if SMTP["security"] == "starttls":
            server.starttls(context=ctx)
    if SMTP["user"]:
        server.login(SMTP["user"], SMTP["password"])
    return server


def _select_guests(kind: str, scope: str):
    where = "COALESCE(email,'') <> ''"
    if kind == "invite":
        if scope != "all":
            where += " AND invite_sent_at IS NULL"
    else:
        where += " AND rsvp = 'pending'"
    with dbm.db() as c:
        return c.execute(f"SELECT * FROM guests WHERE {where} ORDER BY name COLLATE NOCASE").fetchall()


def _run_job(kind: str, guests, base: str, actor: str) -> None:
    s = get_settings()
    subj_t, body_t = s.get(f"{kind}_subject", ""), s.get(f"{kind}_body", "")
    col = "invite_sent_at" if kind == "invite" else "reminder_sent_at"
    server = None
    try:
        server = _connect()
        for g in guests:
            v = _values(s, g, base)
            try:
                server.send_message(build_message(g["email"], fill(subj_t, v), fill(body_t, v)))
                ok, err = 1, None
            except (smtplib.SMTPException, OSError, ValueError) as e:
                ok, err = 0, type(e).__name__
                if isinstance(e, smtplib.SMTPServerDisconnected):
                    server = _connect()
            with dbm.db() as c:
                c.execute("INSERT INTO mail_log (guest_id, recipient, kind, ok, error) VALUES (?,?,?,?,?)",
                          (g["id"], g["email"], kind, ok, err))
                if ok:
                    c.execute(f"UPDATE guests SET {col} = datetime('now') WHERE id = ?", (g["id"],))
            with _job_lock:
                _job["sent" if ok else "failed"] += 1
            time.sleep(DELAY)
    except (smtplib.SMTPException, OSError) as e:
        log.error("mail_job_failed kind=%s error=%s", kind, type(e).__name__)
        with dbm.db() as c:
            c.execute("INSERT INTO mail_log (kind, ok, error) VALUES (?, 0, ?)", (kind, f"Anslutning: {type(e).__name__}: {e}"[:300]))
    finally:
        if server:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
        with _job_lock:
            _job.update(running=False, finished=time.strftime("%H:%M:%S"))
        log.info("mail_job_done kind=%s sent=%s failed=%s by=%s", kind, _job["sent"], _job["failed"], actor)


async def mail_view(request: Request):
    user = auth(request)
    with dbm.db() as c:
        stats = c.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(COALESCE(email,'') <> ''),0) AS with_email,
                      COALESCE(SUM(COALESCE(email,'') <> '' AND invite_sent_at IS NULL),0) AS not_invited,
                      COALESCE(SUM(COALESCE(email,'') <> '' AND rsvp = 'pending'),0) AS pending,
                      COALESCE(SUM(COALESCE(email,'') = ''),0) AS no_email
               FROM guests""").fetchone()
        mlog = c.execute("SELECT m.*, g.name FROM mail_log m LEFT JOIN guests g ON g.id = m.guest_id "
                         "ORDER BY m.id DESC LIMIT 30").fetchall()
    s = get_settings()
    preview = {k: fill(s.get(f"invite_{k}", ""), _values(s, None, public_base(request))) for k in ("subject", "body")}
    with _job_lock:
        job = dict(_job)
    return render(request, "mail.html", user, settings=s, stats=stats, mlog=mlog, job=job, preview=preview,
                  configured=configured(), smtp=SMTP, can_write=user["role"] != "viewer", active="mail",
                  msg=request.query_params.get("msg"))


async def mail_send(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    if not configured():
        raise HTTPException(400, "SMTP är inte konfigurerat (se README).")
    kind, scope = form.get("kind"), form.get("scope", "new")
    if kind not in ("invite", "reminder"):
        raise HTTPException(400)
    if form.get("confirm") != "on":
        return RedirectResponse("/mail?msg=confirm", 303)
    guests = _select_guests(kind, scope)
    with _job_lock:
        if _job["running"]:
            return RedirectResponse("/mail?msg=busy", 303)
        _job.update(running=True, kind=kind, total=len(guests), sent=0, failed=0,
                    started=time.strftime("%H:%M:%S"), finished=None)
    threading.Thread(target=_run_job, args=(kind, guests, public_base(request), user["username"]), daemon=True).start()
    log.info("mail_job_start kind=%s n=%s by=%s", kind, len(guests), user["username"])
    return RedirectResponse("/mail", 303)


async def mail_test(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    to = str(form.get("to", "")).strip()
    if not configured() or "@" not in to or len(to) > 200 or any(ch in to for ch in "\r\n,;<>"):
        raise HTTPException(400, "Ogiltig adress eller SMTP saknas.")
    s = get_settings()
    v = _values(s, None, public_base(request))
    try:
        server = _connect()
        server.send_message(build_message(to, "[TEST] " + fill(s.get("invite_subject"), v), fill(s.get("invite_body"), v)))
        server.quit()
        ok, err = 1, None
    except (smtplib.SMTPException, OSError) as e:
        ok, err = 0, f"{type(e).__name__}: {e}"[:300]
    with dbm.db() as c:
        c.execute("INSERT INTO mail_log (recipient, kind, ok, error) VALUES (?, 'test', ?, ?)", (to, ok, err))
    log.info("mail_test to=%s ok=%s by=%s", safe_log(to), ok, user["username"])
    return RedirectResponse(f"/mail?msg={'test_ok' if ok else 'test_fail'}", 303)


routes = [
    Route("/mail", mail_view),
    Route("/mail/send", mail_send, methods=["POST"]),
    Route("/mail/test", mail_test, methods=["POST"]),
]
