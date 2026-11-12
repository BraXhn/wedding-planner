"""Quiz om brudparet (gästerna svarar i mobilen via QR-koden på borden eller sin egen länk, ställningen visas
på storbildsskärmen) och minnesboken (hälsningar, låtönskemål och utvalda bilder att skriva ut efteråt)."""
import json

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import db as dbm
from .core import auth, can_write, client_ip, csrf_form, flag, get_settings, log, parse_date, read_form, render, set_settings
from .security import RateLimiter

QUIZ_IP = RateLimiter(20, 10 * 60)  # inskickade svar per IP
NAME_MAX = 40


def quiz_questions(c) -> list[dict]:
    """Frågor som är med: minst två alternativ och ett rätt svar som finns."""
    out = []
    for q in c.execute("SELECT * FROM quiz WHERE enabled = 1 ORDER BY sort_no, id"):
        options = [o.strip() for o in (q["options"] or "").splitlines() if o.strip()][:6]
        if len(options) >= 2 and 1 <= (q["correct"] or 0) <= len(options):
            out.append({"id": q["id"], "question": q["question"], "options": options, "correct": q["correct"]})
    return out


def leaderboard(c, limit: int = 15) -> list[dict]:
    """Bästa resultat per namn; vid lika vinner den som var först."""
    best = {}
    for e in c.execute("SELECT id, name, score, total FROM quiz_entries ORDER BY score DESC, id"):
        best.setdefault(" ".join(e["name"].casefold().split()), dict(e))
    return list(best.values())[:limit]


# ======================================================================= gästerna svarar
async def _play(request: Request, base: str, default_name: str = ""):
    s = get_settings()
    with dbm.db() as c:
        questions = quiz_questions(c)
    is_open = flag(s, "quiz_open") and bool(questions)
    ctx = dict(settings=s, guest=None, base=base, questions=questions, is_open=is_open, player=default_name, picked={},
               wedding_date=parse_date(s.get("wedding_date")), name_max=NAME_MAX, result=None, error=None)
    if request.method == "GET" or not is_open:
        return render(request, "quiz_play.html", status=200 if request.method == "GET" else 403, **ctx)
    if not QUIZ_IP.hit(client_ip(request)):
        return render(request, "quiz_play.html", status=429, **{**ctx, "error": "För många svar på kort tid – vänta en stund."})
    form = await read_form(request)
    name = " ".join("".join(ch for ch in str(form.get("name", "")) if ch.isprintable()).split())[:NAME_MAX]
    picked = {}
    for q in questions:
        raw = str(form.get(f"q_{q['id']}", ""))
        if raw.isdigit() and 1 <= int(raw) <= len(q["options"]):
            picked[q["id"]] = int(raw)
    ctx.update(player=name, picked=picked)
    if not name:
        return render(request, "quiz_play.html", status=400, **{**ctx, "error": "Skriv ert namn eller lagnamn."})
    if len(picked) < len(questions):
        return render(request, "quiz_play.html", status=400, **{**ctx, "error": "Svara på alla frågor."})
    score = sum(picked[q["id"]] == q["correct"] for q in questions)
    with dbm.db() as c:
        c.execute("INSERT INTO quiz_entries (name, score, total, answers) VALUES (?, ?, ?, ?)",
                  (name, score, len(questions), json.dumps(picked)))
    log.info("quiz_entry score=%s/%s", score, len(questions))
    return render(request, "quiz_play.html", **{**ctx, "result": {"score": score, "total": len(questions)}})


async def play_table(request: Request):
    from .routes_photos import _check_photo_token
    _check_photo_token(request)
    return await _play(request, f"/p/{request.path_params['token']}")


async def play_guest(request: Request):
    from .routes_public import guest_by_token
    g = guest_by_token(request)
    return await _play(request, f"/r/{g['rsvp_token']}", g["name"])


# ======================================================================= toastmastern
async def quiz_admin(request: Request):
    user = auth(request)
    with dbm.db() as c:
        questions = quiz_questions(c)
        total = c.execute("SELECT COUNT(*) FROM quiz").fetchone()[0]
        entries = c.execute("SELECT COUNT(*) FROM quiz_entries").fetchone()[0]
        board = leaderboard(c)
    return render(request, "quiz_admin.html", user, questions=questions, skipped=total - len(questions), entries=entries,
                  board=board, is_open=flag(get_settings(), "quiz_open"), can_edit=can_write(user, "quiz"), active="day")


async def quiz_action(request: Request):
    user = auth(request, write=True, area="quiz")
    form = await csrf_form(request, user)
    action = form.get("action")
    if action in ("open", "close"):
        set_settings({"quiz_open": "1" if action == "open" else "0"})
    elif action == "reset":
        with dbm.db() as c:
            c.execute("DELETE FROM quiz_entries")
    else:
        raise HTTPException(400)
    log.info("quiz_%s by=%s", action, user["username"])
    return RedirectResponse("/quiz", 303)


async def quiz_board(request: Request):
    """Ställningen på storbildsskärmen. ?facit=1 visar de rätta svaren (när quizet är stängt)."""
    user = auth(request)
    s = get_settings()
    with dbm.db() as c:
        board = leaderboard(c)
        questions = quiz_questions(c)
        entries = c.execute("SELECT COUNT(*) FROM quiz_entries").fetchone()[0]
    show_key = request.query_params.get("facit") == "1" and not flag(s, "quiz_open")
    return render(request, "quiz_board.html", user, public_page=True, board=board, entries=entries, is_open=flag(s, "quiz_open"),
                  questions=questions if show_key else [], show_key=show_key)


# ======================================================================= minnesbok
async def memory_book(request: Request):
    user = auth(request)
    from .routes_photos import visible_greetings
    from .routes_reports import song_list
    with dbm.db() as c:
        messages = c.execute("SELECT name, message FROM guests WHERE TRIM(COALESCE(message,'')) <> '' "
                             "ORDER BY name COLLATE NOCASE").fetchall()
        songs = song_list(c)
        photos = c.execute("SELECT file, uploader FROM photos WHERE hidden = 0 AND favorite = 1 ORDER BY id").fetchall()
        fallback = not photos
        if fallback:
            photos = c.execute("SELECT file, uploader FROM photos WHERE hidden = 0 ORDER BY id LIMIT 24").fetchall()
        coming = c.execute("SELECT COALESCE(SUM(attending), 0) FROM guests WHERE rsvp = 'yes'").fetchone()[0]
        board = leaderboard(c, 3)
    s = get_settings()
    return render(request, "memory_book.html", user, messages=messages, greetings=list(reversed(visible_greetings())), songs=songs,
                  photos=photos, fallback=fallback, coming=coming, board=board, wedding_date=parse_date(s.get("wedding_date")),
                  active="photos")


routes = [
    Route("/p/{token}/quiz", play_table, methods=["GET", "POST"]),
    Route("/r/{token}/quiz", play_guest, methods=["GET", "POST"]),
    Route("/quiz", quiz_admin),
    Route("/quiz", quiz_action, methods=["POST"]),
    Route("/quiz/stallning", quiz_board),
    Route("/minnesbok", memory_book),
]
