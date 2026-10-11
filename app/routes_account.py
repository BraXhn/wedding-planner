import re
import secrets

from markupsafe import Markup
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import (
    LOGIN_IP, LOGIN_USER, ROLES, auth, client_ip, create_session, csrf_form,
    cookie_name, cookie_secure, get_session, log, public_base, read_form, render, safe_log, set_session_cookie,
)
from .qr import qr_svg
from .security import (
    hash_pw, needs_rehash, new_token, new_totp_secret, password_problem, token_hash, totp_uri, verify_pw,
    verify_totp,
)

USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,32}")


# ======================================================================= login / logout
async def login(request: Request):
    if request.method == "GET":
        if get_session(request):
            return RedirectResponse("/", 303)
        return render(request, "login.html", insecure=request.url.scheme != "https")

    form = await read_form(request)
    username = str(form.get("username", ""))[:64].strip()
    password = str(form.get("password", ""))[:256]
    code = str(form.get("code", ""))[:12]
    ip, ukey = client_ip(request), "u:" + username.lower()

    if LOGIN_IP.blocked(ip) or LOGIN_USER.blocked(ukey):
        log.warning("login_blocked ip=%s user=%s", ip, safe_log(username))
        return render(request, "login.html", error="För många misslyckade försök. Vänta 15 minuter.", status=429)

    with dbm.db() as c:
        u = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = verify_pw(u["pw_hash"] if u else None, password)
        if ok and u["totp_secret"]:
            step = verify_totp(u["totp_secret"], code, u["totp_last_step"])
            ok = step is not None
            if ok:
                c.execute("UPDATE users SET totp_last_step = ? WHERE id = ?", (step, u["id"]))
        if not ok:
            LOGIN_IP.hit(ip)
            LOGIN_USER.hit(ukey)
            log.warning("login_failed ip=%s user=%s", ip, safe_log(username))
            return render(request, "login.html", error="Fel användarnamn, lösenord eller kod.", status=401)

        if needs_rehash(u["pw_hash"]):
            c.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_pw(password), u["id"]))
        old = request.cookies.get(cookie_name(request))
        if old:  # förhindra session fixation
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(old),))
        token = create_session(c, u["id"])

    LOGIN_USER.reset(ukey)
    log.info("login_ok ip=%s user=%s", ip, safe_log(username))
    resp = RedirectResponse("/account" if u["must_change_pw"] else "/", 303)
    set_session_cookie(resp, token, request)
    return resp


async def logout(request: Request):
    user = auth(request)
    await csrf_form(request, user)
    with dbm.db() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (user["token_hash"],))
    resp = RedirectResponse("/login", 303)
    resp.delete_cookie(cookie_name(request), path="/", secure=cookie_secure(request), httponly=True, samesite="strict")
    return resp


# ======================================================================= konto
async def account(request: Request):
    user = auth(request)
    return render(request, "account.html", user, active="account")


async def account_password(request: Request):
    user = auth(request)
    form = await csrf_form(request, user)
    current, new, new2 = (str(form.get(k, ""))[:256] for k in ("current", "new", "new2"))
    with dbm.db() as c:
        u = c.execute("SELECT * FROM users WHERE id = ?", (user["user_id"],)).fetchone()
        if not verify_pw(u["pw_hash"], current):
            err = "Nuvarande lösenord är fel."
        elif new != new2:
            err = "De nya lösenorden matchar inte."
        elif new == current:
            err = "Välj ett nytt lösenord."
        else:
            err = password_problem(new, u["username"])
        if err:
            return render(request, "account.html", user, status=400, pw_error=err, active="account")
        c.execute("UPDATE users SET pw_hash = ?, must_change_pw = 0 WHERE id = ?", (hash_pw(new), u["id"]))
        c.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (u["id"], user["token_hash"]))
    log.info("password_changed user=%s", user["username"])
    return render(request, "account.html", auth(request), pw_ok=True, active="account")


async def totp_start(request: Request):
    user = auth(request)
    await csrf_form(request, user)
    secret = new_totp_secret()
    with dbm.db() as c:
        c.execute("UPDATE sessions SET totp_pending = ? WHERE token_hash = ?", (secret, user["token_hash"]))
    uri = totp_uri(secret, user["username"])
    return render(request, "account.html", user, active="account", totp_secret=secret,
                  totp_secret_spaced=" ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
                  totp_uri=uri, totp_qr=Markup(qr_svg(uri)))  # SVG genereras av oss själva → säker


async def totp_confirm(request: Request):
    user = auth(request)
    form = await csrf_form(request, user)
    secret = user.get("totp_pending")
    step = verify_totp(secret, str(form.get("code", "")), None) if secret else None
    if step is None:
        return render(request, "account.html", user, status=400, active="account",
                      totp_error="Koden stämde inte. Starta om aktiveringen och försök igen.")
    with dbm.db() as c:
        c.execute("UPDATE users SET totp_secret = ?, totp_last_step = ? WHERE id = ?", (secret, step, user["user_id"]))
        c.execute("UPDATE sessions SET totp_pending = NULL WHERE token_hash = ?", (user["token_hash"],))
    log.info("totp_enabled user=%s", user["username"])
    return render(request, "account.html", auth(request), active="account", totp_ok="Tvåstegsverifiering är aktiverad.")


