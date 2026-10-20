"""Web Push (RFC 8030/8291/8292) till apparna på hemskärmen – iPhone från iOS 16.4.

Nycklarna (VAPID) skapas första gången och sparas i inställningarna. Meddelandet krypteras för varje
prenumeration (aes128gcm) och skickas bara till push-tjänster i ALLOWED_HOSTS – adressen kommer från
webbläsaren och får aldrig kunna peka mot interna adresser."""
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import db as dbm
from .core import get_settings, log, set_settings

ALLOWED_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")
APPS = ("tm", "plan")


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def endpoint_ok(url: str) -> bool:
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and u.port in (None, 443) and not u.username and len(url) <= 1024
            and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS))


def _raw_public(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_key():
    pem = get_settings().get("vapid_private_key")
    if not pem:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        set_settings({"vapid_private_key": pem})
    return serialization.load_pem_private_key(pem.encode(), None)


def public_key() -> str:
    """Nyckeln webbläsaren behöver för att prenumerera (applicationServerKey)."""
    return b64u(_raw_public(vapid_key()))


def vapid_header(endpoint: str, subject: str, key=None) -> str:
    key = key or vapid_key()
    u = urllib.parse.urlsplit(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": subject}
    signing = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode()) + "." + b64u(json.dumps(claims).encode())
    r, s = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={b64u(_raw_public(key))}"


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None, server_key=None) -> bytes:
    """Krypterar enligt RFC 8291 (aes128gcm, en post)."""
    ua_public, secret = b64u_dec(p256dh), b64u_dec(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(server_key)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hmac(_hmac(secret, shared), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    salt = salt or os.urandom(16)
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_public)]) + as_public + body


def subject() -> str:
    url = get_settings().get("app_url", "")
    return url if url.startswith("https://") else "mailto:brollop@example.invalid"


def send_one(sub, message: dict) -> int:
    """Skickar till en prenumeration. Returnerar HTTP-status (0 vid nätverksfel)."""
    if not endpoint_ok(sub["endpoint"]):
        return 0
    body = encrypt(json.dumps(message).encode(), sub["p256dh"], sub["auth"])
    req = urllib.request.Request(sub["endpoint"], body, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "3600",
        "Urgency": "high", "Authorization": vapid_header(sub["endpoint"], subject())})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        log.warning("push_failed error=%s: %s", type(e).__name__, e)
        return 0


def send(app: str, title: str, body: str, url: str, user_id: int | None = None, wait: bool = False) -> None:
    """Skickar till alla prenumerationer för appen (eller en användare) i en bakgrundstråd."""
    with dbm.db() as c:
        sql, args = "SELECT * FROM push_subs WHERE app = ?", [app]
        if user_id is not None:
            sql, args = sql + " AND user_id = ?", args + [user_id]
        subs = [dict(r) for r in c.execute(sql, args)]
    if not subs:
        return

    def work():
        gone = []
        for sub in subs:
            status = send_one(sub, {"title": title, "body": body, "url": url})
            if status in (404, 410):  # prenumerationen finns inte längre
                gone.append(sub["id"])
            elif status and status >= 400:
                log.warning("push_rejected status=%s sub=%s", status, sub["id"])
        if gone:
            with dbm.db() as c:
                c.executemany("DELETE FROM push_subs WHERE id = ?", [(i,) for i in gone])
        log.info("push_sent app=%s n=%s removed=%s", app, len(subs), len(gone))

    t = threading.Thread(target=work, daemon=True)
    t.start()
    if wait:
        t.join(30)


def programme_reminders(now: dt.datetime | None = None) -> int:
    """Körs varje minut: påminner toastmasterappen fem minuter innan varje programpunkt på bröllopsdagen."""
    from .core import parse_date
    from .entities import NIGHT_CUTOFF
    s = get_settings()
    wd = parse_date(s.get("wedding_date"))
    now = (now or dt.datetime.now()).replace(second=0, microsecond=0)
    if not wd or not wd <= now.date() <= wd + dt.timedelta(days=1):
        return 0
    sent = set(filter(None, s.get("push_reminded", "").split(",")))
    n = 0
    with dbm.db() as c:
        items = c.execute("SELECT id, time, title, location FROM timeline").fetchall()
    for t in items:
        day = wd + dt.timedelta(days=1) if t["time"] < NIGHT_CUTOFF else wd
        at = dt.datetime.combine(day, dt.time.fromisoformat(t["time"]))
        key = f"{t['id']}@{t['time']}"  # flyttas punkten kommer en ny påminnelse
        if key not in sent and dt.timedelta(0) < at - now <= dt.timedelta(minutes=5):
            send("tm", f"Om {int((at - now).total_seconds() // 60)} min: {t['title']}",
                 f"kl. {t['time']}" + (f" · {t['location']}" if t["location"] else ""), "/tm")
            sent.add(key)
            n += 1
    if n:
        set_settings({"push_reminded": ",".join(sorted(sent))})
    return n
