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
print(f"\n{len(fails)} fel")
sys.exit(1 if fails else 0)
