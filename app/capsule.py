"""Tidskapseln: gästerna skriver brev till brudparet som mejlas ut på ettårsdagen.
Brudparet ser bara antalet brev före dess – innehållet visas inte i appen."""
from . import db as dbm
from .core import add_months, flag, get_settings, parse_date, set_settings, sv_date, today
from .security import RateLimiter

CAPSULE_IP = RateLimiter(6, 60 * 60)  # brev per IP och timme
CAPSULE_MAX = 2000
RESULTS = {"ok": None, "tom": "Skriv något först.", "lang": f"Brevet får vara högst {CAPSULE_MAX} tecken.",
           "manga": "För många brev på kort tid – vänta en stund.", "stangd": "Tidskapseln är stängd."}


def open_date():
    wd = parse_date(get_settings().get("wedding_date"))
    return add_months(wd, 12) if wd else None


def is_open(s: dict | None = None) -> bool:
    s = s or get_settings()
    od = open_date()
    return flag(s, "capsule_enabled") and (od is None or today() < od)


def save_letter(form, ip: str, guest=None) -> str:
    if not is_open():
        return "stangd"
    text = str(form.get("letter", "")).replace("\r\n", "\n").strip()
    name = " ".join(str(guest["name"] if guest else form.get("name", "")).split())[:60]
    if not text:
        return "tom"
    if len(text) > CAPSULE_MAX:
        return "lang"
    if not CAPSULE_IP.hit(ip):
        return "manga"
    with dbm.db() as c:
        c.execute("INSERT INTO capsule (guest_id, name, text) VALUES (?, ?, ?)", (guest["id"] if guest else None, name or None, text))
    return "ok"


def count() -> int:
    with dbm.db() as c:
        return c.execute("SELECT COUNT(*) FROM capsule").fetchone()[0]


def capsule_due() -> bool:
    s = get_settings()
    od = open_date()
    return bool(od and flag(s, "capsule_enabled") and s.get("capsule_sent") != "1" and today() >= od and count())


def build_letters() -> tuple[str, str]:
    s = get_settings()
    with dbm.db() as c:
        letters = c.execute("SELECT name, text, created_at FROM capsule ORDER BY id").fetchall()
    parts = [f"Grattis på ettårsdagen, {s.get('couple_names') or 'ni två'}!\n",
             f"För ett år sedan, {sv_date(s.get('wedding_date'))}, skrev era gäster de här {len(letters)} breven till er:\n"]
    for l in letters:
        parts.append("─" * 30)
        parts.append(f"Från {l['name'] or 'en gäst'}:\n\n{l['text']}\n")
    return "Tidskapseln: brev från bröllopet för ett år sedan 💌", "\n".join(parts)


def send_capsule(log) -> int:
    from .routes_mail import couple_addresses, send_to_couple
    if not couple_addresses():
        return 0
    subject, body = build_letters()
    n = send_to_couple(subject, body, kind="capsule")
    if n:
        set_settings({"capsule_sent": "1"})
    log.info("capsule_sent ok=%s letters=%s", n, count())
    return n
