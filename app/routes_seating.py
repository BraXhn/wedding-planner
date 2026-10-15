import json

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_header, log, render


def seat_need(g) -> int:
    """Platser ett hushåll tar: antal som kommer om de svarat ja, annars antal inbjudna."""
    return (g["attending"] or 0) if g["rsvp"] == "yes" else (g["invited_count"] or 1)


async def seating(request: Request):
    user = auth(request)
    with dbm.db() as c:
        tables = [dict(t) for t in c.execute("SELECT * FROM tables ORDER BY sort_no, name COLLATE NOCASE")]
        guests = [dict(g) for g in c.execute(
            "SELECT id, name, rsvp, attending, invited_count, table_id, diet, group_name FROM guests "
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
    return render(request, "seating.html", user, tables=tables, unseated=unseated, total_seats=total_seats,
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


routes = [
    Route("/seating", seating),
    Route("/seating/assign", seating_assign, methods=["POST"]),
]
