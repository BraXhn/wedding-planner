"""Rapporter som skrivs ut: maten till cateringen, bordskort och placeringslista med namn."""
import csv
import io
import re
from collections import Counter

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import db as dbm
from .core import auth, log, render, today
from .people import coming_people
from .routes_crud import csv_cell


def _by_table(people: list[dict]) -> list[dict]:
    """Grupperar personer per bord i bordsordning; personer utan bord sist."""
    with dbm.db() as c:
        tables = c.execute("SELECT id, name FROM tables ORDER BY sort_no, name COLLATE NOCASE").fetchall()
    groups = {t["id"]: {"name": t["name"], "people": []} for t in tables}
    unseated = {"name": "Utan bord", "people": []}
    for p in people:
        groups.get(p["table_id"], unseated)["people"].append(p)
    out = [g for g in groups.values() if g["people"]]
    if unseated["people"]:
        out.append(unseated)
    return out


def allergy_summary(people: list[dict]) -> list[tuple[str, int]]:
    """"Nötter, laktos" och "nötter" → nötter 2, laktos 1. Mest förekommande först."""
    counts = Counter()
    for p in people:
        for part in re.split(r"[,;/]| och ", p["allergies"].lower()):
            part = part.strip(" .")
            if part:
                counts[part] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


async def food_report(request: Request):
    user = auth(request)
    with dbm.db() as c:
        people = coming_people(c)
        households = c.execute("SELECT name, diet FROM guests WHERE rsvp = 'yes' AND COALESCE(diet,'') <> '' "
                               "ORDER BY name COLLATE NOCASE").fetchall()
        pending = c.execute("SELECT COALESCE(SUM(invited_count),0) FROM guests WHERE rsvp = 'pending'").fetchone()[0]
    with_allergy = [p for p in people if p["allergies"]]
    return render(request, "report_food.html", user, groups=_by_table(people), total=len(people),
                  with_allergy=with_allergy, summary=allergy_summary(with_allergy), households=households,
                  pending=pending, today=today(), active="guests")


async def food_csv(request: Request):
    user = auth(request)
    with dbm.db() as c:
        people = coming_people(c)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Bord", "Namn", "Hushåll", "Allergier/specialkost", "Övrigt om maten (hushåll)"])
    for g in _by_table(people):
        for p in g["people"]:
            w.writerow([csv_cell(g["name"]), csv_cell(p["name"] if p["named"] else ""), csv_cell(p["household"]),
                        csv_cell(p["allergies"]), csv_cell(p["household_diet"])])
    log.info("export food by=%s", user["username"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="mat-{today().isoformat()}.csv"'})


async def place_cards(request: Request):
    """Ett bordskort per person som kommer och har ett bord."""
    user = auth(request)
    with dbm.db() as c:
        people = [p for p in coming_people(c) if p["table_id"]]
    people.sort(key=lambda p: (p["table_sort"] or 0, p["table_name"].lower(), p["name"].lower()))
    unnamed = sum(not p["named"] for p in people)
    return render(request, "place_cards.html", user, people=people, unnamed=unnamed, active="seating")


async def seating_list(request: Request):
    """Alfabetisk lista namn → bord, att sätta upp vid entrén."""
    user = auth(request)
    with dbm.db() as c:
        people = coming_people(c)
    rows, seen = [], {}
    for p in people:  # hushåll utan namngivna personer visas en gång med antal
        if p["named"]:
            rows.append({**p, "count": 1})
        elif p["guest_id"] in seen:
            seen[p["guest_id"]]["count"] += 1
        else:
            seen[p["guest_id"]] = {**p, "count": 1}
            rows.append(seen[p["guest_id"]])
    rows.sort(key=lambda p: p["name"].lower())
    return render(request, "seating_list.html", user, people=rows, active="seating")


routes = [
    Route("/rapport/mat", food_report),
    Route("/rapport/mat.csv", food_csv),
    Route("/seating/kort", place_cards),
    Route("/seating/lista", seating_list),
]