async def totp_disable(request: Request):
    user = auth(request)
    form = await csrf_form(request, user)
    with dbm.db() as c:
        u = c.execute("SELECT pw_hash FROM users WHERE id = ?", (user["user_id"],)).fetchone()
        if not verify_pw(u["pw_hash"], str(form.get("password", ""))[:256]):
            return render(request, "account.html", user, status=400, active="account", totp_error="Fel lösenord.")
        c.execute("UPDATE users SET totp_secret = NULL, totp_last_step = NULL WHERE id = ?", (user["user_id"],))
    log.info("totp_disabled user=%s", user["username"])
    return render(request, "account.html", auth(request), active="account", totp_ok="Tvåstegsverifiering är avstängd.")


async def ics_token(request: Request):
    """Skapar (eller återkallar) personlig kalenderprenumeration. Länken visas bara en gång."""
    user = auth(request)
    form = await csrf_form(request, user)
    with dbm.db() as c:
        if form.get("action") == "revoke":
            c.execute("UPDATE users SET ics_token_hash = NULL WHERE id = ?", (user["user_id"],))
            log.info("ics_revoked user=%s", user["username"])
            return render(request, "account.html", auth(request), active="account", ics_ok="Kalenderlänken är återkallad.")
        token = new_token(32)
        c.execute("UPDATE users SET ics_token_hash = ? WHERE id = ?", (token_hash(token), user["user_id"]))
    log.info("ics_created user=%s", user["username"])
    return render(request, "account.html", auth(request), active="account",
                  ics_url=f"{public_base(request)}/cal/{token}.ics")


# ======================================================================= användare (admin)
def _users():
    with dbm.db() as c:
        return c.execute("SELECT id, username, role, totp_secret IS NOT NULL AS has_totp, created_at "
                         "FROM users ORDER BY username").fetchall()


async def users_view(request: Request):
    user = auth(request, admin=True)
    if request.method == "GET":
        return render(request, "users.html", user, users=_users(), roles=ROLES, active="users")
    form = await csrf_form(request, user)
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))[:256]
    role = str(form.get("role", ""))
    if not USERNAME_RE.fullmatch(username):
        err = "Användarnamn: 3–32 tecken, bokstäver a–z, siffror, . _ -"
    elif role not in dict(ROLES):
        err = "Ogiltig roll."
    else:
        err = password_problem(password, username)
    if not err:
        with dbm.db() as c:
            if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                err = "Användarnamnet finns redan."
            else:
                c.execute("INSERT INTO users (username, pw_hash, role, must_change_pw) VALUES (?,?,?,1)",
                          (username, hash_pw(password), role))
                log.info("user_created user=%s role=%s by=%s", username, role, user["username"])
    return render(request, "users.html", user, status=400 if err else 200, users=_users(), roles=ROLES,
                  active="users", error=err,
                  ok=None if err else f"Användaren {username} skapades. De måste byta lösenord vid första inloggning.")


async def user_delete(request: Request):
    user = auth(request, admin=True)
    await csrf_form(request, user)
    uid = request.path_params["user_id"]
    if uid == user["user_id"]:
        raise HTTPException(400, "Du kan inte ta bort dig själv.")
    with dbm.db() as c:
        c.execute("DELETE FROM users WHERE id = ?", (uid,))
    log.info("user_deleted id=%s by=%s", uid, user["username"])
    return RedirectResponse("/users", 303)


def bootstrap_admin() -> None:
    import os
    with dbm.db() as c:
        if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        username = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"
        password = os.environ.get("ADMIN_PASSWORD", "")
        generated = bool(password_problem(password, username))
        if generated:
            password = secrets.token_urlsafe(15)
        c.execute("INSERT INTO users (username, pw_hash, role, must_change_pw) VALUES (?,?, 'admin', 1)",
                  (username, hash_pw(password)))
    if generated:
        log.warning("=" * 60)
        log.warning("Första admin skapad. Användare: %s  Engångslösenord: %s", username, password)
        log.warning("Du måste byta lösenord vid första inloggningen.")
        log.warning("=" * 60)
    else:
        log.warning("Första admin '%s' skapad från ADMIN_PASSWORD. Ta bort variabeln nu.", username)


routes = [
    Route("/login", login, methods=["GET", "POST"]),
    Route("/logout", logout, methods=["POST"]),
    Route("/account", account),
    Route("/account/password", account_password, methods=["POST"]),
    Route("/account/totp/start", totp_start, methods=["POST"]),
    Route("/account/totp/confirm", totp_confirm, methods=["POST"]),
    Route("/account/totp/disable", totp_disable, methods=["POST"]),
    Route("/account/ics", ics_token, methods=["POST"]),
    Route("/users", users_view, methods=["GET", "POST"]),
    Route("/users/{user_id:int}/delete", user_delete, methods=["POST"]),
]
