# Ändringslogg

## 1.2.0 – 2026-10-14
- **OSA via QR-kod för tryckta inbjudningar.** Varje hushåll får en kort OSA-kod och en QR-kod. Under *Gäster → OSA-kort med QR* finns ett utskriftsark (A7-kort, 8 per A4) och en zip med QR-koderna som PNG/SVG plus en CSV för dokumentkoppling. Den som inte kan skanna går till `/osa` och skriver in koden. Koden byts tillsammans med länken via *Skapa ny länk och kod*. Felaktiga koder spärras per IP och totalt.
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
