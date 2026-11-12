"""Passkeys (WebAuthn) – inloggning med Face ID/Touch ID i stället för lösenord.

Bara det som behövs: ES256-nycklar, ingen attestering ("none"), krav på användarverifiering (UV) –
en passkey är därmed två faktorer (enheten + ansikte/finger/kod) och ersätter lösenord + engångskod.
Utmaningarna hålls i minnet (appen kör med en worker), gäller i fem minuter och kan bara användas en gång."""
import hashlib
import json
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from .push import b64u, b64u_dec
from .security import new_token

CHALLENGE_TTL = 300
MAX_PER_USER = 10
FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40
_challenges: dict[str, tuple[float, int | None]] = {}  # utmaning → (går ut, användare vid registrering)
_lock = threading.Lock()


class PasskeyError(ValueError):
    pass


# ----------------------------------------------------------------------- utmaningar
def new_challenge(user_id: int | None = None) -> str:
    ch = new_token(32)
    now = time.time()
    with _lock:
        for k in [k for k, (exp, _) in _challenges.items() if exp < now]:
            del _challenges[k]
        if len(_challenges) > 2000:  # någon fyller minnet – släng de äldsta
            for k in sorted(_challenges, key=lambda k: _challenges[k][0])[:1000]:
                del _challenges[k]
        _challenges[ch] = (now + CHALLENGE_TTL, user_id)
    return ch


def _use_challenge(ch: str, user_id: int | None) -> None:
    with _lock:
        exp, owner = _challenges.pop(ch, (0, None))
    if exp < time.time() or owner != user_id:
        raise PasskeyError("challenge")


# ----------------------------------------------------------------------- CBOR (det authenticatorn skickar)
def cbor_decode(data: bytes, pos: int = 0, depth: int = 0):
    """Avkodar ett CBOR-värde. Returnerar (värde, nästa position). Stöder heltal, bytes, text, listor och kartor."""
    if depth > 8 or pos >= len(data):
        raise PasskeyError("cbor")
    major, info = data[pos] >> 5, data[pos] & 0x1F
    pos += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if pos + size > len(data):
            raise PasskeyError("cbor")
        n = int.from_bytes(data[pos:pos + size], "big")
        pos += size
    else:
        raise PasskeyError("cbor")
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if pos + n > len(data):
            raise PasskeyError("cbor")
        raw = data[pos:pos + n]
        return (raw if major == 2 else raw.decode("utf-8", "replace")), pos + n
    if major == 4 and n <= 64:
        out = []
        for _ in range(n):
            v, pos = cbor_decode(data, pos, depth + 1)
            out.append(v)
        return out, pos
    if major == 5 and n <= 64:
        out = {}
        for _ in range(n):
            k, pos = cbor_decode(data, pos, depth + 1)
            v, pos = cbor_decode(data, pos, depth + 1)
            if isinstance(k, (int, str)):
                out[k] = v
        return out, pos
    raise PasskeyError("cbor")


# ----------------------------------------------------------------------- kontroller
def _client_data(raw: bytes, kind: str, origin: str, user_id: int | None) -> None:
    try:
        cd = json.loads(raw)
    except ValueError:
        raise PasskeyError("clientdata")
    if not isinstance(cd, dict):
        raise PasskeyError("clientdata")
    _use_challenge(str(cd.get("challenge", "")), user_id)  # förbrukas alltid, även om resten är fel
    if cd.get("type") != kind or cd.get("origin") != origin or cd.get("crossOrigin") is True:
        raise PasskeyError("clientdata")


def _auth_data(raw: bytes, rp_id: str) -> tuple[int, int, bytes]:
    """Returnerar (flaggor, räknare, resten). Kräver rätt sajt, närvaro och användarverifiering."""
    if len(raw) < 37 or raw[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise PasskeyError("rpid")
    flags = raw[32]
    if not flags & FLAG_UP or not flags & FLAG_UV:
        raise PasskeyError("verification")
    return flags, int.from_bytes(raw[33:37], "big"), raw[37:]


def register(user_id: int, origin: str, rp_id: str, client_data: bytes, attestation: bytes) -> tuple[str, str, int]:
    """Kontrollerar svaret från navigator.credentials.create(). Returnerar (id, publik nyckel, räknare)."""
    _client_data(client_data, "webauthn.create", origin, user_id)
    att, _ = cbor_decode(attestation)
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise PasskeyError("attestation")
    flags, count, rest = _auth_data(att["authData"], rp_id)
    if not flags & FLAG_AT or len(rest) < 18:
        raise PasskeyError("attestation")
    id_len = int.from_bytes(rest[16:18], "big")
    cred_id = rest[18:18 + id_len]
    if not 1 <= id_len <= 1023 or len(cred_id) != id_len:
        raise PasskeyError("attestation")
    key, _ = cbor_decode(rest, 18 + id_len)
    # COSE: kty 2 (EC2), alg -7 (ES256), crv 1 (P-256), x och y
    if not (isinstance(key, dict) and key.get(1) == 2 and key.get(3) == -7 and key.get(-1) == 1
            and isinstance(key.get(-2), bytes) and isinstance(key.get(-3), bytes)
            and len(key[-2]) == 32 and len(key[-3]) == 32):
        raise PasskeyError("key")
    point = b"\x04" + key[-2] + key[-3]
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        raise PasskeyError("key")
    return b64u(cred_id), b64u(point), count


def verify(public_key: str, stored_count: int, origin: str, rp_id: str, client_data: bytes, auth_data: bytes,
           signature: bytes) -> int:
    """Kontrollerar svaret från navigator.credentials.get(). Returnerar den nya räknaren."""
    _client_data(client_data, "webauthn.get", origin, None)
    _, count, _ = _auth_data(auth_data, rp_id)
    if (count or stored_count) and count <= stored_count:  # kopierad nyckel; 0/0 = enheten räknar inte (t.ex. iCloud)
        raise PasskeyError("counter")
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64u_dec(public_key))
        key.verify(signature, auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise PasskeyError("signature")
    return count
