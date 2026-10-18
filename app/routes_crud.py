import csv
import io

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from . import db as dbm
from .core import (
    SWISH_MSG_RE, auth, csrf_form, display, fill_task_deadlines, normalize_swish, get_settings, load_refs, log, move_task_deadlines, parse_date, parse_form,
    public_base, render, set_settings, sync_speech_from_guest, today,
)
from .entities import ENTITIES, SETTINGS_FIELDS
from .routes_mail import parse_addresses
from .people import parse_people, people_for, save_people, trim_people
from .security import format_code, new_code, new_token


def get_spec(request: Request) -> tuple[str, dict]:
    ent = request.path_params["ent"]
    if ent not in ENTITIES:
        raise HTTPException(404)
    return ent, ENTITIES[ent]


def get_item(c, ent: str, item_id: int):
    row = c.execute(f"SELECT * FROM {ent} WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def normalize_attending(vals: dict) -> None:
    """"Kommer" utan angivet antal → hela hushållet kommer. "Kommer inte" → 0."""
    if vals.get("rsvp") == "yes" and not vals.get("attending"):
        vals["attending"] = vals.get("invited_count") or 1
    elif vals.get("rsvp") == "no":
        vals["attending"] = 0


def sync_budget_from_vendor(c, vendor_id: int) -> None:
    """Bokad leverantör med pris → budgetpost med priset som budgeterat belopp (skapas eller uppdateras).
    Faktiskt belopp, betalning och förfallodatum ändras aldrig härifrån."""
    v = c.execute("SELECT id, name, category, status, price FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    if not v or v["status"] != "Bokad" or v["price"] is None:
        return
    b = c.execute("SELECT id FROM budget WHERE vendor_id = ? ORDER BY id LIMIT 1", (vendor_id,)).fetchone()
    if b:
        c.execute("UPDATE budget SET estimated = ? WHERE id = ?", (v["price"], b["id"]))
    else:
        c.execute("INSERT INTO budget (item, category, estimated, paid, vendor_id) VALUES (?, ?, ?, 0, ?)",
                  (v["name"], v["category"], v["price"], v["id"]))


def rsvp_link(request: Request, token: str | None) -> str:
    return f"{public_base(request)}/r/{token}" if token else ""


def _back(ent: str, spec: dict) -> str:
    return spec.get("back", f"/m/{ent}")


# ======================================================================= översikt
async def dashboard(request: Request):
    user = auth(request)
    s = get_settings()
    if s.get("app_url") != public_base(request):  # adressen till länken i veckobrevet (skickas utan förfrågan)
        set_settings({"app_url": public_base(request)})
    td = today()
    with dbm.db() as c:
        g = c.execute(
            """SELECT COUNT(*) AS households,
                      COALESCE(SUM(invited_count),0) AS invited,
                      COALESCE(SUM(CASE WHEN rsvp='yes' THEN attending END),0) AS coming,
                      COALESCE(SUM(CASE WHEN rsvp='no' THEN invited_count END),0) AS declined,
                      COALESCE(SUM(CASE WHEN rsvp='pending' THEN invited_count END),0) AS pending,
                      COALESCE(SUM(rsvp='yes' AND (COALESCE(diet,'') <> '' OR EXISTS (
                          SELECT 1 FROM guest_people p WHERE p.guest_id = guests.id AND p.attending = 1
                          AND COALESCE(p.allergies,'') <> ''))),0) AS diets,
                      COALESCE(SUM(rsvp<>'no' AND table_id IS NULL),0) AS unseated
               FROM guests"""
        ).fetchone()
        b = c.execute(
            """SELECT COALESCE(SUM(estimated),0) AS estimated,
                      COALESCE(SUM(COALESCE(actual, estimated)),0) AS planned,
                      COALESCE(SUM(CASE WHEN paid=1 THEN COALESCE(actual, estimated) END),0) AS paid
               FROM budget"""
        ).fetchone()
        t = c.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(done=0),0) AS open, "
            "COALESCE(SUM(done=0 AND due_date <> '' AND due_date < ?),0) AS overdue FROM tasks", (td.isoformat(),)
        ).fetchone()
        upcoming = c.execute(
            f"SELECT * FROM tasks WHERE done=0 ORDER BY {ENTITIES['tasks']['order']} LIMIT 6"
        ).fetchall()
        bills = c.execute(
            "SELECT * FROM budget WHERE paid=0 AND due_date <> '' ORDER BY due_date LIMIT 5"
        ).fetchall()
        v = c.execute("SELECT COUNT(*) AS total, COALESCE(SUM(status='Bokad'),0) AS booked FROM vendors").fetchone()
        sp = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(minutes),0) AS minutes FROM speeches WHERE status <> 'Struken'").fetchone()
        w = c.execute("SELECT COALESCE(SUM(quantity),0) AS wanted, "
                      "(SELECT COALESCE(SUM(qty),0) FROM gift_reservations) AS reserved FROM wishlist").fetchone()
        ph = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(hidden),0) AS hidden FROM photos").fetchone()
    wd = parse_date(s.get("wedding_date"))
    days_left = (wd - td).days if wd else None
    total_budget = int(s["total_budget"]) if s.get("total_budget") else None
    return render(request, "dashboard.html", user, settings=s, g=g, b=b, t=t, v=v, sp=sp, w=w, ph=ph,
                  upcoming=upcoming, bills=bills, days_left=days_left, wedding_date=wd,
                  total_budget=total_budget, today=td.isoformat(), active="home")


