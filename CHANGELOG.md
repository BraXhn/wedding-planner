# Ändringslogg

## Ej släppt
- **Säkerhet:** en aktiv tvåstegsverifiering kan inte längre bytas ut utan att först stängas av med lösenord. Andra inloggade sessioner loggas ut när den aktiveras. Kontroll av nuvarande lösenord (byte av lösenord, avstängning av 2FA) räknas mot samma spärr som inloggningen.
- Rättat: flera fall som gav "Internt fel" (500) i stället för ett begripligt svar: TOTP-kod eller formulärtoken med icke-ASCII-tecken, belopp som `inf` eller `1e400`, datum som år 1, orimligt stora id i adresser, placering och önskelista, konstiga värden i `?ok=` på bildsidorna, och nedladdning av QR-kod för gäster med namn som Łukasz.
- Rättat: "Antal som kommer" kan inte längre vara större än "Antal inbjudna".
- Rättat: ett utskick där SMTP-anslutningen misslyckades visades som lyckat med "0 skickade, 0 misslyckade". Nu räknas de mottagare som inte nåddes som misslyckade.
- Rättat: obetalda räkningar på översikten visade budgeterat belopp när det faktiska beloppet var 0 kr.
- Rättat: en gäst kunde ange ett annat uppladdarnamn än sitt eget på bilder. Gruppnamnet i CSV:n för OSA-korten skyddas nu mot formelinjektion i Excel.
- Repot är förberett för Claude Code: `CLAUDE.md` med arkitektur, säkerhetsregler och arbetsflöde, och `.claude/settings.json` som installerar beroenden i molnsessioner.

## 1.2.1 – 2026-10-14
- Rättat: efter en uppdatering kunde webbläsaren eller Cloudflare fortsätta visa den gamla stilmallen i upp till en timme. Sidan såg då trasig ut, med bland annat en synlig kryssruta vid "Meny". Stilmall, skript och ikon länkas nu med en hash av innehållet (`style.css?v=…`), så adressen byts när filen ändras. Versionerade filer cachas länge, och oversionerade kontrolleras alltid mot servern.

## 1.2.0 – 2026-10-14
- **OSA via QR-kod för tryckta inbjudningar.** Varje hushåll får en kort OSA-kod och en QR-kod. Under *Gäster → OSA-kort med QR* finns ett utskriftsark (A7-kort, 8 per A4) och en zip med QR-koderna som PNG/SVG plus en CSV för dokumentkoppling. Den som inte kan skanna går till `/osa` och skriver in koden. Koden byts tillsammans med länken via *Skapa ny länk och kod*. Felaktiga koder spärras per IP och totalt.
- Texten under koden på OSA-korten kan redigeras direkt på sidan *OSA-kort*, med förhandsvisning och platshållarna `{osa_senast}`, `{namn}`, `{antal}`, `{datum}`, `{brudpar}` och `{plats}`. Den finns också under Inställningar.
- Nya platshållare i e-postmallarna: `{kod}` och `{osa_adress}`.
- **"Kommer" utan antal** betyder nu att hela hushållet kommer. Befintliga gäster med "Kommer" och antal 0 rättas automatiskt vid uppdateringen. "Kommer inte" sätter antalet till 0.
- **Responsiv layout.** Sidan använder bredden på stora skärmar (upp till 1360 px), menyn fälls ihop bakom en *Meny*-knapp på mobil och surfplatta, och tabellerna visas som kort på mobilen.
- Rättat: siffrorna i tabellerna fick samma jättestora stil som siffrorna på översiktskorten.

## 1.1.0 – 2026-10-11
- API: ny behörighet *Att göra-lista* för API-nycklar. Svaret får då `tasks` med uppgifterna som är kvar (titel, period, deadline, ansvarig, försenad), t.ex. för att visa listan i Hemmahub. Saknar en uppgift deadline räknas den fram från bröllopsdatumet och perioden.

## 1.0.0 – 2026-10-11
Första versionen.
- Gäster med personliga OSA-länkar och gästportal (OSA, information, önskelista, bilder, kalender)
- Bordsplacering med dra-och-släpp
- Att göra-lista med automatiska deadlines utifrån bröllopsdatumet
- Budget, leverantörer, körschema och talarlista
- Gästernas bilduppladdning via QR-kod, med borttagning av EXIF/GPS och valfri granskning
- E-postutskick av inbjudningar och påminnelser
- Kalenderprenumeration (.ics)
- Nedräknings-API med API-nycklar (t.ex. för Hemmahub)
- Inloggning med scrypt, TOTP-tvåstegsverifiering, CSRF-skydd, strikt CSP och rate limiting
- Unraid-mall och multi-arch-image på ghcr.io
