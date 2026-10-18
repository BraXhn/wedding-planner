"""Import av gästlistan: klistra in från Excel/Numbers/Google Kalkylark eller ladda upp en CSV-fil.

Steg 1 tolkar texten och visar en förhandsvisning (inget sparas). Steg 2 sparar de giltiga raderna.
Hushåll vars namn redan finns hoppas över, så att en import kan göras om utan dubbletter."""
import csv
import io

from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, log, parse_form, render
from .entities import ENTITIES
from .security import new_code, new_token

MAX_ROWS = 1000
MAX_TEXT = 200_000
# rubrik i filen (gemener, utan mellanslag i kanterna) → fält
ALIASES = {
    "name": ("namn", "name", "hushåll", "hushall", "gäst", "gast", "gäster"),
    "email": ("e-post", "epost", "email", "e-mail", "mejl", "mail"),
    "phone": ("telefon", "tel", "mobil", "phone"),
    "street": ("gatuadress", "adress", "address", "gata"),
    "postcode": ("postnummer", "postnr", "post nr", "zip"),
    "city": ("ort", "postort", "stad", "city"),
    "invited_count": ("antal", "antal inbjudna", "inbjudna", "personer", "antal personer"),
    "group_name": ("grupp", "group", "kategori"),
    "side": ("sida", "side"),
    "notes": ("anteckningar", "anteckning", "notes", "kommentar"),
}
FIELDS = list(ALIASES)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):  # Excel på svenska Windows sparar CSV som cp1252
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_rows(text: str) -> tuple[list[dict], list[str]]:
    """Returnerar (rader, varningar). Varje rad: {"vals", "errors", "line"}. Avgränsare gissas (tab, ; eller ,)."""
    text = text.strip("﻿\r\n ")
    if not text:
        return [], ["Ingen text att importera."]
    first = text.splitlines()[0]
    delim = max(("\t", ";", ","), key=first.count) if any(d in first for d in "\t;,") else ";"
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = [h.strip().lower() for h in next(reader, [])]
    cols = {}
    for i, h in enumerate(header):
        for field, names in ALIASES.items():
            if h in names and field not in cols:
                cols[field] = i
    warnings = []
    if "name" not in cols:
        return [], ["Hittade ingen kolumn med namn. Första raden måste vara rubriker, t.ex. Namn; E-post; Antal; Grupp."]
    unknown = [h for i, h in enumerate(header) if h and i not in cols.values()]
    if unknown:
        warnings.append("Kolumner som inte används: " + ", ".join(unknown[:8]))
    spec = ENTITIES["guests"]
    fields = [spec["by_name"][f] for f in FIELDS]
    side_opts = {lab.lower(): val for val, lab in spec["by_name"]["side"]["options"]}
    rows = []
    for n, line in enumerate(reader, start=2):
        if not any(c.strip() for c in line):
            continue
        if len(rows) >= MAX_ROWS:
            warnings.append(f"Bara de första {MAX_ROWS} raderna tas med.")
            break
        raw = {f: (line[i].strip() if i < len(line) else "") for f, i in cols.items()}
        raw["side"] = side_opts.get(raw.get("side", "").lower(), "Gemensam")
        raw.setdefault("invited_count", "")
        vals, errors = parse_form(fields, raw)
        rows.append({"line": n, "vals": vals, "errors": errors})
    return rows, warnings


def _mark_existing(rows: list[dict]) -> None:
    with dbm.db() as c:
        existing = {r[0].casefold() for r in c.execute("SELECT name FROM guests")}
    seen = set()
    for r in rows:
        key = (r["vals"].get("name") or "").casefold()
        r["duplicate"] = key in existing or key in seen
        seen.add(key)


async def _read_input(request: Request, user) -> str:
    form = await request.form(max_files=1, max_fields=10, max_part_size=MAX_TEXT)
    await csrf_form(request, user, form)
    up = form.get("file")
    if isinstance(up, UploadFile) and (up.filename or up.size):
        data = await up.read(MAX_TEXT + 1)
        if len(data) > MAX_TEXT:
            raise HTTPException(413, "Filen är för stor (högst 200 kB).")
        return _decode(data)
    return str(form.get("text", ""))[:MAX_TEXT]


async def import_view(request: Request):
    user = auth(request, write=True)
    if request.method == "GET":
        return render(request, "import.html", user, active="guests", aliases=ALIASES)
    form_text = await _read_input(request, user)
    rows, warnings = parse_rows(form_text)
    _mark_existing(rows)
    ok = [r for r in rows if not r["errors"] and not r["duplicate"]]
    return render(request, "import.html", user, active="guests", aliases=ALIASES, rows=rows, warnings=warnings,
                  ok_count=len(ok), text=form_text)


async def import_save(request: Request):
    user = auth(request, write=True)
    form = await request.form(max_files=0, max_fields=10, max_part_size=MAX_TEXT)
    await csrf_form(request, user, form)
    rows, _ = parse_rows(str(form.get("text", ""))[:MAX_TEXT])
    _mark_existing(rows)
    saved = 0
    with dbm.db() as c:
        for r in rows:
            if r["errors"] or r["duplicate"]:
                continue
            vals = {**r["vals"], "rsvp": "pending", "attending": 0, "rsvp_token": new_token(24), "rsvp_code": new_code()}
            c.execute(f"INSERT INTO guests ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
            saved += 1
    log.info("guests_import n=%s by=%s", saved, user["username"])
    return RedirectResponse(f"/m/guests?importerade={saved}", 303)


routes = [
    Route("/m/guests/import", import_view, methods=["GET", "POST"]),
    Route("/m/guests/import/spara", import_save, methods=["POST"]),
]
