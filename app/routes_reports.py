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
from .questions import options_of
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


def _answer_rows(c):
    questions = [{**dict(q), "choices": options_of(q)} for q in c.execute("SELECT * FROM questions ORDER BY sort_no, id")]
    rows = c.execute("SELECT a.question_id, a.value, g.name, g.attending FROM answers a JOIN guests g ON g.id = a.guest_id "
                     "WHERE g.rsvp = 'yes' ORDER BY g.name COLLATE NOCASE").fetchall()
    for q in questions:
        mine = [r for r in rows if r["question_id"] == q["id"]]
        q["answers"] = mine
        if q["kind"] in ("yesno", "choice"):
            keys = ["ja", "nej"] if q["kind"] == "yesno" else q["choices"]
            keys += sorted({r["value"] for r in mine} - set(keys))  # alternativ som tagits bort efter att någon svarat
            q["tally"] = [{"value": k, "households": [r for r in mine if r["value"] == k],
                           "people": sum((r["attending"] or 0) for r in mine if r["value"] == k)} for k in keys]
    return questions


async def answers_report(request: Request):
    user = auth(request)
    with dbm.db() as c:
        questions = _answer_rows(c)
        coming = c.execute("SELECT COUNT(*) FROM guests WHERE rsvp = 'yes'").fetchone()[0]
    return render(request, "report_answers.html", user, questions=questions, coming=coming,
                  can_write=user["role"] != "viewer", active="guests")


async def answers_csv(request: Request):
    user = auth(request)
    with dbm.db() as c:
        questions = c.execute("SELECT id, label FROM questions ORDER BY sort_no, id").fetchall()
        guests = c.execute("SELECT id, name, attending FROM guests WHERE rsvp = 'yes' ORDER BY name COLLATE NOCASE").fetchall()
        ans = {(r["guest_id"], r["question_id"]): r["value"] for r in c.execute("SELECT * FROM answers")}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Hushåll", "Antal som kommer"] + [q["label"] for q in questions])
    for g in guests:
        w.writerow([csv_cell(g["name"]), g["attending"]] + [csv_cell(ans.get((g["id"], q["id"]), "")) for q in questions])
    log.info("export answers by=%s", user["username"])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="osa-svar-{today().isoformat()}.csv"'})


def song_list(c) -> list[dict]:
    """Låtönskemål från dem som kommer, ihopslagna oberoende av stora/små bokstäver och skiljetecken."""
    groups = {}
    for g in c.execute("SELECT name, song FROM guests WHERE rsvp = 'yes' AND TRIM(COALESCE(song,'')) <> '' "
                       "ORDER BY rsvp_at, id"):
        key = re.sub(r"[\W_]+", " ", g["song"].casefold()).strip()
        item = groups.setdefault(key, {"song": g["song"].strip(), "by": []})
        item["by"].append(g["name"])
    return sorted(groups.values(), key=lambda s: (-len(s["by"]), s["song"].casefold()))


async def songs_report(request: Request):
    user = auth(request)
    with dbm.db() as c:
        songs = song_list(c)
    return render(request, "report_songs.html", user, songs=songs, active="guests")


async def songs_csv(request: Request):
    user = auth(request)
    with dbm.db() as c:
        songs = song_list(c)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Låt", "Antal önskningar", "Önskad av"])
    for s in songs:
        w.writerow([csv_cell(s["song"]), len(s["by"]), csv_cell(", ".join(s["by"]))])
    log.info("export songs by=%s", user["username"])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="latonskemal-{today().isoformat()}.csv"'})


routes = [
    Route("/rapport/latar", songs_report),
    Route("/rapport/latar.csv", songs_csv),
    Route("/rapport/svar", answers_report),
    Route("/rapport/svar.csv", answers_csv),
    Route("/rapport/mat", food_report),
    Route("/rapport/mat.csv", food_csv),
    Route("/seating/kort", place_cards),
    Route("/seating/lista", seating_list),
]
