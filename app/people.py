"""Personer i ett hushåll: namn, om personen kommer och allergier/specialkost.

Varje hushåll har lika många platser som "Antal inbjudna". Raderna sparas i guest_people med
position 1..n; platser utan sparad rad visas som tomma. När antalet inbjudna minskar tas
överskjutande rader bort. Hushållets "Antal som kommer" räknas fram från personerna när
personuppgifter skickas in."""

NAME_MAX = 80
ALLERGY_MAX = 200


def people_for(c, guest) -> list[dict]:
    """En rad per inbjuden plats (pos 1..invited_count), även för platser som inte fyllts i."""
    n = max(1, guest["invited_count"] or 1)
    stored = {r["pos"]: dict(r) for r in c.execute(
        "SELECT pos, name, attending, allergies FROM guest_people WHERE guest_id = ? AND pos <= ?", (guest["id"], n))}
    out = []
    for pos in range(1, n + 1):
        p = stored.get(pos) or {"pos": pos, "name": "", "attending": 1, "allergies": ""}
        p["name"], p["allergies"] = p["name"] or "", p["allergies"] or ""
        out.append(p)
    return out


def parse_people(form, n: int) -> tuple[list[dict], list[str]]:
    """Läser name_i / coming_i / allergy_i ur ett formulär. Den som kommer måste ha ett namn."""
    people, errors = [], []
    for pos in range(1, n + 1):
        name = " ".join(str(form.get(f"name_{pos}", "")).split())[:NAME_MAX]
        allergies = " ".join(str(form.get(f"allergy_{pos}", "")).split())[:ALLERGY_MAX]
        coming = form.get(f"coming_{pos}") == "on"
        if coming and not name:
            errors.append(f"Skriv namnet på person {pos} som kommer.")
        people.append({"pos": pos, "name": name, "attending": 1 if coming else 0, "allergies": allergies})
    return people, errors


def save_people(c, guest_id: int, people: list[dict]) -> None:
    c.execute("DELETE FROM guest_people WHERE guest_id = ? AND pos > ?", (guest_id, len(people)))
    c.executemany(
        "INSERT INTO guest_people (guest_id, pos, name, attending, allergies) VALUES (?,?,?,?,?) "
        "ON CONFLICT(guest_id, pos) DO UPDATE SET name = excluded.name, attending = excluded.attending, "
        "allergies = excluded.allergies",
        [(guest_id, p["pos"], p["name"], p["attending"], p["allergies"]) for p in people])


def trim_people(c, guest_id: int, invited_count: int) -> None:
    """Tar bort personer på platser som inte längre finns (antal inbjudna har minskat)."""
    c.execute("DELETE FROM guest_people WHERE guest_id = ? AND pos > ?", (guest_id, invited_count or 1))


def coming_people(c) -> list[dict]:
    """Alla som kommer, en rad per person, med hushåll och bord. Hushåll som svarat ja men inte
    namngett alla som kommer fylls ut med hushållets namn så att antalet stämmer."""
    rows = c.execute(
        """SELECT g.id AS guest_id, g.name AS household, g.attending, g.diet, g.table_id, t.name AS table_name,
                  t.sort_no AS table_sort
           FROM guests g LEFT JOIN tables t ON t.id = g.table_id
           WHERE g.rsvp = 'yes' ORDER BY g.name COLLATE NOCASE""").fetchall()
    named = {}
    for p in c.execute("SELECT guest_id, pos, name, allergies FROM guest_people "
                       "WHERE attending = 1 AND COALESCE(name,'') <> '' ORDER BY guest_id, pos"):
        named.setdefault(p["guest_id"], []).append(p)
    out = []
    for g in rows:
        persons = named.get(g["guest_id"], [])[: g["attending"] or 0]
        base = {"guest_id": g["guest_id"], "household": g["household"], "table_id": g["table_id"],
                "table_name": g["table_name"] or "", "table_sort": g["table_sort"], "household_diet": g["diet"] or ""}
        for p in persons:
            out.append({**base, "name": p["name"], "allergies": p["allergies"] or "", "named": True})
        for _ in range((g["attending"] or 0) - len(persons)):
            out.append({**base, "name": g["household"], "allergies": "", "named": False})
    return out
