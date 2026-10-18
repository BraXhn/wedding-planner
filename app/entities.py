"""Datamodell. Tabeller, formulär och listvyer genereras från dessa specar.
Kolumn-/tabellnamn i SQL kommer ENBART härifrån (vitlista) – aldrig från användarindata."""


def F(name, label, type="text", **kw):
    return {"name": name, "label": label, "type": type, **kw}


def S(label):
    """Rubrik i ett formulär (sparas inte)."""
    return {"name": "_" + label, "label": label, "type": "section"}


def opts(values):
    return [(v, v) for v in values]


CATEGORIES = [
    "Lokal", "Vigsel", "Mat & dryck", "Tårta", "Foto & film", "Kläder & styling",
    "Blommor & dekor", "Musik & underhållning", "Ringar", "Tryck & inbjudningar",
    "Transport", "Boende", "Bröllopsresa", "Övrigt",
]

PERIODS = [
    "12+ mån före", "9–12 mån före", "6–9 mån före", "3–6 mån före",
    "1–3 mån före", "Sista månaden", "Sista veckan", "Bröllopsdagen", "Efteråt",
]
# deadline relativt bröllopsdatum: (månader, dagar)
PERIOD_OFFSETS = {
    "12+ mån före": (-12, 0), "9–12 mån före": (-9, 0), "6–9 mån före": (-6, 0),
    "3–6 mån före": (-3, 0), "1–3 mån före": (-1, 0), "Sista månaden": (0, -10),
    "Sista veckan": (0, -2), "Bröllopsdagen": (0, 0), "Efteråt": (1, 0),
}

SPEECH_PARTS = ["Under förrätten", "Under varmrätten", "Under efterrätten", "Vid kaffet", "Under kvällen"]

RSVP_OPTIONS = [("pending", "Väntar"), ("yes", "Kommer"), ("no", "Kommer inte")]


# Programpunkter före 06:00 hör till natten efter bröllopsdagen (t.ex. 01:00 Nattmat) och sorteras sist.
NIGHT_CUTOFF = "06:00"
TIMELINE_ORDER = f"time < '{NIGHT_CUTOFF}', time"


def _case(col, values):
    return f"CASE {col} " + " ".join(f"WHEN '{v}' THEN {i}" for i, v in enumerate(values)) + " ELSE 99 END"


