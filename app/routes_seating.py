import json
import re

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, csrf_header, get_settings, log, render, set_settings

PLAN_RATIOS = [("liggande", "Liggande"), ("kvadrat", "Kvadratisk"), ("staende", "Stående")]
MAX_LABELS, LABEL_MAX = 30, 40


def seat_need(g) -> int:
    """Platser ett hushåll tar: antal som kommer om de svarat ja, annars antal inbjudna."""
    return (g["attending"] or 0) if g["rsvp"] == "yes" else (g["invited_count"] or 1)


async def seating(request: Request):
    user = auth(request)
    with dbm.db() as c:
        tables = [dict(t) for t in c.execute("SELECT * FROM tables ORDER BY sort_no, name COLLATE NOCASE")]
        guests = [dict(g) for g in c.execute(
            "SELECT id, name, rsvp, attending, invited_count, table_id, group_name, "
            "TRIM(COALESCE(diet,'') || ' ' || COALESCE((SELECT group_concat(p.name || ': ' || p.allergies, '; ') "
            "FROM guest_people p WHERE p.guest_id = guests.id AND p.attending = 1 AND COALESCE(p.allergies,'') <> ''),'')) "
            "AS diet FROM guests "
            "WHERE rsvp <> 'no' ORDER BY group_name COLLATE NOCASE, name COLLATE NOCASE")]
    for g in guests:
        g["need"] = seat_need(g)
    by_table = {t["id"]: [] for t in tables}
    unseated = []
    for g in guests:
        (by_table[g["table_id"]] if g["table_id"] in by_table else unseated).append(g)
    for t in tables:
        t["guests"] = by_table[t["id"]]
        t["used"] = sum(g["need"] for g in t["guests"])
    total_seats = sum(t["seats"] or 0 for t in tables)
    total_need = sum(g["need"] for g in guests)
    qp = request.query_params
    nums = [qp.get("placerade", ""), qp.get("kvar", "0")]
    result = tuple(int(x) for x in nums) if all(re.fullmatch(r"[0-9]{1,4}", x) for x in nums) else None
    return render(request, "seating.html", user, tables=tables, unseated=unseated, total_seats=total_seats, result=result,
                  total_need=total_need, can_write=not user["readonly"], active="seating",
                  print_mode=request.query_params.get("print") == "1")


async def seating_assign(request: Request):
    user = auth(request, write=True)
    csrf_header(request, user)
    body = await request.body()
    try:
        data = json.loads(body)
        guest_id = int(data["guest_id"])
        table_id = data.get("table_id")
        table_id = int(table_id) if table_id not in (None, "", 0, "0") else None
        if not 0 < guest_id < 2**63 or not (table_id is None or 0 < table_id < 2**63):
            raise ValueError
    except (ValueError, KeyError, TypeError, OverflowError):
        raise HTTPException(400)
    with dbm.db() as c:
        if not c.execute("SELECT 1 FROM guests WHERE id = ?", (guest_id,)).fetchone():
            raise HTTPException(404)
        if table_id is not None and not c.execute("SELECT 1 FROM tables WHERE id = ?", (table_id,)).fetchone():
            raise HTTPException(404)
        c.execute("UPDATE guests SET table_id = ? WHERE id = ?", (table_id, guest_id))
    log.info("seating guest=%s table=%s by=%s", guest_id, table_id, user["username"])
    return JSONResponse({"ok": True})


async def seating_suggest(request: Request):
    """Placerar hushåll utan bord enligt seating_plan.suggest. Redan placerade flyttas inte."""
    from .seating_plan import suggest
    user = auth(request, write=True)
    await csrf_form(request, user)
    with dbm.db() as c:
        c.execute("BEGIN IMMEDIATE")
        plan, left = suggest(c)
        c.executemany("UPDATE guests SET table_id = ? WHERE id = ?", [(t, g) for g, t in plan])
    log.info("seating_suggest placed=%s left=%s by=%s", len(plan), len(left), user["username"])
    return RedirectResponse(f"/seating?placerade={len(plan)}&kvar={len(left)}", 303)