# ======================================================================= generisk CRUD
async def list_view(request: Request):
    user = auth(request)
    ent, spec = get_spec(request)
    q = request.query_params.get("q", "")[:100].strip()
    flt = request.query_params.get("f", "")
    where, params = [], []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(" + " OR ".join(f"COALESCE({col},'') LIKE ? ESCAPE '\\'" for col in spec["search"]) + ")")
        params += [like] * len(spec["search"])
    if ent == "guests" and flt in ("pending", "yes", "no"):
        where.append("rsvp = ?")
        params.append(flt)
    if ent == "tasks" and flt in ("open", "done"):
        where.append("done = ?")
        params.append(1 if flt == "done" else 0)
    if ent == "speeches" and flt == "active":
        where.append("status <> 'Struken'")
    extra = "".join(f", {sql} AS {name}" for name, _, sql in spec["computed"])
    sql = (f"SELECT *{extra} FROM {ent}" + (" WHERE " + " AND ".join(where) if where else "")
           + f" ORDER BY {spec['order']}")
    with dbm.db() as c:
        rows = c.execute(sql, params).fetchall()
    totals = {col: sum((r[col] or 0) for r in rows) for col in spec["sum"]}
    if ent == "guests":
        totals["attending"] = sum((r["attending"] or 0) for r in rows if r["rsvp"] == "yes")
    if ent == "speeches":
        totals["minutes"] = sum((r["minutes"] or 0) for r in rows if r["status"] != "Struken")
    return render(request, "list.html", user, ent=ent, spec=spec, rows=rows, q=q, flt=flt, totals=totals,
                  refs=load_refs(spec), can_write=user["role"] != "viewer", today=today().isoformat(), active=ent)


