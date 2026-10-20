"""Enhetstester utan server: migreringar och OSA-koder."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
from app import db as dbm  # noqa: E402
from app.security import format_code, new_code, normalize_code  # noqa: E402

fails = []


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


dbm.init_db()
with dbm.db() as c:
    c.execute("INSERT INTO guests (name, invited_count, rsvp, attending) VALUES ('Gammal', 3, 'yes', 0)")
    c.execute("INSERT INTO guests (name, invited_count, rsvp, attending) VALUES ('Väntar', 2, 'pending', 0)")
dbm.init_db()  # som vid omstart/uppdatering
with dbm.db() as c:
    rows = {r["name"]: r for r in c.execute("SELECT * FROM guests")}
ok(rows["Gammal"]["attending"] == 3, "migrering: Kommer med 0 → hela hushållet")
ok(rows["Väntar"]["attending"] == 0, "migrering rör inte gäster som inte svarat")
ok(all(r["rsvp_code"] and r["rsvp_token"] for r in rows.values()), "migrering: befintliga gäster får kod och länk")
codes = {new_code() for _ in range(2000)}
ok(len(codes) == 2000 and all(len(x) == 10 and not set(x) & set("IL01O") for x in codes), "koder unika och utan förväxlingsbara tecken")
x = new_code()
ok(normalize_code(" " + format_code(x).lower() + " ") == x, "kod tål gemener, bindestreck och mellanslag")
ok(normalize_code("ABCDE-FGHI1") is None and normalize_code("x" * 50) is None, "ogiltiga koder avvisas")
from app.core import get_settings  # noqa: E402
ok(get_settings().get("osa_card_footer") == "Svara senast {osa_senast}", "ny installation: standardtext under koden")

# --- validering som tidigare gav 500
from app.core import parse_form  # noqa: E402
from app.security import verify_totp  # noqa: E402
from app.routes_invites import _safe_filename  # noqa: E402
for bad in ("inf", "1e400", "nan", "-5"):
    _, errs = parse_form([{"name": "p", "label": "Pris", "type": "money"}], {"p": bad})
    ok(len(errs) == 1, f"belopp {bad!r} ger valideringsfel")
_, errs = parse_form([{"name": "p", "label": "Pris", "type": "money"}], {"p": "12 500,50 kr"})
ok(not errs, "vanligt belopp godkänns")
for bad in ("0001-01-01", "9999-12-31"):
    _, errs = parse_form([{"name": "d", "label": "Datum", "type": "date"}], {"d": bad})
    ok(len(errs) == 1, f"datum {bad} ger valideringsfel")
_, errs = parse_form([{"name": "t", "label": "Tid", "type": "time"}], {"t": "1٢:3٠"})
ok(len(errs) == 1, "tid med arabiska siffror ger valideringsfel")
ok(verify_totp("JBSWY3DPEHPK3PXP", "１２３４５６", None) is None, "TOTP med helbreddssiffror avvisas utan krasch")
ok(_safe_filename(7, "Łukasz & Zoë") == "007_Lukasz_Zoe" and _safe_filename(1, "Åsa") == "001_Asa", "QR-filnamn blir ASCII")

# --- säkerhetskopior
import datetime as _dt  # noqa: E402
from app import backup  # noqa: E402
d0 = _dt.date(2027, 1, 1)
made = [backup.daily_backup(d0 + _dt.timedelta(days=i)) for i in range(backup.KEEP + 3)]
ok(all(made) and backup.daily_backup(d0 + _dt.timedelta(days=backup.KEEP + 2)) is None, "en kopia per dag, tas inte om samma dag")
kept = [b["name"] for b in backup.list_backups()]
ok(len(kept) == backup.KEEP and kept[0] == made[-1] and made[0] not in kept, f"bara de {backup.KEEP} senaste behålls")

# --- Swish
from app.core import SWISH_MSG_RE, normalize_swish, swish_payload  # noqa: E402
ok([normalize_swish(x) for x in ("070-123 45 67", "+46701234567", "1231234567", "0812345678", "070123")]
   == ["0701234567", "0701234567", "1231234567", None, None], "Swish-nummer normaliseras och kontrolleras")
ok(swish_payload("0701234567", "Bröllopsgåva") == "C0701234567;;Bröllopsgåva;6", "Swish-QR: låst mottagare, fritt belopp och meddelande")
ok(SWISH_MSG_RE.fullmatch("Till resan!") and not SWISH_MSG_RE.fullmatch("a;b") and not SWISH_MSG_RE.fullmatch("x" * 51),
   "Swish-meddelande: tillåtna tecken och längd")

# --- trycksaker
from app.cards import SEED, _mid_sentence  # noqa: E402
with dbm.db() as c:
    n0 = c.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    c.execute("DELETE FROM cards WHERE kind = 'menu'")
dbm.init_db()
with dbm.db() as c:
    n1 = c.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
ok(n0 == len(SEED) and n1 == len(SEED) - 1, "förslagen läggs in en gång och kommer inte tillbaka när de tagits bort")
ok([_mid_sentence(x) for x in ("Vas från Svenskt Tenn", "IKEA-kort", "x")] == ["vas från Svenskt Tenn", "IKEA-kort", "x"],
   "presenten skrivs med liten bokstav mitt i meningen")

from app.cards import initials  # noqa: E402
ok([initials(x) for x in ("Louise & Anton", "anna och erik svensson", "Kim", "")] == ["L & A", "A & E", "K", ""],
   "initialer till monogram och krans")
with dbm.db() as c:
    c.execute("ALTER TABLE cards DROP COLUMN paper")  # som en databas från förra versionen
dbm.init_db()
with dbm.db() as c:
    papers = {r[0] for r in c.execute("SELECT paper FROM cards")}
ok(papers == {"vit"}, "migrering: befintliga trycksaker får vitt papper")

# --- dekorativ QR
from app.qr import QrCode, qr_svg_fancy  # noqa: E402
svg = qr_svg_fancy("https://x.se/o/ABC", "prickar", "initialer", "<&>")
ok("&lt;&amp;&gt;" in svg and "<&>" not in svg, "QR: initialer i mitten escapas")
ok("qr-fancy" in qr_svg_fancy("https://x.se", "okänd", "okänt"), "QR: okänd stil faller tillbaka")
ok(QrCode("https://x.se/o/ABCDEFGH23", "H").version >= QrCode("https://x.se/o/ABCDEFGH23", "M").version,
   "QR: motiv i mitten använder högsta felkorrigeringen")
with dbm.db() as c:
    for col in ("qr_style", "qr_center", "qr_color"):
        c.execute(f"ALTER TABLE cards DROP COLUMN {col}")
dbm.init_db()
with dbm.db() as c:
    qrs = {tuple(r) for r in c.execute("SELECT qr_style, qr_center, qr_color FROM cards")}
ok(qrs == {("prickar", "hjarta", "kort")}, "migrering: befintliga trycksaker får prickar och hjärta")

# --- veckobrev: när ska det gå ut?
import datetime as _d  # noqa: E402
from app.core import set_settings  # noqa: E402
from app.digest import digest_due  # noqa: E402
mon7, mon6, tue = _d.datetime(2027, 3, 1, 7, 5), _d.datetime(2027, 3, 1, 6, 59), _d.datetime(2027, 3, 2, 9)
set_settings({"digest_enabled": "1", "digest_week": ""})
ok(digest_due(mon7) == "2027-09" and digest_due(mon6) is None and digest_due(tue) is None, "veckobrev: måndag efter 07")
set_settings({"digest_week": "2027-09"})
ok(digest_due(mon7) is None, "veckobrev: bara en gång per vecka")
set_settings({"digest_enabled": "0", "digest_week": ""})
ok(digest_due(mon7) is None, "veckobrev: kan stängas av")

# --- förslag på bordsplacering
from app.seating_plan import suggest  # noqa: E402
with dbm.db() as c:
    c.execute("DELETE FROM guests"); c.execute("DELETE FROM tables")
    t1 = c.execute("INSERT INTO tables (name, seats, sort_no) VALUES ('Bord 1', 5, 1)").lastrowid
    t2 = c.execute("INSERT INTO tables (name, seats, sort_no) VALUES ('Bord 2', 5, 2)").lastrowid
    def gst(name, n, grp="", rsvp="pending", table=None, avoid=None):
        return c.execute("INSERT INTO guests (name, invited_count, rsvp, attending, group_name, table_id, avoid_guest_id) "
                         "VALUES (?,?,?,?,?,?,?)", (name, n, rsvp, n if rsvp == "yes" else 0, grp, table, avoid)).lastrowid
    k1, k2 = gst("Kollega A", 2, "Kollegor"), gst("Kollega B", 2, "Kollegor")
    fam = gst("Familjen", 3, "Familj", rsvp="yes")
    ex = gst("Exet", 1, avoid=fam)
    nej = gst("Kommer inte", 2, rsvp="no")
    stor = gst("Jättegruppen", 6, "Ensam")
    plan, left = suggest(c)
    placed = dict(plan)
ok(placed.get(k1) == placed.get(k2) and placed.get(k1) is not None, "placering: gruppen hålls ihop")
ok(placed.get(ex) != placed.get(fam) and ex in placed and fam in placed, "placering: ”sitt inte med” respekteras")
ok(nej not in placed and stor in left, "placering: de som tackat nej och de som inte får plats lämnas")
used = {t: 0 for t in (t1, t2)}
need = {k1: 2, k2: 2, fam: 3, ex: 1}
for g, t in plan: used[t] += need[g]
ok(used[t1] <= 5 and used[t2] <= 5, "placering: bord fylls aldrig över antal platser")

# --- tidskapsel
import logging  # noqa: E402
from app import capsule  # noqa: E402
set_settings({"wedding_date": "2025-06-01", "capsule_enabled": "1", "capsule_sent": ""})
with dbm.db() as c:
    c.execute("DELETE FROM capsule")
ok(not capsule.capsule_due(), "tidskapsel: inget skickas utan brev")
with dbm.db() as c:
    c.execute("INSERT INTO capsule (name, text) VALUES ('Moster', 'Grattis!')")
ok(capsule.capsule_due() and not capsule.is_open(), "tidskapsel: ett år efter bröllopet är det dags och kapseln stängd")
subj, body = capsule.build_letters()
ok("Tidskapseln" in subj and "Från Moster:" in body and "Grattis!" in body, "tidskapsel: alla brev i ett mejl")
set_settings({"wedding_date": "2099-06-01"})
ok(not capsule.capsule_due() and capsule.is_open(), "tidskapsel: före ettårsdagen skickas inget")
set_settings({"wedding_date": "2025-06-01", "capsule_sent": "1"})
ok(not capsule.capsule_due(), "tidskapsel: skickas bara en gång")

# ---------------------------------------------------------------- push: kryptering (RFC 8291) och VAPID (RFC 8292)
import base64, json as _json, hashlib as _hl, hmac as _hm, datetime as _dt
from cryptography.hazmat.primitives import hashes as _h, serialization as _ser
from cryptography.hazmat.primitives.asymmetric import ec as _ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _GCM
from app import push  # noqa: E402

ua = _ec.generate_private_key(_ec.SECP256R1())
ua_pub = ua.public_key().public_bytes(_ser.Encoding.X962, _ser.PublicFormat.UncompressedPoint)
secret = os.urandom(16)
body = push.encrypt(b'{"title":"Hej"}', push.b64u(ua_pub), push.b64u(secret))
salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
as_pub = body[21:21 + idlen]
shared = ua.exchange(_ec.ECDH(), _ec.EllipticCurvePublicKey.from_encoded_point(_ec.SECP256R1(), as_pub))
H = lambda k, d: _hm.new(k, d, _hl.sha256).digest()
ikm = H(H(secret, shared), b"WebPush: info\x00" + ua_pub + as_pub + b"\x01")
prk = H(salt, ikm)
plain = _GCM(H(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]).decrypt(H(prk, b"Content-Encoding: nonce\x00\x01")[:12], body[21 + idlen:], None)
ok(rs == 4096 and idlen == 65 and plain == b'{"title":"Hej"}\x02', "push: meddelandet kan avkrypteras av mottagaren (aes128gcm)")
hdr = push.vapid_header("https://web.push.apple.com/abc", "mailto:a@b.se")
jwt, k = hdr[len("vapid t="):].split(", k=")
h64, c64, s64 = jwt.split(".")
claims = _json.loads(push.b64u_dec(c64))
sig = push.b64u_dec(s64)
pub = _ec.EllipticCurvePublicKey.from_encoded_point(_ec.SECP256R1(), push.b64u_dec(k))
try:
    pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
               f"{h64}.{c64}".encode(), _ec.ECDSA(_h.SHA256()))
    verified = True
except Exception:
    verified = False
ok(verified and claims["aud"] == "https://web.push.apple.com" and claims["sub"] == "mailto:a@b.se", "push: VAPID-signaturen stämmer")
ok(k == push.public_key(), "push: samma nyckel sparas och återanvänds")
ok(all(push.endpoint_ok(u) for u in ("https://web.push.apple.com/QK", "https://fcm.googleapis.com/fcm/send/x",
                                     "https://updates.push.services.mozilla.com/wpush/v2/x")), "push: kända push-tjänster godkänns")
ok(not any(push.endpoint_ok(u) for u in ("http://web.push.apple.com/x", "https://evil.example/x", "https://push.apple.com.evil.example/x",
                                         "https://127.0.0.1/x", "https://web.push.apple.com:8443/x", "https://u@web.push.apple.com/x",
                                         "https://evilpush.apple.com/x")), "push: andra adresser nekas (ingen SSRF)")
set_settings({"wedding_date": "2027-05-22"})
with dbm.db() as c:
    c.execute("DELETE FROM timeline")
    c.execute("INSERT INTO timeline (time, title) VALUES ('15:00', 'Vigsel'), ('00:30', 'Nattmat')")
ok(push.programme_reminders(_dt.datetime(2027, 5, 22, 14, 56)) == 1, "push: påminnelse fem minuter innan")
ok(push.programme_reminders(_dt.datetime(2027, 5, 22, 14, 57)) == 0, "push: bara en påminnelse per punkt")
ok(push.programme_reminders(_dt.datetime(2027, 5, 23, 0, 26)) == 1, "push: punkter efter midnatt räknas till natten efter")
ok(push.programme_reminders(_dt.datetime(2027, 5, 21, 14, 56)) == 0, "push: inga påminnelser andra dagar")

# ---------------------------------------------------------------- väder från SMHI
from app import weather  # noqa: E402
import time as _t
def _ts(h):  # lokal tid → UTC-sträng som SMHI skickar
    return _dt.datetime(2027, 5, 22, h).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
data = {"timeSeries": [
    {"time": _ts(9), "data": {"air_temperature": 5.0, "symbol_code": 1}},
    {"time": _ts(12), "data": {"air_temperature": 14.4, "symbol_code": 3, "precipitation_amount_mean": 0.2, "wind_speed": 3.1}},
    {"time": _ts(14), "data": {"air_temperature": 16.6, "symbol_code": 18, "precipitation_amount_mean": 0.5, "wind_speed": 9999}},
    {"time": _ts(20), "data": {"air_temperature": 9999, "symbol_code": 2, "wind_speed": 5.4}},
    {"time": "trasig", "data": {}}]}
w = weather.summarize(data, _dt.date(2027, 5, 22), "14:00")
ok(w and (w["text"], w["temp"], w["min"], w["max"], w["rain"], w["wind"]) == ("Lätt regn", 17, 14, 17, 0.7, 5),
   f"väder: sammanfattning vid starttiden, 9999 hoppas över ({w})")
ok(weather.summarize({"timeSeries": []}, _dt.date(2027, 5, 22)) is None, "väder: tom prognos ger inget")
ok(weather.coords({"venue_lat": "59,365", "venue_lon": "18.013"}) == (59.365, 18.013), "väder: koordinater med komma")
ok(weather.coords({"venue_lat": "48.8", "venue_lon": "2.3"}) is None and weather.coords({"venue_lat": "x"}) is None,
   "väder: koordinater utanför SMHI:s område eller trasiga ignoreras")

# ---------------------------------------------------------------- samåkning
from app.routes_rides import suggest  # noqa: E402
drivers = [{"id": 1, "ride_from": "Uppsala", "free": 3}, {"id": 2, "ride_from": "Göteborg", "free": 2}]
needers = [{"id": 10, "ride_from": "uppsala ", "need": 2, "ride_with_id": None},
           {"id": 11, "ride_from": "Malmö", "need": 2, "ride_with_id": None},
           {"id": 12, "ride_from": "Uppsala", "need": 2, "ride_with_id": None},
           {"id": 13, "ride_from": "", "need": 1, "ride_with_id": 2}]
plan = dict(suggest(drivers, needers))
ok(plan.get(10) == 1 and plan.get(11) == 2 and 12 not in plan and 13 not in plan,
   f"samåkning: samma ort först, ingen bil överfylls, redan kopplade rörs inte ({plan})")
print(f"\n{len(fails)} fel")
sys.exit(1 if fails else 0)
