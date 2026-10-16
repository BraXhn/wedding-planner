# Bröllopsplaneraren

Självhostad bröllopsplanerare för Louise & Anton (bröllop 22 maj 2027). Körs som Docker-container på Unraid och nås från internet på `https://gift.braxhn.net` via Cloudflare Tunnel. Gränssnitt, felmeddelanden, commit-meddelanden och dokumentation skrivs på **svenska**. Funktioner och drift för slutanvändaren: `README.md`.

## Kommandon

- `bash tests/run.sh` – hela testsviten (enhetstester + end-to-end mot riktig server med test-SMTP). Grön före varje commit.
- `DATA_DIR=./data uvicorn app.main:app --reload --port 8080` – lokal körning; engångslösenord för första admin skrivs i loggen.

## Arkitektur

Starlette (inte FastAPI) + Jinja2 + SQLite. Kryptot (scrypt, TOTP, tokens) bygger på standardbiblioteket i `app/security.py`, och QR-koder genereras av egen kod i `app/qr.py`. Det är medvetet: få beroenden i en internetexponerad app. Lägg till ett beroende bara när standardbiblioteket eller befintlig kod inte räcker, versionslåst i `requirements.txt`.

- `app/entities.py` – datamodellen. Tabeller, formulär, listvyer och CSV genereras från `ENTITIES`; inställningar från `SETTINGS_FIELDS`/`SETTINGS_DEFAULTS`.
- `app/db.py` – schema och migreringar. Nya fält i `ENTITIES` läggs till som kolumner automatiskt vid start; datamigreringar skrivs i `init_db()` och måste tåla att köras vid varje start.
- `app/core.py` – sessioner, behörighet, validering (`parse_form`), mallhjälpare (`render`, `asset`, `sv_date`).
- `app/people.py` – personer i ett hushåll (`guest_people`: namn, kommer, allergier); `coming_people()` ger en rad per person som kommer och används av matrapport, bordskort och placeringslista.
- `app/cards.py` + `app/routes_cards.py` – trycksaker (tabell `cards`, förslagen i `SEED` läggs in en gång). Kortet ritas av makrot `templates/_card.html`; designerna är bara CSS (`.d-*` design, `.c-*` färg, `.p-*` papper, `.s-*` format; mått i `cqw` så att förhandsvisning och utskrift blir lika). Designens bakgrund ligger i `.pcard-bg` och skrivs bara ut på vitt papper (`.p-vit`). `app.js` krymper innehållet via `--fit` när texten inte ryms. Mallvariabeln `items` är upptagen av menyn i `base.html`.
- `app/qr.py` – egen QR-generator. `qr_svg()` ger en vanlig kod (admin, nedladdning); `qr_svg_fancy()` ritar dekorativa moduler, hörn och ett motiv i mitten med `currentColor` och felkorrigering H när motiv finns. Ändras ritningen: provläs alla stilar × motiv med en avkodare (t.ex. zxing-cpp utanför repot) innan merge.
- `app/backup.py` – daglig SQLite-kopia i `DATA_DIR/backups` (bakgrundstråd som startas i `lifespan`).
- `app/routes_*.py` – en modul per område; registreras i `app/main.py` (ordningen spelar roll där specifika sökvägar krockar med `/m/{ent}/...`).
- `app/templates/`, `app/static/app.js`, `app/static/style.css` – all JS och CSS ligger i filerna (CSP tillåter inget inline).

## Säkerhetsinvarianter

Appen ligger ute på internet; varje ändring håller dessa:

- Inloggade vyer anropar `auth(request, write=…, admin=…)`; roller: admin, editor, viewer. Läsare får aldrig se gästernas OSA-länkar, koder eller QR (de ger skrivrätt till gästens svar).
- Varje POST verifierar CSRF: `csrf_form()` för formulär, `csrf_header()` för `fetch()`-anrop med JSON.
- Publika token-sidor (`/r/`, `/p/`, `/o/`, `/osa`, `/cal/`, `/api/`) anropar `public_rate_limit()` eller en egen `RateLimiter`, validerar token/nyckel mot ett strikt mönster (`TOKEN_RE`, `KEY_RE`, `normalize_code`) och svarar 404/401 utan att avslöja om den finns.
- SQL är parametriserad; tabell- och kolumnnamn kommer bara från `ENTITIES` (vitlista).
- Mallar autoescapar; `Markup` används bara för SVG som appen själv genererat.
- Statiska filer länkas via `{{ asset('fil') }}` (innehållshash i URL:en); annars visar Cloudflare gammal CSS efter en uppdatering.
- Uppladdade bilder kodas om med Pillow (tar bort EXIF/GPS); filnamn slumpas; allt skrivs under `DATA_DIR`.
- Ny publik sökväg: lägg till den i bypass-tabellen för Cloudflare Access i `README.md`, annars når gästerna den inte.

## Tester

End-to-end i `tests/test_features.py` och `tests/test_basic.py` (HTTP mot servern, `ok(villkor, "beskrivning")`), enhetstester utan server i `tests/test_units.py`. Varje ny funktion får tester för både lyckat flöde och säkerhetsgränsen (CSRF, roll, rate limit, escaping). Testerna delar en databas och körs i ordning; rate-limit-tester ligger sist i sitt avsnitt.

## Arbetsflöde och driftsättning

1. Ny gren från `main`, ändring + tester + rad i `CHANGELOG.md`.
2. Pull request mot `main`. GitHub Actions (`.github/workflows/build.yml`) kör testerna och bygger imagen.
3. Merge till `main` publicerar `ghcr.io/braxhn/wedding-planner:latest` (amd64+arm64); Unraid visar *update ready*. Tagg `vX.Y.Z` ger versionslåsta images.

Commits görs som `BraXhn <BraXhn@users.noreply.github.com>` så att ingen privat e-post hamnar i det publika repot. Dependabot öppnar PR:er för beroenden varje vecka.

## Drift (Unraid)

Containern kör som 99:100 utan capabilities (`entrypoint.sh` släpper root efter `chown` av `/data`). Rekommenderad koppling: containern och cloudflared på samma Docker-nätverk (`proxynet`), tunneln pekar på `http://wedding-planner:8080`. Serverns LAN-IP (`192.168.1.9:8080`) gav "connection refused" inifrån cloudflared-containern. All data finns i `/mnt/user/appdata/wedding-planner` (`wedding.db` + `photos/`).