ENTITIES = {
    "guests": {
        "title": "Gäster", "singular": "gäst",
        "order": "name COLLATE NOCASE",
        "fields": [
            F("name", "Namn", required=True, help="Ett hushåll/sällskap per rad, t.ex. ”Anna & Erik Svensson”"),
            F("email", "E-post", "email", help="Behövs för e-postutskick"),
            F("phone", "Telefon"),
            F("street", "Gatuadress", help="För inbjudan med posten, t.ex. ”Storgatan 1” eller ”c/o Svensson, Storgatan 1”"),
            F("postcode", "Postnummer"),
            F("city", "Ort"),
            F("side", "Sida", "select", options=opts(["Gemensam", "Partner A", "Partner B"]), default="Gemensam"),
            F("group_name", "Grupp", help="t.ex. Familj, Vänner, Kollegor"),
            F("invited_count", "Antal inbjudna", "int", default=1, min=1, max=20),
            F("rsvp", "OSA", "select", options=RSVP_OPTIONS, default="pending"),
            F("attending", "Antal som kommer", "int", default=0, min=0, max=20,
              help="Lämnas tomt vid ”Kommer” → alla inbjudna räknas"),
            F("diet", "Specialkost – övrigt", "textarea",
              help="Allergier anges per person under Personer (eller av gästen i OSA-svaret)"),
            F("speech", "Vill hålla tal", "bool"),
            F("song", "Låtönskemål"),
            F("table_id", "Bord", "ref", ref="tables", help="Enklast via Placering"),
            F("avoid_guest_id", "Ska inte sitta vid samma bord som", "ref", ref="guests",
              help="Följs av ”Föreslå placering” under Placering"),
            F("message", "Meddelande från gäst", "textarea"),
            F("notes", "Egna anteckningar", "textarea"),
            F("gift_received", "Present från dem", help="Fylls i efter bröllopet – se Tackkort"),
            F("thanks_sent", "Tackkort skickat", "bool"),
        ],
        "list": ["name", "group_name", "invited_count", "rsvp", "attending", "diet", "table_id"],
        "search": ["name", "email", "group_name", "diet", "street", "city"],
        "sum": ["invited_count", "attending"],
        "filters": [("", "Alla"), ("pending", "Väntar"), ("yes", "Kommer"), ("no", "Kommer inte")],
        "extra_columns": {"rsvp_token": "TEXT", "rsvp_code": "TEXT", "rsvp_at": "TEXT", "invite_sent_at": "TEXT",
                          "reminder_sent_at": "TEXT", "table_no": "TEXT"},
    },
    "tables": {
        "title": "Bord", "singular": "bord", "nav": False,
        "order": "sort_no, name COLLATE NOCASE",
        "fields": [
            F("name", "Namn", required=True, help="t.ex. ”Bord 1” eller ”Brudbordet”"),
            F("seats", "Antal platser", "int", default=8, min=1, max=60),
            F("shape", "Form", "select", options=opts(["Runt", "Långbord", "Fyrkantigt"]), default="Runt"),
            F("sort_no", "Ordning", "int", default=0, min=0, max=999),
            F("notes", "Anteckningar", "textarea"),
        ],
        "list": ["name", "seats", "shape", "sort_no"],
        "search": ["name", "notes"],
        "sum": ["seats"],
        "filters": [],
        "back": "/seating",
    },
    "tasks": {
        "title": "Att göra", "singular": "uppgift",
        "order": "done, " + _case("period", PERIODS) + ", due_date IS NULL OR due_date = '', due_date, id",
        "fields": [
            F("title", "Uppgift", required=True),
            F("period", "När", "select", options=opts(PERIODS), default=PERIODS[0]),
            F("due_date", "Deadline", "date", help="Lämna tomt så räknas den ut från bröllopsdatumet"),
            F("assignee", "Ansvarig"),
            F("done", "Klar", "bool"),
            F("notes", "Anteckningar", "textarea"),
        ],
        "list": ["done", "title", "period", "due_date", "assignee"],
        "search": ["title", "assignee", "notes"],
        "sum": [],
        "filters": [("", "Alla"), ("open", "Kvar"), ("done", "Klara")],
    },
    "budget": {
        "title": "Budget", "singular": "budgetpost",
        "order": "category, item COLLATE NOCASE",
        "fields": [
            F("item", "Post", required=True),
            F("category", "Kategori", "select", options=opts(CATEGORIES), default="Övrigt"),
            F("estimated", "Budgeterat (kr)", "money"),
            F("actual", "Faktiskt (kr)", "money"),
            F("paid", "Betald", "bool"),
            F("due_date", "Förfallodatum", "date"),
            F("vendor_id", "Leverantör", "ref", ref="vendors", help="Sätts automatiskt när en leverantör med pris bokas"),
            F("notes", "Anteckningar", "textarea"),
        ],
        "list": ["item", "category", "estimated", "actual", "paid", "due_date"],
        "search": ["item", "category", "notes"],
        "sum": ["estimated", "actual"],
        "filters": [],
    },
    "vendors": {
        "title": "Leverantörer", "singular": "leverantör",
        "order": "category, name COLLATE NOCASE",
        "fields": [
            F("name", "Namn", required=True),
            F("category", "Kategori", "select", options=opts(CATEGORIES), default="Övrigt"),
            F("status", "Status", "select", options=opts(["Förfrågan", "Offert mottagen", "Bokad", "Avböjd"]), default="Förfrågan"),
            F("contact", "Kontaktperson"),
            F("phone", "Telefon"),
            F("email", "E-post", "email"),
            F("website", "Webbplats", "url"),
            F("price", "Pris (kr)", "money", help="När status är Bokad läggs priset in som budgeterat belopp i Budget"),
            F("notes", "Anteckningar", "textarea"),
        ],
        "list": ["name", "category", "status", "contact", "phone", "price"],
        "search": ["name", "category", "contact", "notes"],
        "sum": ["price"],
        "filters": [],
    },
    "timeline": {
        "title": "Körschema", "singular": "programpunkt",
        "order": TIMELINE_ORDER,
        "fields": [
            F("time", "Tid", "time", required=True, help="Tider före 06:00 räknas som natten efter bröllopsdagen"),
            F("title", "Vad", required=True),
            F("location", "Plats"),
            F("responsible", "Ansvarig"),
            F("public", "Visa för gäster", "bool", help="Syns i gästportalen och på bilduppladdningssidan"),
            F("notes", "Anteckningar", "textarea"),
        ],
        "list": ["time", "title", "location", "responsible", "public"],
        "search": ["title", "location", "responsible"],
        "sum": [],
        "filters": [],
    },
    "speeches": {
        "title": "Tal", "singular": "tal",
        "order": _case("part", SPEECH_PARTS) + ", order_no, id",
        "fields": [
            F("speaker", "Talare", required=True),
            F("guest_id", "Gäst", "ref", ref="guests", help="Kopplas automatiskt när en gäst anmäler tal via OSA"),
            F("topic", "Om / relation", help="t.ex. ”Brudens bror”"),
            F("part", "När", "select", options=opts(SPEECH_PARTS), default=SPEECH_PARTS[1]),
            F("order_no", "Ordning", "int", default=0, min=0, max=999),
            F("minutes", "Minuter", "int", default=5, min=1, max=60),
            F("status", "Status", "select", options=opts(["Anmäld", "Bekräftad", "Hållen", "Struken"]), default="Anmäld"),
            F("notes", "Anteckningar (t.ex. behöver mikrofon/projektor)", "textarea"),
        ],
        "list": ["part", "order_no", "speaker", "topic", "minutes", "status"],
        "search": ["speaker", "topic", "notes"],
        "sum": ["minutes"],
        "filters": [("", "Alla"), ("active", "Ej strukna")],
    },
    "wishlist": {
        "title": "Önskelista", "singular": "önskning",
        "order": "sort_no, title COLLATE NOCASE",
        "fields": [
            F("title", "Önskning", required=True),
            F("description", "Beskrivning", "textarea"),
            F("url", "Länk till produkt", "url"),
            F("price", "Ungefärligt pris (kr)", "money"),
            F("quantity", "Antal önskade", "int", default=1, min=1, max=100),
            F("sort_no", "Ordning", "int", default=0, min=0, max=999),
        ],
        "list": ["title", "price", "quantity"],
        "computed": [("reserved", "Reserverat", "(SELECT COALESCE(SUM(qty),0) FROM gift_reservations r WHERE r.gift_id = wishlist.id)")],
        "search": ["title", "description"],
        "sum": ["price"],
        "filters": [],
    },
}

