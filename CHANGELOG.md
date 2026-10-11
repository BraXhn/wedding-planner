# Ändringslogg

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
