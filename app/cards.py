"""Trycksaker: inbjudningar, save the date, tackkort, meny, skyltar och program.

Varje trycksak har en design, en färg, ett format och fyra textfält med platshållare
({namn}, {datum} …). Personliga trycksaker blir ett kort per hushåll (alla, de som inte svarat
eller de som kommer), övriga skrivs ut i valfritt antal. Texterna fylls i med enkel
strängersättning (routes_mail.fill) – aldrig str.format."""
import re

from .core import sv_date
from .entities import TIMELINE_ORDER
from .security import format_code

DESIGNS = [("klassisk", "Klassisk"), ("botanisk", "Botanisk"), ("modern", "Modern"), ("romantisk", "Romantisk"),
           ("minimal", "Minimal"), ("monogram", "Monogram"), ("artdeco", "Art déco"), ("akvarell", "Akvarell"),
           ("krans", "Krans"), ("bage", "Båge"), ("rustik", "Rustik")]
COLORS = [("skog", "Skogsgrön"), ("salvia", "Salvia"), ("guld", "Guld"), ("terrakotta", "Terrakotta"), ("rosa", "Dammrosa"),
          ("lavendel", "Lavendel"), ("bla", "Marinblå"), ("svart", "Svart")]
# Färgat papper: då skrivs ingen bakgrund eller fyllning ut – bara text och linjer. Färgen används i förhandsvisningen.
PAPERS = [("vit", "Vitt papper – designen skrivs ut med bakgrund"), ("kram", "Färgat papper: kräm"),
          ("kraft", "Färgat papper: kraft"), ("salvia", "Färgat papper: salvia"), ("rosa", "Färgat papper: dammrosa"),
          ("bla", "Färgat papper: ljusblå"), ("gra", "Färgat papper: grå"), ("annan", "Färgat papper: annan färg")]
SIZES = [("a6", "A6 stående"), ("a6l", "A6 liggande"), ("a5", "A5 stående"), ("a4", "A4")]
AUDIENCES = [("none", "Ingen särskild"), ("all", "Alla hushåll"), ("pending", "Hushåll som inte svarat"),
             ("coming", "Hushåll som kommer")]
KINDS = [("save", "Save the date"), ("invite", "Inbjudan"), ("thanks", "Tackkort"), ("menu", "Meny"),
         ("program", "Program"), ("sign", "Skylt")]

PLACEHOLDERS = ["namn", "brudpar", "initialer", "datum", "tid", "plats", "adress", "klädkod", "osa_senast", "kod", "osa_adress",
                "present", "program"]
LIMITS = {"eyebrow": 120, "heading": 120, "body": 1500, "footer": 300}

SEED = [
    {"kind": "save", "title": "Save the date", "design": "botanisk", "color": "skog", "size": "a6l", "audience": "all",
     "paper": "vit", "show_qr": 0, "eyebrow": "Save the date", "heading": "{brudpar}",
     "body": "gifter sig\n{datum}\n{plats}", "footer": "Inbjudan kommer senare"},
    {"kind": "invite", "title": "Inbjudan", "design": "klassisk", "color": "skog", "size": "a5", "audience": "all",
     "paper": "vit", "show_qr": 1, "eyebrow": "Välkommen på bröllop", "heading": "{brudpar}",
     "body": "Kära {namn}!\n\nVi gifter oss och vill så gärna fira dagen tillsammans med er.\n\n"
             "{datum} kl. {tid}\n{plats}\n{adress}",
     "footer": "Svara senast {osa_senast}: skanna koden eller gå till {osa_adress} och skriv in {kod}"},
    {"kind": "thanks", "title": "Tackkort", "design": "romantisk", "color": "rosa", "size": "a6l", "audience": "coming",
     "paper": "vit", "show_qr": 0, "eyebrow": "Tack", "heading": "Kära {namn}",
     "body": "Tack för att ni firade vår dag med oss – och för {present}. Det betyder mer än vi kan säga.",
     "footer": "Varma hälsningar, {brudpar}"},
    {"kind": "menu", "title": "Meny", "design": "klassisk", "color": "guld", "size": "a4", "audience": "none",
     "paper": "vit", "show_qr": 0, "eyebrow": "{datum}", "heading": "Meny",
     "body": "Förrätt\nSkriv förrätten här\n\nVarmrätt\nSkriv varmrätten här\n\nDessert\nSkriv desserten här\n\n"
             "Bröllopstårta och kaffe",
     "footer": "{brudpar}"},
    {"kind": "program", "title": "Program", "design": "botanisk", "color": "skog", "size": "a5", "audience": "none",
     "paper": "vit", "show_qr": 0, "eyebrow": "Dagens program", "heading": "{brudpar}", "body": "{program}", "footer": "{plats}"},
    {"kind": "sign", "title": "Välkomstskylt", "design": "modern", "color": "skog", "size": "a4", "audience": "none",
     "paper": "vit", "show_qr": 0, "eyebrow": "Välkommen till", "heading": "{brudpar}s bröllop", "body": "{datum}",
     "footer": "Dela era bilder – skanna QR-koden på borden"},
]
FIELDS = ["kind", "title", "design", "color", "paper", "size", "audience", "show_qr", "eyebrow", "heading", "body", "footer"]