QUESTION_KINDS = [("yesno", "Ja eller nej"), ("choice", "Välj ett alternativ"), ("text", "Fritext")]
ENTITIES["questions"] = {
    "title": "OSA-frågor", "singular": "fråga", "nav": False,
    "order": "sort_no, id",
    "fields": [
        F("label", "Fråga", required=True, help="Visas i OSA-formuläret för den som svarar ”Ja, gärna!”"),
        F("kind", "Typ av svar", "select", options=QUESTION_KINDS, default="yesno"),
        F("options", "Alternativ", "textarea", help="Ett alternativ per rad – bara för ”Välj ett alternativ”"),
        F("enabled", "Påslagen", "bool", default=1, help="Avstängda frågor visas inte för gästerna; svar som redan kommit in finns kvar"),
        F("sort_no", "Ordning", "int", default=0, min=0, max=999),
    ],
    "list": ["label", "kind", "enabled", "sort_no"],
    "search": ["label"],
    "sum": [],
    "filters": [],
}
ENTITIES["faq"] = {
    "title": "Frågor och svar", "singular": "fråga", "nav": False,
    "order": "sort_no, id",
    "fields": [
        F("question", "Fråga", required=True, help="t.ex. ”Får barn följa med?”, ”Finns det parkering?”, ”Vad ska vi ge i present?”"),
        F("answer", "Svar", "textarea", required=True),
        F("sort_no", "Ordning", "int", default=0, min=0, max=999),
    ],
    "list": ["question", "sort_no"],
    "search": ["question", "answer"],
    "sum": [],
    "filters": [],
}
ENTITIES["challenges"] = {
    "title": "Fotoutmaningar", "singular": "utmaning", "nav": False, "back": "/photos",
    "order": "sort_no, id",
    "fields": [
        F("text", "Utmaning", required=True, help="Visas på sidan där gästerna laddar upp bilder"),
        F("enabled", "Påslagen", "bool", default=1),
        F("sort_no", "Ordning", "int", default=0, min=0, max=999),
    ],
    "list": ["text", "enabled", "sort_no"],
    "search": ["text"],
    "sum": [],
    "filters": [],
}
CHALLENGE_SEED = [
    "En selfie med brudparet", "Någon du träffade för första gången i dag", "Bästa dansmovet",
    "Det finaste på bordet", "Ett skratt som inte går att hålla inne", "Er bästa gruppbild",
    "Någon som gråter av glädje", "Brudparet när de inte ser det",
]
QUESTION_SEED = [
    ("Behöver ni skjuts från stationen?", "yesno", ""),
    ("Var bor ni under helgen?", "choice", "Hemma / hos släkt\nHotellet vi tipsat om\nAnnat boende\nVet inte än"),
    ("Behöver ni barnstol?", "yesno", ""),
]

