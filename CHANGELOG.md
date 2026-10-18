# Ändringslogg

## Ej släppt

## 1.3.0 – 2026-10-18
- **Roligare QR-koder.** Trycksakernas QR-kod kan ritas med prickar, rundade rutor, små hjärtan eller romber, med matchande hörnmarkeringar, och med ett hjärta, två ringar, era initialer eller en kamera i mitten – i kortets färg eller svart. Koden använder då högsta felkorrigeringen, så motivet i mitten tar inte bort något. OSA-korten får prickar med hjärta och bordskorten för bilder rundade rutor med en kamera. Alla 400 kombinationer av stil, motiv, färg och länktyp är provlästa med en QR-avkodare.
- **Trycksaker: sju nya designer** – minimal, monogram (initialerna i en cirkel), art déco, akvarell, krans (initialerna i en lagerkrans), båge och rustik – och tre nya färger (salvia, terrakotta, lavendel). Designen väljs genom att klicka på små förhandsvisningar.
- **Färgat papper:** välj papperets färg (kräm, kraft, salvia, dammrosa, ljusblå, grå eller annan). Då skrivs ingen bakgrund eller fyllning ut – bara text, linjer och ornament – och förhandsvisningen visar kortet på det papperet.
- Lång text krymps automatiskt så att den får plats på kortet, och redigeringen varnar när det händer. Ny platshållare `{initialer}`.
- **Trycksaker:** förslag på save the date, inbjudan, tackkort, meny, program och välkomstskylt som redigeras i appen med förhandsvisning medan man skriver. Fyra designer, fem färger och formaten A6 (stående/liggande), A5 och A4. Personliga trycksaker skrivs ut ett per hushåll (alla, de som inte svarat eller de som kommer) med namn och egen OSA-QR; {program} fylls med körschemat och {present} med presenten från Tackkort. Läsare ser förhandsvisningen men kan inte skriva ut kort med gästernas koder.
- **Personer per hushåll.** Gästen skriver i OSA-svaret namn och allergier för var och en som kommer och bockar ur den som inte kan. ”Antal som kommer” räknas fram från personerna. Samma uppgifter går att redigera under Gäster → Personer. Det gamla fältet för specialkost finns kvar som ”Specialkost – övrigt”.
- **Postadress** per hushåll (gatuadress, postnummer, ort), med i CSV:n för dokumentkoppling på OSA-korten.
- **Till cateringen:** antal som kommer, allergier per person och bord och en sammanställning. Utskrift och CSV.
- **Bordskort med namn** (ett per person, 8 per A4) och **placeringslista** i bokstavsordning, under Placering.
- **Dagen:** sida för toastmaster och brudpar med vad som händer nu och härnäst, körschemat och talen per del av middagen. Uppdateras varje minut; före bröllopet kan man förhandsvisa en viss tid.
- **Bildspel** för projektor under Bilder: helskärm, nya bilder visas direkt, QR-kod för uppladdning i hörnet.
- **Tackkort:** present och avbockning per hushåll, med adress.
- **Swish-QR** i gästportalens önskelista när ett Swish-nummer är angivet under Inställningar.
- **Mejl till er** när någon svarar på OSA (Inställningar → Aviseringar, en eller flera adresser).
- **Bokade leverantörer** läggs in i budgeten automatiskt med priset som budgeterat belopp.
- **Säkerhetskopior:** en kopia av databasen varje dygn (de senaste 14 sparas) och nedladdning för administratörer under Användare → Säkerhetskopior.
- Nytt bröllopsdatum flyttar de deadlines som räknats ut från det gamla; egna datum lämnas.
- Programpunkter före 06:00 räknas som natten efter bröllopsdagen: de sorteras sist och får rätt datum i kalendern.
- Läsare (t.ex. toastmaster) ser inte längre gästernas OSA-länkar, koder eller QR-koder, varken på gästsidan, i CSV-exporten eller på OSA-korten.
- Tidszonen är `Europe/Stockholm` som standard i imagen, CI kontrollerar att den gäller och appen varnar i loggen om den saknas.
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
