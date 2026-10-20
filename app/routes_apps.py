"""Mobilappar som läggs på hemskärmen (iPhone: Safari → Dela → Lägg till på hemskärmen).

/tm   – Toastmaster: nu & härnäst med timer, talen (bocka av, flytta, ändra, lägga till) och programmet.
/plan – Planering: att göra-listan (bocka av, lägga till, ändra) och programmet.

Samma data och behörigheter som resten av appen: tal och program får ändras av admin, redigerare och
toastmaster; att göra-listan av admin och redigerare. Alla inloggade får bocka av tal som hållna."""
import datetime as dt
import json

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import db as dbm
from . import push
from .core import (BASE, auth, can_write, csrf_form, csrf_header, fill_task_deadlines, get_settings, log, parse_form,
                   public_base, render, speech_token, today)
from .entities import CATEGORIES, ENTITIES, NIGHT_CUTOFF, PACK_CATEGORIES, PERIODS, SPEECH_PARTS, TIMELINE_ORDER
from .people import coming_people
from .receipts import receipt_path, save_receipt
from .routes_day import day_context, toggle_held
from .weather import forecast

TM = {"key": "tm", "name": "Toastmaster", "manifest": "manifest-tm.json", "icon": "icon-tm-180.png",
      "tabs": [("nu", "/tm", "Nu", "⏱"), ("tal", "/tm/tal", "Tal", "🎤"), ("program", "/tm/program", "Program", "🗓")]}
PLAN = {"key": "plan", "name": "Planering", "manifest": "manifest-plan.json", "icon": "icon-plan-180.png",
        "tabs": [("todo", "/plan", "Att göra", "✓"), ("packa", "/plan/packa", "Packa", "🧳"),
                 ("utgift", "/plan/utgifter", "Utgifter", "🧾"), ("program", "/plan/program", "Program", "🗓"),
                 ("klart", "/plan/klart", "Klart", "☑")]}
APPS = {"tm": TM, "plan": PLAN}
SPEECH_FIELDS = [f for f in ENTITIES["speeches"]["fields"] if f["name"] != "guest_id"]
TIMELINE_FIELDS = ENTITIES["timeline"]["fields"]
TASK_FIELDS = ENTITIES["tasks"]["fields"]


def _app(request: Request) -> dict:
    return APPS[request.url.path.split("/")[1]]


def _render(request: Request, name: str, user, tab: str, **ctx):
    return render(request, name, user, app=_app(request), tab=tab, public_page=True, push_key=push.public_key(), **ctx)


# ======================================================================= Toastmaster: nu
async def tm_now(request: Request):
    user = auth(request)
    return _render(request, "app_tm_now.html", user, "nu", weather=forecast(), **day_context(request))


# ======================================================================= Toastmaster: tal
async def tm_speeches(request: Request):
    user = auth(request)
    ctx = day_context(request)
    with dbm.db() as c:
        struck = c.execute("SELECT id, speaker FROM speeches WHERE status = 'Struken' ORDER BY id").fetchall()
    return _render(request, "app_tm_speeches.html", user, "tal", struck=struck,
                   can_edit=can_write(user, "speeches"), **ctx)


async def tm_speech_held(request: Request):
    user = auth(request)  # även läsare – det dokumenterade undantaget
    await csrf_form(request, user)
    sid = request.path_params["item_id"]
    new = toggle_held(sid)
    log.info("speech_status id=%s status=%s by=%s app=tm", sid, new, user["username"])
    back = "/tm" if request.query_params.get("fran") == "nu" else f"/tm/tal#tal{sid}"
    return RedirectResponse(back, 303)


