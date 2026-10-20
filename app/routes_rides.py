"""Samåkning: gäster som har plats i bilen och gäster som behöver skjuts (anges i OSA-svaret)."""
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, csrf_form, log, render


def _norm(s) -> str:
    return " ".join(str(s or "").casefold().split())


def ride_state(c) -> tuple[list[dict], list[dict]]:
    """(förare med passagerare och lediga platser, de som behöver skjuts)."""
    rows = [dict(g) for g in c.execute(
        "SELECT id, name, attending, ride, ride_seats, ride_from, ride_with_id FROM guests "
        "WHERE rsvp = 'yes' AND ride IN ('har', 'behover') ORDER BY name COLLATE NOCASE")]
    drivers = [g for g in rows if g["ride"] == "har"]
    by_id = {d["id"]: d for d in drivers}
    for d in drivers:
        d["passengers"] = []
    needers = [g for g in rows if g["ride"] == "behover"]
    for g in needers:
        g["need"] = max(g["attending"] or 1, 1)
        if g["ride_with_id"] in by_id:
            by_id[g["ride_with_id"]]["passengers"].append(g)
    for d in drivers:
        d["free"] = (d["ride_seats"] or 0) - sum(p["need"] for p in d["passengers"])
    return drivers, needers


def suggest(drivers: list[dict], needers: list[dict]) -> list[tuple[int, int]]:
    """Föreslår förare åt dem som saknar: samma ort först, sedan den bil där sällskapet precis får plats.
    Ingen bil fylls över antalet lediga platser."""
    free = {d["id"]: d["free"] for d in drivers}
    town = {d["id"]: _norm(d["ride_from"]) for d in drivers}
    plan = []
    for g in sorted((g for g in needers if g["ride_with_id"] not in free), key=lambda g: -g["need"]):
        fits = [d for d in free if free[d] >= g["need"]]
        if not fits:
            continue
        best = min(fits, key=lambda d: (not _norm(g["ride_from"]) or town[d] != _norm(g["ride_from"]), free[d]))
        free[best] -= g["need"]
        plan.append((g["id"], best))
    return plan


async def rides(request: Request):
    user = auth(request)
    with dbm.db() as c:
        drivers, needers = ride_state(c)
    names = {d["id"]: d["name"] for d in drivers}
    proposal = [(g, names[d]) for gid, d in suggest(drivers, needers) for g in needers if g["id"] == gid]
    return render(request, "rides.html", user, drivers=drivers, needers=needers, proposal=proposal,
                  can_write=not user["readonly"], active="guests")


async def rides_apply(request: Request):
    user = auth(request, write=True, area="guests")
    await csrf_form(request, user)
    with dbm.db() as c:
        plan = suggest(*ride_state(c))
        c.executemany("UPDATE guests SET ride_with_id = ? WHERE id = ?", [(d, g) for g, d in plan])
    log.info("rides_suggested n=%s by=%s", len(plan), user["username"])
    return RedirectResponse("/samakning", 303)


async def rides_set(request: Request):
    """Koppla (eller koppla loss) ett sällskap till en förare för hand."""
    user = auth(request, write=True, area="guests")
    form = await csrf_form(request, user)
    try:
        gid = int(form.get("guest", ""))
        driver = int(form["driver"]) if form.get("driver") else None
    except ValueError:
        raise HTTPException(400)
    with dbm.db() as c:
        drivers, needers = ride_state(c)
        if gid not in {g["id"] for g in needers} or (driver is not None and driver not in {d["id"] for d in drivers}):
            raise HTTPException(404)
        c.execute("UPDATE guests SET ride_with_id = ? WHERE id = ?", (driver, gid))
    return RedirectResponse("/samakning", 303)


routes = [
    Route("/samakning", rides),
    Route("/samakning/forslag", rides_apply, methods=["POST"]),
    Route("/samakning/koppla", rides_set, methods=["POST"]),
]
