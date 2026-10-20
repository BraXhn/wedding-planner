"""Tackkort: vilken present varje hushåll gav och om tackkortet är skickat."""
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, log, render
from .routes_crud import get_item


async def thanks_view(request: Request):
    user = auth(request)
    with dbm.db() as c:
        rows = c.execute(
            "SELECT id, name, street, postcode, city, email, gift_received, thanks_sent, rsvp FROM guests "
            "WHERE rsvp = 'yes' OR COALESCE(gift_received,'') <> '' OR thanks_sent = 1 "
            "ORDER BY thanks_sent, name COLLATE NOCASE").fetchall()
    flt = request.query_params.get("f", "")
    shown = [r for r in rows if not (flt == "kvar" and r["thanks_sent"])]
    return render(request, "thanks.html", user, rows=shown, total=len(rows), sent=sum(1 for r in rows if r["thanks_sent"]),
                  flt=flt, can_write=not user["readonly"], active="guests")


async def thanks_save(request: Request):
    user = auth(request, write=True)
    form = await csrf_form(request, user)
    item_id = request.path_params["item_id"]
    gift = " ".join(str(form.get("gift_received", "")).split())[:200]
    with dbm.db() as c:
        get_item(c, "guests", item_id)
        c.execute("UPDATE guests SET gift_received = ?, thanks_sent = ? WHERE id = ?",
                  (gift, 1 if form.get("thanks_sent") == "on" else 0, item_id))
    log.info("thanks guest=%s by=%s", item_id, user["username"])
    nxt = "/tack?f=kvar" if form.get("f") == "kvar" else "/tack"
    return RedirectResponse(f"{nxt}#g{item_id}", 303)


routes = [
    Route("/tack", thanks_view),
    Route("/tack/{item_id:id}", thanks_save, methods=["POST"]),
]
