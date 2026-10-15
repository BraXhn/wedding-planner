#!/usr/bin/env bash
# Installerar Python-beroendena i Claude Code-sessioner i molnet, så att tests/run.sh fungerar direkt.
# Lokalt görs ingenting – där hanterar du din egen miljö (t.ex. en venv).
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
python3 -c "import starlette, uvicorn, jinja2, multipart, PIL" 2>/dev/null && exit 0
pip install -q -r requirements.txt 2>/dev/null \
  || pip install -q --break-system-packages -r requirements.txt \
  || echo "Kunde inte installera beroenden – kör: pip install -r requirements.txt" >&2
exit 0