async def item_form(request: Request):
    ent, spec = get_spec(request)
    item_id = request.path_params.get("item_id")
    user = auth(request, write=request.method == "POST")
    refs = load_refs(spec)
    row, link = None, ""
    if item_id is not None:
        with dbm.db() as c:
            row = get_item(c, ent, item_id)
        if ent == "guests":
            link = rsvp_link(request, row["rsvp_token"])
    qr = code = None
    if user["role"] == "viewer":
        link = ""  # läsare (t.ex. toastmaster) ska inte kunna svara i gästernas namn
    elif ent == "guests" and row is not None and row["rsvp_code"]:
        from markupsafe import Markup
        from .qr import qr_svg
        qr = Markup(qr_svg(f"{public_base(request)}/o/{row['rsvp_code']}"))  # SVG genererad av oss själva
        code = format_code(row["rsvp_code"])
    ctx = dict(ent=ent, spec=spec, item=row, link=link, refs=refs, back=_back(ent, spec), qr=qr, code=code,
               osa_host=public_base(request).split("://", 1)[-1],
               active="seating" if ent == "tables" else ent)

    if ent == "guests" and row is not None:
        with dbm.db() as c:
            ctx["people"] = people_for(c, row)
            ctx["qa"] = c.execute("SELECT q.label, a.value FROM answers a JOIN questions q ON q.id = a.question_id "
                                  "WHERE a.guest_id = ? ORDER BY q.sort_no, q.id", (row["id"],)).fetchall()
    if ent == "vendors" and row is not None:
        with dbm.db() as c:
            ctx["budget_item"] = c.execute("SELECT id, item FROM budget WHERE vendor_id = ? ORDER BY id LIMIT 1",
                                           (row["id"],)).fetchone()
    if request.method == "GET":
        vals = dict(row) if row else {f["name"]: f.get("default") for f in spec["fields"]}
        return render(request, "form.html", user, vals=vals, can_write=user["role"] != "viewer", **ctx)

    form = await csrf_form(request, user)
    vals, errors = parse_form(spec["fields"], form, refs)
    if ent == "guests" and not errors:
        normalize_attending(vals)
        if vals.get("rsvp") == "yes" and vals["attending"] > vals["invited_count"]:
            errors.append("Antal som kommer kan inte vara fler än antal inbjudna.")
    if errors:
        return render(request, "form.html", user, status=400, vals=vals, errors=errors, can_write=True, **ctx)
    cols = list(vals)
    with dbm.db() as c:
        if row is None:
            if ent == "guests":
                vals["rsvp_token"] = new_token(24)
                vals["rsvp_code"] = new_code()
                cols += ["rsvp_token", "rsvp_code"]
            item_id = c.execute(f"INSERT INTO {ent} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                [vals[k] for k in cols]).lastrowid
        else:
            c.execute(f"UPDATE {ent} SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                      [vals[k] for k in cols] + [item_id])
        if ent == "guests":
            sync_speech_from_guest(c, item_id)
            trim_people(c, item_id, vals["invited_count"])
        if ent == "vendors":
            sync_budget_from_vendor(c, item_id)
    if ent == "tasks" and not vals.get("due_date"):
        fill_task_deadlines()
    return RedirectResponse(_back(ent, spec), 303)


def delete_cleanup(c, ent: str, item_id: int) -> None:
    """Nollställer referenser till posten i andra tabeller (SQLite-kolumnerna saknar FK)."""
    for other, ospec in ENTITIES.items():
        for f in ospec["fields"]:
            if f["type"] == "ref" and f["ref"] == ent:
                c.execute(f"UPDATE {other} SET {f['name']} = NULL WHERE {f['name']} = ?", (item_id,))
    if ent == "guests":
        c.execute("DELETE FROM gift_reservations WHERE guest_id = ?", (item_id,))
        c.execute("DELETE FROM guest_people WHERE guest_id = ?", (item_id,))
        c.execute("DELETE FROM answers WHERE guest_id = ?", (item_id,))
        c.execute("UPDATE photos SET guest_id = NULL WHERE guest_id = ?", (item_id,))
    if ent == "wishlist":
        c.execute("DELETE FROM gift_reservations WHERE gift_id = ?", (item_id,))
    if ent == "questions":
        c.execute("DELETE FROM answers WHERE question_id = ?", (item_id,))


async def item_delete(request: Request):
    ent, spec = get_spec(request)
    user = auth(request, write=True)
    await csrf_form(request, user)
    item_id = request.path_params["item_id"]
    with dbm.db() as c:
        get_item(c, ent, item_id)
        delete_cleanup(c, ent, item_id)
        c.execute(f"DELETE FROM {ent} WHERE id = ?", (item_id,))
    log.info("deleted %s id=%s by=%s", ent, item_id, user["username"])
    return RedirectResponse(_back(ent, spec), 303)


async def task_toggle(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    with dbm.db() as c:
        get_item(c, "tasks", request.path_params["item_id"])
        c.execute("UPDATE tasks SET done = 1 - COALESCE(done,0) WHERE id = ?", (request.path_params["item_id"],))
    nxt = form.get("next")  # vitlistad – ingen open redirect
    return RedirectResponse(nxt if nxt in ("/", "/m/tasks", "/m/tasks?f=open") else "/m/tasks", 303)


async def task_deadlines(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    if not parse_date(get_settings().get("wedding_date")):
        raise HTTPException(400, "Ange bröllopsdatum under Inställningar först.")
    n = fill_task_deadlines(only_empty=form.get("mode") != "all")
    log.info("deadlines_filled n=%s by=%s", n, user["username"])
    return RedirectResponse("/m/tasks", 303)


async def guest_newlink(request: Request):
    user = auth(request, write=True)
    await csrf_form(request, user)
    item_id = request.path_params["item_id"]
    with dbm.db() as c:
        get_item(c, "guests", item_id)
        c.execute("UPDATE guests SET rsvp_token = ?, rsvp_code = ? WHERE id = ?", (new_token(24), new_code(), item_id))
    return RedirectResponse(f"/m/guests/{item_id}", 303)


async def guest_people(request: Request):
    """Personerna i ett hushåll (namn, kommer, allergier) – samma uppgifter som gästen fyller i vid OSA."""
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    item_id = request.path_params["item_id"]
    with dbm.db() as c:
        g = get_item(c, "guests", item_id)
        people, errors = parse_people(form, g["invited_count"] or 1)
        coming = sum(p["attending"] for p in people)
        if g["rsvp"] == "yes" and not coming:
            errors.append("Minst en person måste komma när hushållet svarat ”Kommer”.")
        if errors:
            raise HTTPException(400, " ".join(errors))
        save_people(c, item_id, people)
        if g["rsvp"] == "yes":
            c.execute("UPDATE guests SET attending = ? WHERE id = ?", (coming, item_id))
    log.info("guest_people guest=%s by=%s", item_id, user["username"])
    return RedirectResponse(f"/m/guests/{item_id}#personer", 303)


def csv_cell(v) -> str:
    s = "" if v is None else str(v)
    # skydd mot CSV/formel-injektion i Excel
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


async def export_csv(request: Request):
    user = auth(request)
    ent, spec = get_spec(request)
    refs = load_refs(spec)
    extra = "".join(f", {sql} AS {name}" for name, _, sql in spec["computed"])
    with dbm.db() as c:
        rows = c.execute(f"SELECT *{extra} FROM {ent} ORDER BY {spec['order']}").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    with_links = ent == "guests" and user["role"] != "viewer"  # läsare får inte gästernas OSA-länkar
    w.writerow([f["label"] for f in spec["fields"]] + [lab for _, lab, _ in spec["computed"]]
               + (["OSA-länk", "OSA-kod", "QR-länk"] if with_links else []))
    for r in rows:
        line = [csv_cell(display(f, r[f["name"]], refs) if f["type"] in ("select", "bool", "ref") else r[f["name"]])
                for f in spec["fields"]]
        line += [csv_cell(r[name]) for name, _, _ in spec["computed"]]
        if with_links:
            line += [rsvp_link(request, r["rsvp_token"]), format_code(r["rsvp_code"]),
                     f"{public_base(request)}/o/{r['rsvp_code']}" if r["rsvp_code"] else ""]
        w.writerow(line)
    log.info("export %s by=%s", ent, user["username"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{ent}-{today().isoformat()}.csv"'})


# ======================================================================= inställningar
async def settings_view(request: Request):
    write = request.method == "POST"
    user = auth(request, write=write)
    if not write:
        return render(request, "settings.html", user, fields=SETTINGS_FIELDS, vals=get_settings(),
                      can_write=user["role"] != "viewer", active="settings")
    form = await csrf_form(request, user)
    vals, errors = parse_form(SETTINGS_FIELDS, form)
    addrs, addr_err = parse_addresses(vals.get("notify_email") or "")
    if addr_err:
        errors.append(f"Mejla oss när någon svarar: {addr_err}.")
    vals["notify_email"] = ", ".join(addrs)
    if vals.get("swish_number"):
        vals["swish_number"] = normalize_swish(vals["swish_number"]) or vals["swish_number"]
        if not normalize_swish(vals["swish_number"]):
            errors.append("Swish-nummer: ange ett mobilnummer (07…) eller ett Swish-nummer (123…).")
    if not SWISH_MSG_RE.fullmatch(vals.get("swish_message") or ""):
        errors.append("Meddelande i Swish: högst 50 tecken – bokstäver, siffror och ! ? ( ) , . : \" @ -")
    if len(vals.get("osa_card_footer") or "") > 300:
        errors.append("Text under koden på OSA-korten: högst 300 tecken.")
    if errors:
        return render(request, "settings.html", user, status=400, fields=SETTINGS_FIELDS, vals=vals,
                      errors=errors, can_write=True, active="settings")
    old_wd = parse_date(get_settings().get("wedding_date"))
    set_settings(vals)
    new_wd = parse_date(vals.get("wedding_date"))
    moved = move_task_deadlines(old_wd, new_wd) if old_wd and new_wd and old_wd != new_wd else 0
    filled = fill_task_deadlines()
    return render(request, "settings.html", user, fields=SETTINGS_FIELDS, vals=get_settings(),
                  can_write=True, saved=True, filled=filled, moved=moved, active="settings")


routes = [
    Route("/", dashboard),
    Route("/m/tasks/deadlines", task_deadlines, methods=["POST"]),
    Route("/m/{ent}", list_view),
    Route("/m/{ent}/export.csv", export_csv),
    Route("/m/{ent}/new", item_form, methods=["GET", "POST"]),
    Route("/m/{ent}/{item_id:id}", item_form, methods=["GET", "POST"]),
    Route("/m/{ent}/{item_id:id}/delete", item_delete, methods=["POST"]),
    Route("/m/tasks/{item_id:id}/toggle", task_toggle, methods=["POST"]),
    Route("/m/guests/{item_id:id}/newlink", guest_newlink, methods=["POST"]),
    Route("/m/guests/{item_id:id}/people", guest_people, methods=["POST"]),
    Route("/settings", settings_view, methods=["GET", "POST"]),
]