async def seating_clear(request: Request):
    user = auth(request, write=True)
    await csrf_form(request, user)
    with dbm.db() as c:
        n = c.execute("UPDATE guests SET table_id = NULL WHERE table_id IS NOT NULL").rowcount
    log.info("seating_clear n=%s by=%s", n, user["username"])
    return RedirectResponse("/seating", 303)


def _plan_settings() -> dict:
    try:
        plan = json.loads(get_settings().get("floor_plan") or "{}")
    except ValueError:
        plan = {}
    ratio = plan.get("ratio") if plan.get("ratio") in dict(PLAN_RATIOS) else "liggande"
    return {"ratio": ratio, "labels": plan.get("labels") or []}


async def floor_plan(request: Request):
    """Planritning: borden dras dit de står i lokalen. Bord som aldrig placerats läggs ut i ett rutnät."""
    user = auth(request)
    with dbm.db() as c:
        tables = [dict(t) for t in c.execute("SELECT * FROM tables ORDER BY sort_no, name COLLATE NOCASE")]
        guests = c.execute("SELECT name, rsvp, attending, invited_count, table_id FROM guests "
                           "WHERE rsvp <> 'no' AND table_id IS NOT NULL ORDER BY name COLLATE NOCASE").fetchall()
    cols = max(1, min(6, round(len(tables) ** 0.5 + 0.5)))
    for i, t in enumerate(tables):
        t["used"] = sum(seat_need(g) for g in guests if g["table_id"] == t["id"])
        t["names"] = [g["name"] for g in guests if g["table_id"] == t["id"]]
        if t["pos_x"] is None or t["pos_y"] is None:
            t["pos_x"] = round(100 * (i % cols + 0.5) / cols, 1)
            t["pos_y"] = round(min(92, 14 + 22 * (i // cols)), 1)
    return render(request, "floor_plan.html", user, tables=tables, plan=_plan_settings(), ratios=PLAN_RATIOS,
                  can_write=not user["readonly"], label_max=LABEL_MAX, active="seating")


def _pos(v) -> float:
    v = float(v)
    if not 0 <= v <= 100:  # även NaN faller här
        raise ValueError
    return round(v, 1)


async def floor_plan_save(request: Request):
    user = auth(request, write=True, area="tables")
    csrf_header(request, user)
    try:
        data = json.loads(await request.body())
        tables = [(_pos(t["x"]), _pos(t["y"]), 90 if int(t.get("rot") or 0) == 90 else 0, int(t["id"]))
                  for t in data.get("tables", [])][:200]
        labels = [{"text": " ".join(str(lab["text"]).split())[:LABEL_MAX], "x": _pos(lab["x"]), "y": _pos(lab["y"])}
                  for lab in data.get("labels", [])]
        ratio = data.get("ratio")
        if len(labels) > MAX_LABELS or ratio not in dict(PLAN_RATIOS) or not all(lab["text"] for lab in labels):
            raise ValueError
    except (ValueError, KeyError, TypeError, OverflowError, AttributeError):
        raise HTTPException(400)
    with dbm.db() as c:
        c.executemany("UPDATE tables SET pos_x = ?, pos_y = ?, rot = ? WHERE id = ?", tables)
    set_settings({"floor_plan": json.dumps({"ratio": ratio, "labels": labels})})
    log.info("floor_plan_saved tables=%s labels=%s by=%s", len(tables), len(labels), user["username"])
    return JSONResponse({"ok": True})


routes = [
    Route("/seating/plan", floor_plan),
    Route("/seating/plan", floor_plan_save, methods=["POST"]),
    Route("/seating/forslag", seating_suggest, methods=["POST"]),
    Route("/seating/tom", seating_clear, methods=["POST"]),
    Route("/seating", seating),
    Route("/seating/assign", seating_assign, methods=["POST"]),
]