async def tm_speech_move(request: Request):
    """Flyttar ett tal upp eller ner inom sin del av middagen (numrerar om ordningen 1, 2, 3 …)."""
    user = auth(request, write=True, area="speeches")
    form = await csrf_form(request, user)
    sid = request.path_params["item_id"]
    with dbm.db() as c:
        sp = c.execute("SELECT id, part FROM speeches WHERE id = ?", (sid,)).fetchone()
        if not sp:
            raise HTTPException(404)
        ids = [r["id"] for r in c.execute(f"SELECT id FROM speeches WHERE part = ? AND status <> 'Struken' "
                                          f"ORDER BY {ENTITIES['speeches']['order']}", (sp["part"],))]
        i = ids.index(sid) if sid in ids else -1
        j = i - 1 if form.get("riktning") == "upp" else i + 1
        if i >= 0 and 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        c.executemany("UPDATE speeches SET order_no = ? WHERE id = ?", [(n, x) for n, x in enumerate(ids, 1)])
    return RedirectResponse(f"/tm/tal#tal{sid}", 303)


async def tm_speech_form(request: Request):
    item_id = request.path_params.get("item_id")
    write = request.method == "POST"
    user = auth(request, write=write, area="speeches")
    row = None
    if item_id is not None:
        with dbm.db() as c:
            row = c.execute("SELECT * FROM speeches WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404)
    vals, errors = (dict(row) if row else {"part": request.query_params.get("del") if request.query_params.get("del") in SPEECH_PARTS
                                           else SPEECH_PARTS[1], "minutes": 5, "status": "Bekräftad", "order_no": 99}), []
    if write:
        form = await csrf_form(request, user)
        vals, errors = parse_form(SPEECH_FIELDS, form)
        if not errors:
            cols = list(vals)
            with dbm.db() as c:
                if row:
                    c.execute(f"UPDATE speeches SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", [*vals.values(), item_id])
                else:
                    item_id = c.execute(f"INSERT INTO speeches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                        list(vals.values())).lastrowid
            log.info("speech_saved id=%s by=%s app=tm", item_id, user["username"])
            return RedirectResponse(f"/tm/tal#tal{item_id}", 303)
    link = None
    if row and can_write(user, "speeches") and row["status"] != "Struken":  # länken ger skrivrätt till talet
        with dbm.db() as c:
            link = f"{public_base(request)}/t/{speech_token(c, item_id)}"
    return _render(request, "app_form.html", user, "tal", status=400 if errors else 200, fields=SPEECH_FIELDS, vals=vals,
                   errors=errors, title=row["speaker"] if row else "Nytt tal", back="/tm/tal",
                   can_edit=can_write(user, "speeches"), share_link=link,
                   share_help="Skicka länken till talaren – där kan hen själv ändra ämne, längd och önskemål." if link else None,
                   hint="Stryk ett tal genom att sätta status till Struken – det går att ångra." if row else None)


# ======================================================================= Toastmaster: pärm att skriva ut
async def tm_binder(request: Request):
    user = auth(request)
    from .routes_reports import _by_table
    ctx = day_context(request)
    with dbm.db() as c:
        vendors = c.execute("SELECT name, category, contact, phone, email FROM vendors WHERE status = 'Bokad' "
                            "ORDER BY category, name COLLATE NOCASE").fetchall()
        tables = _by_table(coming_people(c))
    return render(request, "app_binder.html", user, public_page=True, vendors=vendors, tables=tables,
                  printed=dt.datetime.now(), **ctx)


# ======================================================================= program (båda apparna)
def _minutes(t: str) -> int:
    """Minuter sedan 06:00 på bröllopsdagen – så att 01:00 hamnar efter 23:00."""
    h, m = map(int, t.split(":"))
    mins = h * 60 + m
    return mins + 1440 if t < NIGHT_CUTOFF else mins


def _hhmm(mins: int) -> str:
    mins %= 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


async def programme(request: Request):
    user = auth(request)
    ctx = day_context(request)
    return _render(request, "app_program.html", user, "program", can_edit=can_write(user, "timeline"), **ctx)


async def programme_form(request: Request):
    app = _app(request)
    item_id = request.path_params.get("item_id")
    write = request.method == "POST"
    user = auth(request, write=write, area="timeline")
    row = None
    if item_id is not None:
        with dbm.db() as c:
            row = c.execute("SELECT * FROM timeline WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404)
    vals, errors = (dict(row) if row else {"public": 0}), []
    back = f"/{app['key']}/program"
    if write:
        form = await csrf_form(request, user)
        vals, errors = parse_form(TIMELINE_FIELDS, form)
        if not errors:
            cols = list(vals)
            with dbm.db() as c:
                if row:
                    c.execute(f"UPDATE timeline SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", [*vals.values(), item_id])
                else:
                    item_id = c.execute(f"INSERT INTO timeline ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                        list(vals.values())).lastrowid
            log.info("timeline_saved id=%s by=%s app=%s", item_id, user["username"], app["key"])
            return RedirectResponse(f"{back}#p{item_id}", 303)
    return _render(request, "app_form.html", user, "program", status=400 if errors else 200, fields=TIMELINE_FIELDS,
                   vals=vals, errors=errors, title=row["title"] if row else "Ny programpunkt", back=back,
                   can_edit=can_write(user, "timeline"),
                   delete_url=f"{back}/{item_id}/ta-bort" if row else None)


async def programme_delete(request: Request):
    app = _app(request)
    user = auth(request, write=True, area="timeline")
    await csrf_form(request, user)
    with dbm.db() as c:
        if not c.execute("DELETE FROM timeline WHERE id = ?", (request.path_params["item_id"],)).rowcount:
            raise HTTPException(404)
    log.info("timeline_deleted id=%s by=%s app=%s", request.path_params["item_id"], user["username"], app["key"])
    return RedirectResponse(f"/{app['key']}/program", 303)


async def programme_shift(request: Request):
    """Skjuter programpunkten och allt efter den ett antal minuter (t.ex. +15 när middagen drar ut på tiden)."""
    app = _app(request)
    user = auth(request, write=True, area="timeline")
    form = await csrf_form(request, user)
    try:
        start_id, delta = int(form.get("fran", "")), int(form.get("minuter", ""))
    except ValueError:
        raise HTTPException(400)
    if not -180 <= delta <= 180 or not delta:
        raise HTTPException(400)
    with dbm.db() as c:
        rows = c.execute(f"SELECT id, time FROM timeline ORDER BY {TIMELINE_ORDER}").fetchall()
        ids = [r["id"] for r in rows]
        if start_id not in ids:
            raise HTTPException(404)
        start = _minutes(rows[ids.index(start_id)]["time"])
        moved = [(_hhmm(_minutes(r["time"]) + delta), r["id"]) for r in rows if _minutes(r["time"]) >= start]
        c.executemany("UPDATE timeline SET time = ? WHERE id = ?", moved)
    log.info("timeline_shift from=%s minutes=%s n=%s by=%s app=%s", start_id, delta, len(moved), user["username"], app["key"])
    return RedirectResponse(f"/{app['key']}/program#p{start_id}", 303)


# ======================================================================= Planering: att göra
def _task_groups(c, done: bool):
    td = today()
    rows = c.execute(f"SELECT * FROM tasks WHERE done = ? ORDER BY {ENTITIES['tasks']['order']}", (1 if done else 0,)).fetchall()
    if done:
        return [("Klara", rows)] if rows else []
    soon = (td + dt.timedelta(days=30)).isoformat()
    groups = [("Försenade", [r for r in rows if r["due_date"] and r["due_date"] < td.isoformat()]),
              ("Närmaste 30 dagarna", [r for r in rows if r["due_date"] and td.isoformat() <= r["due_date"] <= soon]),
              ("Senare", [r for r in rows if r["due_date"] and r["due_date"] > soon]),
              ("Utan datum", [r for r in rows if not r["due_date"]])]
    return [(name, items) for name, items in groups if items]


async def plan_tasks(request: Request, done: bool = False):
    user = auth(request)
    with dbm.db() as c:
        groups = _task_groups(c, done)
        counts = c.execute("SELECT COALESCE(SUM(done = 0),0) AS open, COALESCE(SUM(done = 1),0) AS done FROM tasks").fetchone()
    return _render(request, "app_plan_tasks.html", user, "klart" if done else "todo", groups=groups, counts=counts,
                   done=done, can_edit=can_write(user, "tasks"), periods=PERIODS, today=today().isoformat())


async def plan_done(request: Request):
    return await plan_tasks(request, done=True)


async def plan_task_quick(request: Request):
    """Snabbt tillägg: bara uppgift och (valfritt) datum. Utan datum räknas det fram från perioden."""
    user = auth(request, write=True, area="tasks")
    form = await csrf_form(request, user)
    vals, errors = parse_form(TASK_FIELDS, {"title": form.get("title", ""), "due_date": form.get("due_date", ""),
                                            "period": form.get("period") or PERIODS[0]})
    if errors:
        raise HTTPException(400, " ".join(errors))
    with dbm.db() as c:
        c.execute(f"INSERT INTO tasks ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    if not vals.get("due_date"):
        fill_task_deadlines()
    log.info("task_added by=%s app=plan", user["username"])
    return RedirectResponse("/plan", 303)


async def plan_task_toggle(request: Request):
    user = auth(request, write=True, area="tasks")
    await csrf_form(request, user)
    tid = request.path_params["item_id"]
    with dbm.db() as c:
        if not c.execute("UPDATE tasks SET done = 1 - COALESCE(done, 0) WHERE id = ?", (tid,)).rowcount:
            raise HTTPException(404)
    back = "/plan/klart" if request.query_params.get("fran") == "klart" else "/plan"
    return RedirectResponse(f"{back}#t{tid}", 303)


async def plan_task_form(request: Request):
    item_id = request.path_params["item_id"]
    write = request.method == "POST"
    user = auth(request, write=write, area="tasks")
    with dbm.db() as c:
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    vals, errors = dict(row), []
    if write:
        form = await csrf_form(request, user)
        vals, errors = parse_form(TASK_FIELDS, form)
        if not errors:
            with dbm.db() as c:
                c.execute(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?", [*vals.values(), item_id])
            if not vals.get("due_date"):
                fill_task_deadlines()
            return RedirectResponse(f"/plan#t{item_id}", 303)
    return _render(request, "app_form.html", user, "todo", status=400 if errors else 200, fields=TASK_FIELDS, vals=vals,
                   errors=errors, title=row["title"], back="/plan", can_edit=can_write(user, "tasks"),
                   delete_url=f"/plan/uppgift/{item_id}/ta-bort")


async def plan_task_delete(request: Request):
    user = auth(request, write=True, area="tasks")
    await csrf_form(request, user)
    with dbm.db() as c:
        if not c.execute("DELETE FROM tasks WHERE id = ?", (request.path_params["item_id"],)).rowcount:
            raise HTTPException(404)
    return RedirectResponse("/plan", 303)


# ======================================================================= Planering: packlista
async def plan_packing(request: Request):
    user = auth(request)
    with dbm.db() as c:
        rows = c.execute(f"SELECT * FROM packing ORDER BY {ENTITIES['packing']['order']}").fetchall()
    groups = [(cat, [r for r in rows if r["category"] == cat]) for cat in PACK_CATEGORIES]
    other = [r for r in rows if r["category"] not in PACK_CATEGORIES]
    groups = [(cat, items) for cat, items in groups + [("Övrigt", other)] if items]
    return _render(request, "app_packing.html", user, "packa", groups=groups, categories=PACK_CATEGORIES,
                   left=sum(not r["done"] for r in rows), total=len(rows), can_edit=can_write(user, "packing"))


async def plan_pack_add(request: Request):
    user = auth(request, write=True, area="packing")
    form = await csrf_form(request, user)
    vals, errors = parse_form(ENTITIES["packing"]["fields"], {"title": form.get("title", ""), "category": form.get("category", "")})
    if errors:
        raise HTTPException(400, " ".join(errors))
    with dbm.db() as c:
        c.execute(f"INSERT INTO packing ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    return RedirectResponse("/plan/packa", 303)


async def plan_pack_toggle(request: Request):
    user = auth(request, write=True, area="packing")
    await csrf_form(request, user)
    pid = request.path_params["item_id"]
    with dbm.db() as c:
        if not c.execute("UPDATE packing SET done = 1 - COALESCE(done, 0) WHERE id = ?", (pid,)).rowcount:
            raise HTTPException(404)
    return RedirectResponse(f"/plan/packa#k{pid}", 303)


# ======================================================================= Planering: utgifter med kvitto
async def plan_expenses(request: Request):
    user = auth(request)
    errors, vals = [], {"category": "Övrigt", "paid": 1}
    if request.method == "POST":
        user = auth(request, write=True, area="budget")
        form = await request.form(max_files=1, max_fields=10, max_part_size=16 * 1024)
        await csrf_form(request, user, form)
        vals, errors = parse_form(ENTITIES["budget"]["fields"], {
            "item": form.get("item", ""), "category": form.get("category", ""), "actual": form.get("actual", ""),
            "paid": form.get("paid", ""), "notes": form.get("notes", "")})
        if not errors and not vals.get("actual"):
            errors.append("Ange beloppet.")
        receipt = None
        if not errors:
            receipt, err = await save_receipt(form.get("receipt"))
            if err:
                errors.append(err)
        if not errors:
            vals["receipt"] = receipt
            with dbm.db() as c:
                c.execute(f"INSERT INTO budget ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
            log.info("expense_added by=%s receipt=%s app=plan", user["username"], bool(receipt))
            return RedirectResponse("/plan/utgifter?ok=1", 303)
    with dbm.db() as c:
        recent = c.execute("SELECT id, item, category, actual, paid, receipt, created_at FROM budget "
                           "WHERE COALESCE(actual, 0) <> 0 ORDER BY id DESC LIMIT 30").fetchall()
        spent = c.execute("SELECT COALESCE(SUM(actual), 0) FROM budget").fetchone()[0]
    return _render(request, "app_expenses.html", user, "utgift", status=400 if errors else 200, errors=errors, vals=vals,
                   recent=recent, spent=spent, total=get_settings().get("total_budget"), categories=CATEGORIES,
                   can_edit=can_write(user, "budget"), saved=request.query_params.get("ok") == "1")


async def plan_receipt(request: Request):
    auth(request)
    with dbm.db() as c:
        row = c.execute("SELECT receipt FROM budget WHERE id = ?", (request.path_params["item_id"],)).fetchone()
    path = receipt_path(row["receipt"] if row else None, thumb=request.query_params.get("liten") == "1")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ======================================================================= Planering: kalender
async def plan_calendar(request: Request):
    """Prenumerera på deadlines och räkningar i telefonens kalender (samma länk som under Konto)."""
    user = auth(request)
    url = None
    if request.method == "POST":
        await csrf_form(request, user)
        from .routes_account import create_ics_token
        token = create_ics_token(user)
        url = f"{public_base(request)}/cal/{token}.ics"
    return _render(request, "app_calendar.html", user, "todo", ics_url=url,
                   webcal=url.replace("https://", "webcal://").replace("http://", "webcal://") if url else None)


# ======================================================================= push och service worker
SW_JS = (BASE / "static" / "sw.js")


async def service_worker(request: Request):
    """Service workern måste ligga under /tm resp. /plan för att få styra appen (scope)."""
    return Response(SW_JS.read_bytes(), media_type="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": f"/{_app(request)['key']}"})


async def push_subscribe(request: Request):
    user = auth(request)
    csrf_header(request, user)
    app = _app(request)["key"]
    try:
        body = json.loads(await request.body())
        endpoint, keys = str(body["endpoint"]), body["keys"]
        p256dh, secret = str(keys["p256dh"]), str(keys["auth"])
        if len(push.b64u_dec(p256dh)) != 65 or len(push.b64u_dec(secret)) != 16:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400)
    if not push.endpoint_ok(endpoint):
        log.warning("push_endpoint_rejected user=%s", user["username"])
        raise HTTPException(400, "Okänd push-tjänst.")
    with dbm.db() as c:
        c.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
        c.execute("INSERT INTO push_subs (user_id, app, endpoint, p256dh, auth) VALUES (?, ?, ?, ?, ?)",
                  (user["user_id"], app, endpoint, p256dh, secret))
    log.info("push_subscribed user=%s app=%s", user["username"], app)
    return JSONResponse({"ok": True})


async def push_unsubscribe(request: Request):
    user = auth(request)
    csrf_header(request, user)
    try:
        endpoint = str(json.loads(await request.body())["endpoint"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400)
    with dbm.db() as c:
        c.execute("DELETE FROM push_subs WHERE endpoint = ? AND user_id = ?", (endpoint, user["user_id"]))
    return JSONResponse({"ok": True})


async def push_test(request: Request):
    user = auth(request)
    csrf_header(request, user)
    app = _app(request)
    push.send(app["key"], app["name"], "Aviseringarna fungerar 🎉", f"/{app['key']}", user_id=user["user_id"])
    return JSONResponse({"ok": True})


routes = [
    Route("/tm", tm_now),
    Route("/tm/tal", tm_speeches),
    Route("/tm/tal/ny", tm_speech_form, methods=["GET", "POST"]),
    Route("/tm/tal/{item_id:id}", tm_speech_form, methods=["GET", "POST"]),
    Route("/tm/tal/{item_id:id}/hallen", tm_speech_held, methods=["POST"]),
    Route("/tm/tal/{item_id:id}/flytta", tm_speech_move, methods=["POST"]),
    Route("/tm/parm", tm_binder),
    Route("/plan", plan_tasks),
    Route("/plan/klart", plan_done),
    Route("/plan/uppgift/ny", plan_task_quick, methods=["POST"]),
    Route("/plan/uppgift/{item_id:id}", plan_task_form, methods=["GET", "POST"]),
    Route("/plan/uppgift/{item_id:id}/klar", plan_task_toggle, methods=["POST"]),
    Route("/plan/uppgift/{item_id:id}/ta-bort", plan_task_delete, methods=["POST"]),
    Route("/plan/packa", plan_packing),
    Route("/plan/packa/ny", plan_pack_add, methods=["POST"]),
    Route("/plan/packa/{item_id:id}", plan_pack_toggle, methods=["POST"]),
    Route("/plan/utgifter", plan_expenses, methods=["GET", "POST"]),
    Route("/plan/kvitto/{item_id:id}", plan_receipt),
    Route("/plan/kalender", plan_calendar, methods=["GET", "POST"]),
]
for _p in ("tm", "plan"):
    routes += [
        Route(f"/{_p}/program", programme),
        Route(f"/{_p}/program/ny", programme_form, methods=["GET", "POST"]),
        Route(f"/{_p}/program/forskjut", programme_shift, methods=["POST"]),
        Route(f"/{_p}/program/{{item_id:id}}", programme_form, methods=["GET", "POST"]),
        Route(f"/{_p}/program/{{item_id:id}}/ta-bort", programme_delete, methods=["POST"]),
        Route(f"/{_p}/sw.js", service_worker),
        Route(f"/{_p}/push", push_subscribe, methods=["POST"]),
        Route(f"/{_p}/push/av", push_unsubscribe, methods=["POST"]),
        Route(f"/{_p}/push/test", push_test, methods=["POST"]),
    ]
