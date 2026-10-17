# 💍 Bröllopsplaneraren

[![Testa och publicera](https://github.com/BraXhn/wedding-planner/actions/workflows/build.yml/badge.svg)](https://github.com/BraXhn/wedding-planner/actions/workflows/build.yml) ![Image](https://img.shields.io/badge/ghcr.io-braxhn%2Fwedding--planner-2f4a3e) ![Plattformar](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-b08d57)

En självhostad bröllopsplanerare för Unraid. Den är liten (fem Python-beroenden och SQLite), fungerar bra i mobilen och är byggd för att kunna ligga ute på internet.

## Funktioner

### För er
| Del | Vad den gör |
|---|---|
| **Översikt** | Nedräkning, OSA-status, budget, försenade uppgifter, obetalda räkningar, tal, önskelista och bilder |
| **Gäster** | Ett hushåll per rad: antal, grupp/sida, bord, e-post, postadress och låtönskemål. Under **Personer** står namn, om personen kommer och allergier per person. |
| **Till cateringen** | Antal som kommer, allergier per person och per bord och en sammanställning (t.ex. ”2 × nötter”). Kan skrivas ut eller exporteras som CSV. |
| **Placering** | Bord med antal platser. Dra hushåll till ett bord, eller tryck på hushållet och sedan på bordet i mobilen. Fulla bord markeras i rött och det finns en utskriftsvy. **Bordskort** med namn (ett per person, 8 per A4) och en **placeringslista** i bokstavsordning till entrén. |
| **Att göra** | Förifylld svensk checklista med 38 punkter. **Deadlines räknas ut automatiskt** från bröllopsdatumet, till exempel hindersprövning en månad före. Ändras datumet flyttas de uträknade deadlines med; egna datum rörs inte. |
| **Budget** | Budgeterat mot faktiskt, betalt, förfallodatum och summering |
| **Leverantörer** | Status från förfrågan till bokad, kontaktuppgifter och pris. En bokad leverantör läggs in i budgeten med priset som budgeterat belopp. |
| **Körschema** | Dagen minut för minut. Punkter markerade *Visa för gäster* syns i gästportalen. Tider före 06:00 räknas som natten efter. |
| **Dagen** | För toastmaster och brudpar i mobilen på bröllopsdagen: vad som händer nu och härnäst, hela körschemat och talen per del av middagen. |
| **Tal** | Talarlista för toastmaster. Gäster som anmäler tal i OSA-formuläret hamnar här automatiskt. Visar total talartid. |
| **Önskelista** | Gästerna reserverar presenter. Ni ser hur många som är reserverade, men inte av vem. |
| **Bilder** | Gästernas bilder i ett galleri, med valfri granskning innan de visas, nedladdning som zip, utskrivbara **bordskort med QR-kod** och ett **bildspel** för projektor som visar nya bilder direkt |
| **OSA-kort med QR** | För inbjudningar som skickas med posten: en QR-kod och en kort kod per hushåll, utskriftsark (8 kort per A4) och zip med PNG/SVG + CSV för dokumentkoppling i Word, InDesign eller Canva |
| **Utskick** | E-post med personlig länk till varje hushåll, påminnelser till dem som inte svarat, redigerbara mallar och testutskick. Ni kan också få ett mejl varje gång någon svarar på OSA (Inställningar → Aviseringar). |
| **Trycksaker** | Färdiga förslag på save the date, inbjudan, tackkort, meny, program och välkomstskylt. Ändra text, design (elva stycken, från klassisk och botanisk till monogram, art déco, krans och båge), färg och format (A6, A5, A4) med förhandsvisning direkt. Skriver ni ut på **färgat papper** väljer ni papperets färg – då skrivs ingen bakgrund ut, och förhandsvisningen visar hur det blir. Lång text krymps automatiskt så att den får plats. **QR-koden** kan vara prickar, rundade rutor, små hjärtan eller romber, med ett hjärta, två ringar, era initialer eller en kamera i mitten, i kortets färg eller svart. Platshållare som `{namn}`, `{datum}` och `{kod}` fylls i. Inbjudan och tackkort skrivs ut ett per hushåll med namn och egen OSA-QR. |
| **Tackkort** | Efter bröllopet: vilken present varje hushåll gav, adress för kuvertet och avbockning när tackkortet är skickat |
| **Kalender** | Personlig prenumerationslänk (.ics) med bröllopet, körschemat, deadlines och räkningar |
| **API** | Nedräkningen (och valfri statistik) som JSON för t.ex. **Hemmahub** |
| **Roller** | Administratör, Redigerare och Läsare. Läsare passar t.ex. toastmaster – de ser allt men inte gästernas OSA-länkar och koder. |
| **Backup** | En kopia av databasen varje dygn (de senaste 14 sparas) och nedladdning för administratörer |
| **CSV-export** | Alla listor kan exporteras till Excel |

### För gästerna (personlig länk, inget konto)
- **OSA**: kommer eller inte, namn och allergier för var och en som kommer, talanmälan, låtönskemål och hälsning. Svaret kan ändras fram till OSA-deadline.
- **Information**: när och var, program, hitta hit, boende och knappen *Lägg till i kalendern*.
- **Önskelista** med reservation, och en **Swish-QR** för penninggåvor om ni angett ett Swish-nummer.
- **Bilder**: uppladdning och galleri, om ni har slagit på det.

## Installation på Unraid

**1. Hämta mallen** – kör i Unraids terminal (ikonen `>_` uppe till höger):
```bash
wget -O /boot/config/plugins/dockerMan/templates-user/my-wedding-planner.xml \
  https://raw.githubusercontent.com/BraXhn/wedding-planner/main/unraid/wedding-planner.xml
```

**2. Skapa containern** – gå till *Docker → Add Container*, välj **wedding-planner** under *Template* och klicka *Apply*. Unraid hämtar den färdiga imagen från GitHub Container Registry. Mappen i appdata skapas och får rätt behörigheter automatiskt.

**3. Logga in** – klicka på ikonen → *WebUI*. Engångslösenordet hittar du under ikonen → *Logs*. Byt lösenord (tvingas), slå på tvåstegsverifiering under *Konto* och ange datum och plats under *Inställningar*.

Imagen finns för både `amd64` och `arm64`.

## Uppdatering

Varje ändring i `main` bygger och publicerar automatiskt en ny `latest`-image efter att alla tester gått igenom. Imagen byggs dessutom om varje måndag med de senaste säkerhetsuppdateringarna i bas-imagen.

- **Manuellt:** *Docker → Check for Updates*. Står det **update ready** vid containern klickar du där och sedan på *Apply update*. All data finns kvar i appdata.
- **Automatiskt:** installera pluginen **CA Auto Update Applications** från Community Apps och slå på den för `wedding-planner`.
- Den version som körs syns längst ner på sidan *Konto*.
- Databasen uppgraderas automatiskt när en ny version startar. Ta gärna en backup först (se nedan).

Vill du låsa en viss version i stället för `latest`: ändra *Repository* i containerns inställningar till t.ex. `ghcr.io/braxhn/wedding-planner:1.0.0`.

## Exponera mot internet – säkert

Öppna **aldrig** en port i routern direkt till containern. Lägg den bakom en reverse proxy med HTTPS.

### Alternativ A: Cloudflare Tunnel (rekommenderas)
Med en tunnel behövs inga öppna portar alls.
1. Installera `cloudflared` från Community Apps.
2. Skapa en tunnel i Cloudflare Zero Trust: `brollop.dindomän.se` → `http://<unraid-ip>:8080`.
3. Sätt `BASE_URL=https://brollop.dindomän.se` i containerns inställningar. `TRUSTED_PROXIES` täcker som standard alla privata nät, så cloudflared i en annan container fungerar direkt.
4. **Extra lager (starkt rekommenderat):** skapa en Cloudflare Access-policy som kräver inloggning för hela domänen, med en *Bypass*-regel för de sökvägar som skyddas av egna tokens:

   | Sökväg | Används av | Skyddas av |
   |---|---|---|
   | `/r/*` | Gästportalen | Personlig 192-bitars länk |
| `/osa`, `/o/*` | OSA-kod och QR på tryckta inbjudningar | 50-bitars kod + spärr mot gissning |
   | `/p/*` | QR-koden på borden | Slumpad länk, kan bytas |
   | `/cal/*` | Kalenderprenumeration | Personlig länk, kan återkallas |
   | `/api/*` | Hemmahub | API-nyckel |
   | `/static/*` | CSS/JS | – |

   Då syns inloggningssidan bara för er, medan gästerna och Hemmahub fungerar som vanligt.

### Alternativ B: Nginx Proxy Manager / SWAG
1. Peka `brollop.dindomän.se` → `http://<unraid-ip>:8080` (eller `wedding-planner:8080` om båda ligger på samma Docker-nätverk, t.ex. `proxynet`). Aktivera Let's Encrypt och *Force SSL*.
2. Sätt `client_max_body_size 120m;`. Det behövs för bilduppladdning, och appen begränsar själv alla andra förfrågningar till 256 kB.
3. Sätt `BASE_URL`. `TRUSTED_PROXIES` täcker som standard alla privata nät, där proxyn finns.

### Fail2ban / CrowdSec
Misslyckade inloggningar och felaktiga API-nycklar loggas i ett format som är lätt att matcha:
```
WARNING wedding: login_failed ip=203.0.113.7 user=admin
WARNING wedding: api_auth_failed ip=203.0.113.7
```

## Nedräknings-API (Hemmahub)

1. Gå till **API** (syns för administratörer) → *Ny nyckel* → namnge den "Hemmahub". Kryssa i *Statistik* om du vill ha OSA-siffror också, och *Att göra-lista* om du vill visa uppgifterna som är kvar.
2. Kopiera nyckeln. Den visas bara en gång.
3. Låt Hemmahub anropa:

```bash
curl -H "Authorization: Bearer wp_DIN_NYCKEL" https://brollop.dindomän.se/api/v1/countdown
```

Exempelsvar:
```json
{
  "couple": "Anna & Erik",
  "date": "2027-06-12",
  "time": "14:00",
  "venue": "Ulriksdals slott",
  "days_left": 244,
  "weeks_left": 34,
  "seconds_left": 21088800,
  "datetime": "2027-06-12T14:00+02:00",
  "status": "upcoming",
  "label": "244 dagar kvar",
  "generated_at": "2026-10-11T21:00:00+02:00",
  "stats": {
    "guests": {"invited": 120, "attending": 84, "declined": 6, "pending": 30},
    "tasks": {"total": 38, "done": 12, "percent": 32},
    "speeches": 5
  },
  "tasks": [
    {"id": 7, "title": "Boka fotograf", "period": "12 månader innan", "due_date": "2026-10-20", "assignee": "Anna", "overdue": false}
  ]
}
```

- `status` är `unset`, `upcoming`, `today` eller `past`. Efter bröllopet innehåller svaret även `days_married`.
- Nyckeln kan också skickas som `X-API-Key: wp_…`. Nycklar i URL:en accepteras inte, eftersom de hamnar i loggar.
- Gränsen är 120 anrop per minut och nyckel. Hämta gärna en gång per timme och räkna ner sekunderna lokalt.
- **Om Hemmahub anropar från webbläsaren** (JavaScript i frontend) i stället för från sin server: sätt `API_CORS_ORIGINS=https://hemmahub.dindomän.se`. Då lägger API:t till rätt CORS-headers för just den adressen. Anrop från servern behöver ingenting.
- `tasks` (behörigheten *Att göra-lista*) innehåller upp till 50 uppgifter som är kvar, i samma ordning som i appen, med deadline, ansvarig och om den är försenad.
- Utan *Att göra-lista* lämnar API:t aldrig ut namn eller annan persondata, bara datum, plats och siffror. Med den behörigheten ingår uppgifternas text och vem som är ansvarig, men aldrig gästernas namn.

Exempel för Home Assistant (`configuration.yaml`):
```yaml
rest:
  - resource: https://brollop.dindomän.se/api/v1/countdown
    headers: { Authorization: !secret wedding_api_bearer }   # "Bearer wp_…"
    scan_interval: 3600
    sensor:
      - name: Bröllop dagar kvar
        value_template: "{{ value_json.days_left }}"
        unit_of_measurement: dagar
```

## E-post

Sätt `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` och gärna `SMTP_FROM_NAME`.

- **Gmail:** `smtp.gmail.com`, port `587`, `starttls`. Du behöver ett [app-lösenord](https://myaccount.google.com/apppasswords), inte ditt vanliga lösenord.
- **Outlook/Hotmail:** `smtp-mail.outlook.com`, port `587`, `starttls`.
- **One.com, Loopia m.fl.:** se respektive webbhotells SMTP-uppgifter.

Mejlen skickas med en kort paus mellan varje mejl (`SMTP_DELAY_SECONDS`, standard 1,5 s) så att e-postleverantören inte spärrar kontot. Gmail tillåter ungefär 500 mejl per dygn. Mallarna redigeras under *Inställningar → E-postmallar* med platshållarna `{namn} {länk} {kod} {osa_adress} {brudpar} {datum} {plats} {osa_senast}`. Skicka alltid ett testmejl till dig själv först.

## Inbjudningar per post (OSA med QR)

1. Lägg in gästerna, ett hushåll per rad, och ange *Antal inbjudna*.
2. Kontrollera att `BASE_URL` är satt till er publika adress, t.ex. `https://gift.braxhn.net`. QR-koderna pekar dit.
3. Gå till **Gäster → OSA-kort med QR**.
   - Ändra vid behov **texten under koden**, t.ex. "Svara senast {osa_senast}" eller en egen hälsning med `{namn}`. Ändringen förhandsvisas direkt.
   - **Skriv ut** ger ett A7-kort per hushåll, 8 per A4, att lägga i kuvertet.
   - **Ladda ner QR-filer (zip)** om ni har en egen inbjudningsdesign: `png/` (300 dpi) och `svg/` per hushåll plus `gaster.csv` med namn, kod och filnamn för dokumentkoppling.
4. Gästen skannar koden och hamnar direkt på sin OSA-sida. Den som inte kan skanna går till `er-adress/osa` och skriver in koden, t.ex. `2BTU7-Q3VF8`.

Tips: tryck QR-koden minst 2 × 2 cm och testa att skanna ett utskrivet kort innan ni trycker alla. Har ett kort hamnat fel kan ni klicka *Skapa ny länk och kod* på gästen, så slutar den gamla koden att fungera.

Koden består av 10 tecken utan förväxlingsbara tecken (inga I, L, O, 0 eller 1), vilket ger cirka 50 bitars slump. Efter 15 felaktiga försök spärras en IP-adress i 15 minuter. Efter 400 felaktiga försök totalt under en timme stängs kodinmatningen tillfälligt, vilket stoppar gissning från många adresser samtidigt. QR-länkarna som redan skannats fungerar som vanligt.

## Bilder från gästerna

1. Kontrollera att *Låt gäster ladda upp bilder* är påslaget under Inställningar. Det är på som standard.
2. Gå till **Bilder → Skriv ut bordskort**. Du får fyra kort per A4 med QR-kod.
3. Bestäm om gästerna ska se varandras bilder (*galleri*) och om ni vill granska bilderna först.

Varje bild avkodas och sparas om som en ny JPEG på högst 2560 px. Det tar bort **GPS-position och all annan metadata** och gör att skadliga filer inte kan smugglas in. Lagringsgränsen är 5 GB som standard och kan ändras.

> **iPhone:** Safari konverterar normalt HEIC till JPEG vid uppladdning. Om en bild ändå nekas kan gästen välja *Inställningar → Kamera → Format → Mest kompatibelt*.

## Säkerhetsdesign

**Inloggning**
- Lösenord hashas med **scrypt** (minnesintensiv, ca 32 MB per hash) och unikt salt.
- Lösenord måste vara minst 12 tecken. Nya konton tvingas byta lösenord vid första inloggningen.
- **TOTP-tvåstegsverifiering** med QR-kod, och skydd mot att samma kod används två gånger.
- **Rate limiting:** högst 5 misslyckade försök per användarnamn och 10 per IP på 15 minuter.
- Samma felmeddelande och samma svarstid oavsett om användarnamnet finns.

**Sessioner**
- Tokens på 256 bitar. I databasen lagras bara deras SHA-256-hash.
- Cookie med `__Host-`-prefix, `Secure`, `HttpOnly` och `SameSite=Strict` när appen nås via HTTPS. I standardläget `COOKIE_SECURE=auto` används en vanlig `HttpOnly`/`SameSite=Strict`-cookie vid direkt http-åtkomst på LAN:et, och inloggningssidan varnar då. Sätt `COOKIE_SECURE=true` när proxyn är på plats om du vill kräva HTTPS.
- Ny session vid varje inloggning. Byter du lösenord loggas alla andra enheter ut.
- Inloggningen gäller i högst 12 timmar och avslutas efter 2 timmars inaktivitet.

**Webbsäkerhet**
- CSRF-token på alla formulär. JSON-anropen (placering) kräver dessutom token i header och `Content-Type: application/json`.
- Strikt **Content-Security-Policy** utan inline-skript, plus HSTS, `nosniff`, `frame-ancestors 'none'` och `Referrer-Policy: no-referrer`. Den sista gör att gästlänkar inte läcker via Referer.
- Autoescape i alla mallar och parametriserad SQL. Tabell- och kolumnnamn kommer bara från en vitlista.
- Strikt validering av all indata: typ, längd, intervall, tillåtna val och `https://` för länkar.
- Storleksgräns på förfrågningar: 256 kB generellt och 120 MB för bilduppladdning. Gränsen kontrolleras både mot headern och mot faktiskt mottagen data.
- Skydd mot formelinjektion i CSV-exporten.
- Ingen öppen omdirigering, inga API-dokumentationssidor, ingen server-header och `noindex`.

**Gäster, bilder och e-post**
- Länkar och tokens är slumpade (144–256 bitar), har rate limiting per IP och kan återkallas.
- Presentreservationer låses i en transaktion, så två gäster kan inte ta sista exemplaret samtidigt.
- Bilder kodas om med Pillow, och dekomprimeringsbomber (över 50 megapixel) nekas. Filnamnen är slumpade, och dolda bilder visas aldrig publikt.
- E-postmallar fylls i med enkel textersättning, aldrig `str.format`. Rubriker byggs med `EmailMessage`, så header-injektion är inte möjlig. Anslutningen krypteras med TLS.
- API-nycklar och kalenderlänkar visas bara en gång och lagras hashade.

**Container**
- Startskriptet kör som root i en bråkdels sekund, bara för att ge `/data` ägaren `99:100`. Därefter byter det användare med `setpriv` och tar bort **alla** capabilities. Appen kör aldrig som root, vilket CI kontrollerar vid varje bygge.
- Skrivskyddat filsystem, endast `CHOWN`/`SETUID`/`SETGID` tillåts vid start, och `no-new-privileges`.
- Gränser för minne och antal processer.
- Databas och bilder skapas med rättigheterna `0600`/`0700`. Alla beroenden är versionslåsta.

## Backup
Appen tar själv en kopia av databasen varje dygn och sparar de senaste 14 i `backups/` i appdata-mappen (antalet ändras med `BACKUP_KEEP`). Under *Backup* (bara administratörer) kan du ladda ner kopiorna eller en färsk kopia, och där står hur man återställer. Bilderna ingår inte i de kopiorna.

All data ligger i `/mnt/user/appdata/wedding-planner/`: databasen `wedding.db` och mappen `photos/`. Pluginen *Appdata Backup* tar med allt. Manuell backup medan appen kör:
```bash
sqlite3 /mnt/user/appdata/wedding-planner/wedding.db ".backup '/mnt/user/backups/wedding-$(date +%F).db'"
rsync -a /mnt/user/appdata/wedding-planner/photos/ /mnt/user/backups/wedding-photos/
```

## Miljövariabler

| Variabel | Standard | Beskrivning |
|---|---|---|
| `BASE_URL` | – | Publik adress. Används i länkar, e-post och QR-koder. |
| `TRUSTED_PROXIES` | privata nät | IP/CIDR vars `X-Forwarded-For`/`-Proto` appen litar på |
| `COOKIE_SECURE` | `auto` | `auto`: säker cookie via https. `true`: kräv https. `false`: aldrig Secure |
| `PUID` / `PGID` | `99` / `100` | Användare och grupp som appen kör som |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / – | Första administratören. Används bara vid första start. |
| `SESSION_HOURS` / `SESSION_IDLE_MINUTES` | `12` / `120` | Sessionens maxlängd respektive inaktivitetsgräns |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_FROM_NAME` | – | E-postutskick |
| `SMTP_DELAY_SECONDS` | `1.5` | Paus mellan mejl |
| `API_CORS_ORIGINS` | – | Origins som får anropa API:t från en webbläsare |
| `MAX_UPLOAD_MB` / `MAX_UPLOAD_REQUEST_MB` | `20` / `120` | Max storlek per bild respektive per uppladdning |
| `TZ` | `Europe/Stockholm` | Tidszon. Styr vad som är "idag": nedräkningen, försenade uppgifter, sista dag för OSA, säkerhetskopior och läget för toastmastern. |

## Utveckling

```bash
pip install -r requirements.txt
bash tests/run.sh                      # ca 120 end-to-end-tester mot en riktig server
DATA_DIR=./data uvicorn app.main:app --reload --port 8080
```
Pull requests testas automatiskt. En release görs med en tagg: `git tag v1.1.0 && git push --tags`. Den ger imagetaggarna `1.1.0` och `1.1`.

### Med Claude Code
Repot är förberett för [Claude Code](https://code.claude.com/docs/en/overview). `CLAUDE.md` beskriver arkitekturen, säkerhetsreglerna och arbetsflödet, och `.claude/settings.json` installerar beroendena automatiskt i molnsessioner.
- **I webbläsaren eller mobilen:** öppna [claude.ai/code](https://claude.ai/code) och välj repot `BraXhn/wedding-planner`. Sessionen klonar repot, skapar en gren och kan öppna en pull request.
- **I terminalen:** `git clone https://github.com/BraXhn/wedding-planner && cd wedding-planner && claude`.

## Licens
MIT
