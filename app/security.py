"""Säkerhetsprimitiver: lösenordshashning (scrypt), sessionstokens, TOTP (RFC 6238) och rate limiting.

Allt bygger på Pythons standardbibliotek – inga externa kryptoberoenden.
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import threading
import time
from collections import deque

# ---------------------------------------------------------------- lösenord
# scrypt: minnesintensiv KDF (OWASP-rekommenderad). N=2^15, r=8, p=1 ≈ 32 MB per hash.
_N, _R, _P, _DKLEN = 2**15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD_LEN = 12
MAX_PASSWORD_LEN = 256


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _scrypt(pw: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=_DKLEN)


def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(_scrypt(pw, salt, _N, _R, _P))}"


_DUMMY_HASH = hash_pw(secrets.token_urlsafe(24))


def verify_pw(stored: str | None, pw: str) -> bool:
    """Konstant-tid-jämförelse. Om användaren saknas verifieras mot en dummy-hash
    så att svarstiden inte avslöjar om användarnamnet finns."""
    target = stored or _DUMMY_HASH
    try:
        algo, n, r, p, salt, expected = target.split("$")
        if algo != "scrypt":
            return False
        calc = _scrypt(pw[:MAX_PASSWORD_LEN], base64.b64decode(salt), int(n), int(r), int(p))
        ok = hmac.compare_digest(calc, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False
    return ok and stored is not None


def needs_rehash(stored: str) -> bool:
    try:
        _, n, r, p, *_ = stored.split("$")
        return (int(n), int(r), int(p)) != (_N, _R, _P)
    except ValueError:
        return True


def password_problem(pw: str, username: str = "") -> str | None:
    if len(pw) < MIN_PASSWORD_LEN:
        return f"Lösenordet måste vara minst {MIN_PASSWORD_LEN} tecken."
    if len(pw) > MAX_PASSWORD_LEN:
        return "Lösenordet är för långt."
    if username and pw.lower() == username.lower():
        return "Lösenordet får inte vara samma som användarnamnet."
    if len(set(pw)) < 5:
        return "Lösenordet är för enkelt."
    return None


# ---------------------------------------------------------------- tokens
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """Sessionstokens lagras enbart som SHA-256 – en läckt databas ger inga giltiga sessioner."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- TOTP (2FA)
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret: str, t: float | None = None) -> str:
    return _hotp(secret, int((t or time.time()) // 30))


def verify_totp(secret: str, code: str, last_step: int | None) -> int | None:
    """Returnerar tidssteget om koden är giltig (±30 s) och inte redan använd, annars None.
    Att spara steget förhindrar att samma kod återanvänds (replay)."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    now_step = int(time.time() // 30)
    for step in (now_step - 1, now_step, now_step + 1):
        if step > (last_step or 0) and hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def totp_uri(secret: str, account: str, issuer: str = "Bröllopsplaneraren") -> str:
    from urllib.parse import quote
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


# ---------------------------------------------------------------- rate limiting
class RateLimiter:
    """Glidande fönster i minnet. Appen körs med en worker så detta räcker."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _prune(self, q: deque, now: float) -> None:
        while q and q[0] <= now - self.window:
            q.popleft()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return False
            self._prune(q, now)
            return len(q) >= self.limit

    def hit(self, key: str) -> bool:
        """Registrerar ett försök. Returnerar False om gränsen nu är överskriden."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 50_000:
                for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
                    del self._hits[k]
            q = self._hits.setdefault(key, deque())
            self._prune(q, now)
            q.append(now)
            return len(q) <= self.limit

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
