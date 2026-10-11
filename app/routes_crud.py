import csv
import io

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from . import db as dbm
from .core import (
    auth, csrf_form, display, fill_task_deadlines, get_settings, load_refs, log, parse_date, parse_form,
    public_base, render, set_settings, sync_speech_from_guest, today,
)
from .entities import ENTITIES, SETTINGS_FIELDS
from .security import new_token


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


def rsvp_link(request: Request, token: str | None) -> str:
    return f"{public_base(request)}/r/{token}" if token else ""


def _back(ent: str, spec: dict) -> str:
    return spec.get("back", f"/m/{ent}")


# ======================================================================= översikt
async def dashboard(request: Request):
    user = auth(request)
    s = get_settings()
    td = today()
    with dbm.db() as c:
        g = c.execute(
            """SELECT COUNT(*) AS households,
                      COALESCE(SUM(invited_count),0) AS invited,
                      COALESCE(SUM(CASE WHEN rsvp='yes' THEN attending END),0) AS coming,
                      COALESCE(SUM(CASE WHEN rsvp='no' THEN invited_count END),0) AS declined,
                      COALESCE(SUM(CASE WHEN rsvp='pending' THEN invited_count END),0) AS pending,
                      COALESCE(SUM(rsvp='yes' AND COALESCE(diet,'') <> ''),0) AS diets,
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
    ctx = dict(ent=ent, spec=spec, item=row, link=link, refs=refs, back=_back(ent, spec),
               active="seating" if ent == "tables" else ent)

    if request.method == "GET":
        vals = dict(row) if row else {f["name"]: f.get("default") for f in spec["fields"]}
        return render(request, "form.html", user, vals=vals, can_write=user["role"] != "viewer", **ctx)

    form = await csrf_form(request, user)
    vals, errors = parse_form(spec["fields"], form, refs)
    if errors:
        return render(request, "form.html", user, status=400, vals=vals, errors=errors, can_write=True, **ctx)
    cols = list(vals)
    with dbm.db() as c:
        if row is None:
            if ent == "guests":
                vals["rsvp_token"] = new_token(24)
                cols.append("rsvp_token")
            item_id = c.execute(f"INSERT INTO {ent} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                [vals[k] for k in cols]).lastrowid
        else:
            c.execute(f"UPDATE {ent} SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                      [vals[k] for k in cols] + [item_id])
        if ent == "guests":
            sync_speech_from_guest(c, item_id)
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
        c.execute("UPDATE photos SET guest_id = NULL WHERE guest_id = ?", (item_id,))
    if ent == "wishlist":
        c.execute("DELETE FROM gift_reservations WHERE gift_id = ?", (item_id,))


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
        c.execute("UPDATE guests SET rsvp_token = ? WHERE id = ?", (new_token(24), item_id))
    return RedirectResponse(f"/m/guests/{item_id}", 303)


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
    w.writerow([f["label"] for f in spec["fields"]] + [lab for _, lab, _ in spec["computed"]]
               + (["OSA-länk"] if ent == "guests" else []))
    for r in rows:
        line = [csv_cell(display(f, r[f["name"]], refs) if f["type"] in ("select", "bool", "ref") else r[f["name"]])
                for f in spec["fields"]]
        line += [csv_cell(r[name]) for name, _, _ in spec["computed"]]
        if ent == "guests":
            line.append(rsvp_link(request, r["rsvp_token"]))
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
    if errors:
        return render(request, "settings.html", user, status=400, fields=SETTINGS_FIELDS, vals=vals,
                      errors=errors, can_write=True, active="settings")
    set_settings(vals)
    filled = fill_task_deadlines()
    return render(request, "settings.html", user, fields=SETTINGS_FIELDS, vals=get_settings(),
                  can_write=True, saved=True, filled=filled, active="settings")


routes = [
    Route("/", dashboard),
    Route("/m/tasks/deadlines", task_deadlines, methods=["POST"]),
    Route("/m/{ent}", list_view),
    Route("/m/{ent}/export.csv", export_csv),
    Route("/m/{ent}/new", item_form, methods=["GET", "POST"]),
    Route("/m/{ent}/{item_id:int}", item_form, methods=["GET", "POST"]),
    Route("/m/{ent}/{item_id:int}/delete", item_delete, methods=["POST"]),
    Route("/m/tasks/{item_id:int}/toggle", task_toggle, methods=["POST"]),
    Route("/m/guests/{item_id:int}/newlink", guest_newlink, methods=["POST"]),
    Route("/settings", settings_view, methods=["GET", "POST"]),
]
