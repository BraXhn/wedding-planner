"""Egna frågor i OSA-formuläret (skjuts, boende, barnstol …). Varje fråga kan stängas av; svaren sparas per hushåll."""
TEXT_MAX = 300


def options_of(q) -> list[str]:
    return [o.strip() for o in (q["options"] or "").splitlines() if o.strip()]


def enabled_questions(c) -> list[dict]:
    return [{**dict(q), "choices": options_of(q)}
            for q in c.execute("SELECT * FROM questions WHERE enabled = 1 ORDER BY sort_no, id")]


def answers_for(c, guest_id: int) -> dict[int, str]:
    return {r["question_id"]: r["value"] for r in c.execute("SELECT question_id, value FROM answers WHERE guest_id = ?", (guest_id,))}


def parse_answers(form, questions: list[dict]) -> tuple[dict[int, str], list[str]]:
    vals, errors = {}, []
    for q in questions:
        v = " ".join(str(form.get(f"q_{q['id']}", "")).split())
        if q["kind"] == "yesno" and v not in ("", "ja", "nej"):
            errors.append(f"Ogiltigt svar på ”{q['label']}”.")
        elif q["kind"] == "choice" and v and v not in q["choices"]:
            errors.append(f"Ogiltigt val för ”{q['label']}”.")
        vals[q["id"]] = v[:TEXT_MAX]
    return vals, errors


def save_answers(c, guest_id: int, vals: dict[int, str]) -> None:
    for qid, v in vals.items():
        if v:
            c.execute("INSERT INTO answers (guest_id, question_id, value) VALUES (?,?,?) "
                      "ON CONFLICT(guest_id, question_id) DO UPDATE SET value = excluded.value", (guest_id, qid, v))
        else:
            c.execute("DELETE FROM answers WHERE guest_id = ? AND question_id = ?", (guest_id, qid))
