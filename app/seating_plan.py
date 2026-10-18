"""Förslag på bordsplacering för hushåll som saknar bord.

Regler, i den här ordningen:
1. En grupp (t.ex. ”Kollegor”) placeras helst tillsammans vid ett bord – helst ett där gruppen redan sitter,
   annars det bord där gruppen precis får plats (minst spill).
2. Får gruppen inte plats någonstans placeras hushållen var för sig, helst nära sin grupp.
3. Ett hushåll hamnar aldrig vid samma bord som det hushåll det ”inte ska sitta med” (gäller åt båda håll).
4. Bord fylls aldrig över antal platser. Den som inte får plats står kvar utan bord.
Redan placerade hushåll flyttas inte."""
from .routes_seating import seat_need


def suggest(c) -> tuple[list[tuple[int, int]], list[int]]:
    """Returnerar (placeringar [(gäst, bord)], hushåll som inte fick plats). Ändrar inget i databasen."""
    tables = [dict(t) for t in c.execute("SELECT id, seats FROM tables ORDER BY sort_no, name COLLATE NOCASE")]
    guests = [dict(g) for g in c.execute(
        "SELECT id, rsvp, attending, invited_count, table_id, COALESCE(group_name,'') AS grp, avoid_guest_id "
        "FROM guests WHERE rsvp <> 'no'")]
    avoid = {}
    for g in guests:
        if g["avoid_guest_id"]:
            avoid.setdefault(g["id"], set()).add(g["avoid_guest_id"])
            avoid.setdefault(g["avoid_guest_id"], set()).add(g["id"])
    at = {t["id"]: [] for t in tables}  # bord → gäst-id
    free = {t["id"]: t["seats"] or 0 for t in tables}
    groups_at = {t["id"]: set() for t in tables}
    for g in guests:
        g["need"] = seat_need(g)
        if g["table_id"] in at:
            at[g["table_id"]].append(g["id"])
            free[g["table_id"]] -= g["need"]
            groups_at[g["table_id"]].add(g["grp"])

    def ok_at(table_id: int, members: list[dict]) -> bool:
        ids = {m["id"] for m in members}
        return (free[table_id] >= sum(m["need"] for m in members)
                and not any(avoid.get(m["id"], set()) & (set(at[table_id]) | ids) for m in members))

    def best(members: list[dict], grp: str):
        fits = [t for t in at if ok_at(t, members)]
        # samma grupp vid bordet först, sedan minst spill
        return min(fits, key=lambda t: (grp not in groups_at[t] if grp else 0, free[t]), default=None)

    def place(members: list[dict], table_id: int) -> None:
        for m in members:
            at[table_id].append(m["id"])
            free[table_id] -= m["need"]
            groups_at[table_id].add(m["grp"])
            plan.append((m["id"], table_id))

    plan, left = [], []
    unseated = [g for g in guests if g["table_id"] not in at]
    groups = {}
    for g in unseated:
        groups.setdefault(g["grp"], []).append(g)
    order = sorted(groups.items(), key=lambda kv: (kv[0] == "", -sum(m["need"] for m in kv[1])))
    for grp, members in order:
        members.sort(key=lambda m: -m["need"])
        t = best(members, grp) if grp else None
        if t is not None:
            place(members, t)
            continue
        for m in members:
            t = best([m], grp)
            if t is None:
                left.append(m["id"])
            else:
                place([m], t)
    return plan, left
