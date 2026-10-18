import json
import re

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, csrf_header, log, render


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
                  total_need=total_need, can_write=user["role"] != "viewer", active="seating",
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


routes = [
    Route("/seating/forslag", seating_suggest, methods=["POST"]),
    Route("/seating/tom", seating_clear, methods=["POST"]),
    Route("/seating", seating),
    Route("/seating/assign", seating_assign, methods=["POST"]),
]
