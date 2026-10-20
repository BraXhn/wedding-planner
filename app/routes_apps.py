"""Mobilappar som läggs på hemskärmen (iPhone: Safari → Dela → Lägg till på hemskärmen).

/tm   – Toastmaster: nu & härnäst med timer, talen (bocka av, flytta, ändra, lägga till) och programmet.
/plan – Planering: att göra-listan (bocka av, lägga till, ändra) och programmet.

Samma data och behörigheter som resten av appen: tal och program får ändras av admin, redigerare och
toastmaster; att göra-listan av admin och redigerare. Alla inloggade får bocka av tal som hållna."""
import datetime as dt

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, can_write, csrf_form, fill_task_deadlines, log, parse_date, parse_form, render, today
from .entities import ENTITIES, NIGHT_CUTOFF, PERIODS, SPEECH_PARTS, TIMELINE_ORDER
from .routes_day import day_context, toggle_held

TM = {"key": "tm", "name": "Toastmaster", "manifest": "manifest-tm.json", "icon": "icon-tm-180.png",
      "tabs": [("nu", "/tm", "Nu", "⏱"), ("tal", "/tm/tal", "Tal", "🎤"), ("program", "/tm/program", "Program", "🗓")]}
PLAN = {"key": "plan", "name": "Planering", "manifest": "manifest-plan.json", "icon": "icon-plan-180.png",
        "tabs": [("todo", "/plan", "Att göra", "✓"), ("program", "/plan/program", "Program", "🗓"),
                 ("klart", "/plan/klart", "Klart", "☑")]}
APPS = {"tm": TM, "plan": PLAN}
SPEECH_FIELDS = [f for f in ENTITIES["speeches"]["fields"] if f["name"] != "guest_id"]
TIMELINE_FIELDS = ENTITIES["timeline"]["fields"]
TASK_FIELDS = ENTITIES["tasks"]["fields"]


def _app(request: Request) -> dict:
    return APPS[request.url.path.split("/")[1]]


def _render(request: Request, name: str, user, tab: str, **ctx):
    return render(request, name, user, app=_app(request), tab=tab, public_page=True, **ctx)


# ======================================================================= Toastmaster: nu
async def tm_now(request: Request):
    user = auth(request)
    return _render(request, "app_tm_now.html", user, "nu", **day_context(request))


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
    return _render(request, "app_form.html", user, "tal", status=400 if errors else 200, fields=SPEECH_FIELDS, vals=vals,
                   errors=errors, title=row["speaker"] if row else "Nytt tal", back="/tm/tal",
                   can_edit=can_write(user, "speeches"),
                   hint="Stryk ett tal genom att sätta status till Struken – det går att ångra." if row else None)


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


routes = [
    Route("/tm", tm_now),
    Route("/tm/tal", tm_speeches),
    Route("/tm/tal/ny", tm_speech_form, methods=["GET", "POST"]),
    Route("/tm/tal/{item_id:id}", tm_speech_form, methods=["GET", "POST"]),
    Route("/tm/tal/{item_id:id}/hallen", tm_speech_held, methods=["POST"]),
    Route("/tm/tal/{item_id:id}/flytta", tm_speech_move, methods=["POST"]),
    Route("/plan", plan_tasks),
    Route("/plan/klart", plan_done),
    Route("/plan/uppgift/ny", plan_task_quick, methods=["POST"]),
    Route("/plan/uppgift/{item_id:id}", plan_task_form, methods=["GET", "POST"]),
    Route("/plan/uppgift/{item_id:id}/klar", plan_task_toggle, methods=["POST"]),
    Route("/plan/uppgift/{item_id:id}/ta-bort", plan_task_delete, methods=["POST"]),
]
for _p in ("tm", "plan"):
    routes += [
        Route(f"/{_p}/program", programme),
        Route(f"/{_p}/program/ny", programme_form, methods=["GET", "POST"]),
        Route(f"/{_p}/program/forskjut", programme_shift, methods=["POST"]),
        Route(f"/{_p}/program/{{item_id:id}}", programme_form, methods=["GET", "POST"]),
        Route(f"/{_p}/program/{{item_id:id}}/ta-bort", programme_delete, methods=["POST"]),
    ]
