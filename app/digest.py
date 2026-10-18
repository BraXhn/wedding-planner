"""Veckobrevet till brudparet: nya OSA-svar, vilka som inte svarat, uppgifter och räkningar som närmar sig."""
import datetime as dt

from . import db as dbm
from .core import get_settings, kr, parse_date, sv_date, today


def build_digest(base_url: str) -> tuple[str, str]:
    s = get_settings()
    td = today()
    wd = parse_date(s.get("wedding_date"))
    week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    with dbm.db() as c:
        g = c.execute("SELECT COALESCE(SUM(CASE WHEN rsvp='yes' THEN attending END),0) AS coming, "
                      "COALESCE(SUM(rsvp='pending'),0) AS pending_households, COALESCE(SUM(rsvp='no'),0) AS declined "
                      "FROM guests").fetchone()
        new = c.execute("SELECT name, rsvp, attending FROM guests WHERE rsvp <> 'pending' AND rsvp_at >= ? "
                        "ORDER BY rsvp_at", (week_ago,)).fetchall()
        tasks = c.execute("SELECT title, due_date FROM tasks WHERE done = 0 AND COALESCE(due_date,'') <> '' AND due_date <= ? "
                          "ORDER BY due_date", ((td + dt.timedelta(days=14)).isoformat(),)).fetchall()
        bills = c.execute("SELECT item, due_date, COALESCE(actual, estimated) AS amount FROM budget WHERE paid = 0 "
                          "AND COALESCE(due_date,'') <> '' AND due_date <= ? ORDER BY due_date",
                          ((td + dt.timedelta(days=30)).isoformat(),)).fetchall()
        photos = c.execute("SELECT COUNT(*) FROM photos WHERE created_at >= ?", (week_ago,)).fetchone()[0]
    days = (wd - td).days if wd else None
    lines = []
    if days is not None and days >= 0:
        lines.append(f"{days} dagar kvar till bröllopet ({sv_date(wd)}).\n")
    lines.append(f"OSA: {g['coming']} personer kommer, {g['pending_households']} hushåll har inte svarat, "
                 f"{g['declined']} har tackat nej.")
    if new:
        lines.append("\nNya svar den senaste veckan:")
        lines += [f"- {n['name']}: " + (f"kommer ({n['attending']})" if n["rsvp"] == "yes" else "kommer inte") for n in new]
    if tasks:
        lines.append("\nAtt göra de närmaste två veckorna:")
        lines += [f"- {t['title']} ({'FÖRSENAD, ' if t['due_date'] < td.isoformat() else ''}{sv_date(t['due_date'], short=True)})"
                  for t in tasks]
    if bills:
        lines.append("\nRäkningar att betala:")
        lines += [f"- {b['item']}: {kr(b['amount'])} senast {sv_date(b['due_date'], short=True)}"
                  + (" (försenad)" if b["due_date"] < td.isoformat() else "") for b in bills]
    if photos:
        lines.append(f"\n{photos} nya bilder från gästerna.")
    if base_url:
        lines.append(f"\nÖppna planeraren: {base_url}/")
    lines.append("\nVeckobrevet kommer varje måndag. Stäng av det under Inställningar → Aviseringar.")
    subject = f"Veckobrev: {days} dagar kvar" if days is not None and days >= 0 else "Veckobrev från bröllopsplaneraren"
    return subject, "\n".join(lines)


def digest_due(now: dt.datetime) -> str | None:
    """ISO-vecka att skicka för, om det är måndag efter 07 och veckans brev inte skickats; annars None."""
    s = get_settings()
    if s.get("digest_enabled") != "1" or now.weekday() != 0 or now.hour < 7:
        return None
    week = "%d-%02d" % now.isocalendar()[:2]
    return None if s.get("digest_week") == week else week