for _spec in ENTITIES.values():
    _spec["by_name"] = {f["name"]: f for f in _spec["fields"]}
    _spec.setdefault("nav", True)
    _spec.setdefault("computed", [])

SETTINGS_DEFAULTS = {
    "invite_subject": "Välkommen på vårt bröllop {datum}!",
    "invite_body": (
        "Hej {namn}!\n\nVi gifter oss {datum} på {plats} och vill gärna fira tillsammans med er.\n\n"
        "Svara om ni kommer och se all information här:\n{länk}\n\n"
        "Svara gärna senast {osa_senast}.\n\nVarma hälsningar\n{brudpar}"
    ),
    "reminder_subject": "Påminnelse: OSA till bröllopet {datum}",
    "reminder_body": (
        "Hej {namn}!\n\nVi har inte fått ert svar ännu – det tar bara en minut:\n{länk}\n\n"
        "Sista dag att svara är {osa_senast}.\n\nHälsningar\n{brudpar}"
    ),
    "photos_enabled": "1",
    "gallery_public": "0",
    "photo_moderation": "0",
    "photo_quota_mb": "5000",
    "osa_card_footer": "Svara senast {osa_senast}",
    "swish_message": "Bröllopsgåva",
    "digest_enabled": "1",
}

SETTINGS_FIELDS = [
    S("Bröllopet"),
    F("couple_names", "Brudparets namn", help="Visas i menyn, gästportalen och e-post"),
    F("wedding_date", "Bröllopsdatum", "date", help="Att göra-listans tomma deadlines fylls i automatiskt"),
    F("wedding_time", "Starttid", "time"),
    F("venue", "Plats"),
    F("address", "Adress"),
    F("dress_code", "Klädkod"),
    F("rsvp_deadline", "Sista dag för OSA", "date"),
    F("total_budget", "Total budget (kr)", "money"),
    S("Gästportal"),
    F("info_text", "Välkomsttext", "textarea", help="Visas överst för gästerna"),
    F("directions", "Hitta hit", "textarea", help="Vägbeskrivning, parkering, kollektivtrafik"),
    F("accommodation", "Boende", "textarea", help="Hotell, rabattkoder, sovplatser"),
    F("gift_info", "Presenter", "textarea", help="t.ex. bidrag till bröllopsresan. Visas ovanför önskelistan."),
    F("swish_number", "Swish-nummer", help="Mobilnummer eller Swish-nummer. Gästerna får en QR-kod att skanna med Swish under Önskelista."),
    F("swish_message", "Meddelande i Swish", help="Förifyllt i Swish, t.ex. ”Bröllopsgåva”. Högst 50 tecken, gästen kan ändra det."),
    S("Bilder"),
    F("photos_enabled", "Låt gäster ladda upp bilder", "bool"),
    F("gallery_public", "Gäster får se alla uppladdade bilder", "bool"),
    F("photo_moderation", "Granska bilder innan de visas för gäster", "bool"),
    F("photo_quota_mb", "Max lagring för bilder (MB)", "int", min=100, max=200_000),
    S("OSA-kort"),
    F("osa_card_footer", "Text under koden på OSA-korten", "textarea",
      help="Platshållare: {osa_senast} {namn} {antal} {datum} {brudpar} {plats}. Redigera gärna direkt på sidan OSA-kort med förhandsvisning."),
    S("Aviseringar"),
    F("notify_email", "Mejla oss när någon svarar på OSA",
      help="En eller flera e-postadresser, separerade med komma. Lämna tomt för inga mejl. Kräver SMTP."),
    F("digest_enabled", "Veckobrev varje måndag morgon", "bool",
      help="Till samma adresser: nya svar, vilka som inte svarat, uppgifter och räkningar som närmar sig"),
    S("E-postmallar"),
    F("invite_subject", "Ämne – inbjudan"),
    F("invite_body", "Text – inbjudan", "textarea", help="Platshållare: {namn} {länk} {kod} {osa_adress} {brudpar} {datum} {plats} {osa_senast}"),
    F("reminder_subject", "Ämne – påminnelse"),
    F("reminder_body", "Text – påminnelse", "textarea"),
]