def seed_cards(c) -> None:
    """Förslagen läggs in en gång; borttagna förslag kommer inte tillbaka vid omstart."""
    if c.execute("SELECT 1 FROM settings WHERE key = 'cards_seeded'").fetchone():
        return
    for i, s in enumerate(SEED):
        c.execute(f"INSERT INTO cards ({', '.join(FIELDS)}, sort_no) VALUES ({', '.join('?' * len(FIELDS))}, ?)",
                  [s[f] for f in FIELDS] + [i])
    c.execute("INSERT INTO settings (key, value) VALUES ('cards_seeded', '1')")


def seed_for(kind: str) -> dict:
    return next((s for s in SEED if s["kind"] == kind), SEED[0])


def programme_text(c) -> str:
    rows = c.execute(f"SELECT time, title FROM timeline WHERE public = 1 ORDER BY {TIMELINE_ORDER}").fetchall()
    return "\n".join(f"{r['time']}  {r['title']}" for r in rows) or "Lägg till punkter i Körschema och markera Visa för gäster"


def initials(couple: str) -> str:
    """"Louise & Anton" → "L & A", "Anna och Erik Svensson" → "A & E"."""
    parts = [p.strip() for p in re.split(r"\s*(?:&|\+|,|\boch\b|\band\b)\s*", couple or "") if p.strip()]
    return " & ".join(p[0].upper() for p in parts[:2]) if parts else ""


def common_values(s: dict, base: str, programme: str) -> dict:
    return {
        "brudpar": s.get("couple_names") or "",
        "initialer": initials(s.get("couple_names") or ""),
        "datum": sv_date(s.get("wedding_date")) or "",
        "tid": s.get("wedding_time") or "",
        "plats": s.get("venue") or "",
        "adress": s.get("address") or "",
        "klädkod": s.get("dress_code") or "",
        "osa_senast": sv_date(s.get("rsvp_deadline")) or "så snart ni kan",
        "osa_adress": base.split("://", 1)[-1] + "/osa",
        "program": programme,
        "namn": "", "kod": "", "present": "presenten",
    }


def _mid_sentence(text: str) -> str:
    """"Vas från Svenskt Tenn" → "vas från Svenskt Tenn" (står mitt i en mening). "IKEA-kort" lämnas."""
    return text[0].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def guest_values(common: dict, g) -> dict:
    return {**common, "namn": g["name"], "kod": format_code(g["rsvp_code"]) if g["rsvp_code"] else "",
            "present": _mid_sentence(g["gift_received"]) if g["gift_received"] else "den fina presenten"}


SAMPLE_GUEST = {"name": "Anna & Erik Exempel", "rsvp_code": "ABCDEFGH23", "gift_received": "den vackra vasen"}


def recipients(c, audience: str):
    where = {"all": "", "pending": "WHERE rsvp = 'pending'", "coming": "WHERE rsvp = 'yes'"}.get(audience)
    if where is None:
        return []
    return c.execute(f"SELECT id, name, rsvp_code, gift_received FROM guests {where} ORDER BY name COLLATE NOCASE").fetchall()