TASK_SEED = [
    ("12+ mån före", "Sätt en total budget"),
    ("12+ mån före", "Gör en preliminär gästlista"),
    ("12+ mån före", "Bestäm datum och typ av vigsel (kyrklig/borgerlig)"),
    ("12+ mån före", "Boka lokal för vigsel och fest"),
    ("12+ mån före", "Boka vigselförrättare"),
    ("9–12 mån före", "Boka fotograf"),
    ("9–12 mån före", "Boka catering (om det inte ingår i lokalen)"),
    ("9–12 mån före", "Boka musik – band, DJ eller musiker till vigseln"),
    ("9–12 mån före", "Välj toastmaster/toastmadame"),
    ("9–12 mån före", "Skicka save the date"),
    ("6–9 mån före", "Beställ eller köp bröllopskläder"),
    ("6–9 mån före", "Boka florist"),
    ("6–9 mån före", "Boka hår och makeup"),
    ("6–9 mån före", "Planera bröllopsresan"),
    ("6–9 mån före", "Fyll i önskelistan"),
    ("3–6 mån före", "Skicka inbjudningar med personlig OSA-länk (Utskick)"),
    ("3–6 mån före", "Köp ringar"),
    ("3–6 mån före", "Beställ bröllopstårta"),
    ("3–6 mån före", "Boka transport"),
    ("3–6 mån före", "Ordna boende för långväga gäster"),
    ("1–3 mån före", "Begär hindersprövning hos Skatteverket (beviset gäller i 4 månader)"),
    ("1–3 mån före", "Provsmakning av meny"),
    ("1–3 mån före", "Planera vigselceremonin och musiken"),
    ("1–3 mån före", "Skicka OSA-påminnelse till dem som inte svarat"),
    ("1–3 mån före", "Gör bordsplaceringen"),
    ("Sista månaden", "Skicka specialkost-listan till catering"),
    ("Sista månaden", "Ge toastmaster läsbehörighet och gå igenom talarlistan"),
    ("Sista månaden", "Färdigställ körschemat för dagen"),
    ("Sista månaden", "Skriv ut bordskort med QR-kod för bilduppladdning"),
    ("Sista månaden", "Slutbetala leverantörer"),
    ("Sista veckan", "Lämna hindersprövningsbeviset till vigselförrättaren"),
    ("Sista veckan", "Bekräfta tider med alla leverantörer"),
    ("Sista veckan", "Packa nödkit (plåster, nål & tråd, värktabletter)"),
    ("Bröllopsdagen", "Ät frukost och njut!"),
    ("Efteråt", "Ladda ner alla gästbilder"),
    ("Efteråt", "Skicka tackkort"),
    ("Efteråt", "Byt efternamn hos Skatteverket (om aktuellt)"),
    ("Efteråt", "Lämna tillbaka hyrda saker"),
]
