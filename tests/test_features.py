import email.policy, re, sys, io, json, time, uuid, sqlite3, urllib.request, urllib.parse, http.cookiejar
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.security import format_code, totp_now
from PIL import Image
S = sys.argv[2]; B = "http://127.0.0.1:" + __import__("os").environ.get("TEST_PORT", "8099")
PW = re.search(r"Engångslösenord: (\S+)", open(sys.argv[1]).read()).group(1)
DB = sqlite3.connect(S + "/data/wedding.db"); DB.row_factory = sqlite3.Row
q = lambda sql, *a: DB.execute(sql, a).fetchall()
results = []
def ok(c, m): results.append(c); print(("PASS " if c else "FAIL ") + m)

class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedir)
def req(op, path, data=None, follow=True, headers=None, raw=None, method=None):
    body = raw if raw is not None else (urllib.parse.urlencode(data).encode() if data is not None else None)
    for _ in range(5):
        r = urllib.request.Request(B + path, body, headers=headers or {}, method=method)
        try:
            resp = op.open(r); return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303) and follow:
                path = e.headers["location"]; body = None; headers = None; method = None; continue
            return e.code, e.headers, e.read()
def read_mail():
    import email, email.header
    out = []
    for blk in open(S + "/mail.txt").read().split("=====\n"):
        if "\n" not in blk: continue
        m = email.message_from_string(blk.split("\n", 1)[1], policy=email.policy.default)
        out.append(str(m["Subject"]) + "\n" + m.get_content())
    return "\n".join(out)
def html(t): return t[2].decode("utf-8", "replace")
def csrf(h): return re.search(r'name="csrf" value="([^"]+)"', h).group(1)
def multipart(fields, files):
    bnd = uuid.uuid4().hex; out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, (fn, data, ct) in files:
        out.write(f'--{bnd}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\nContent-Type: {ct}\r\n\r\n'.encode())
        out.write(data); out.write(b"\r\n")
    out.write(f"--{bnd}--\r\n".encode())
    return out.getvalue(), {"Content-Type": f"multipart/form-data; boundary={bnd}"}

# ---------------------------------------------------------------- inloggning & grund
a = client()
r = req(a, "/login", {"username": "testadmin", "password": PW}); c = csrf(html(r))
NEW = "Korrekt-Häst-Batteri-Häftklammer"
r = req(a, "/account/password", {"csrf": c, "current": PW, "new": NEW, "new2": NEW}); ok("bytt" in html(r), "inloggning + lösenordsbyte")
r = req(a, "/"); ok(r[0] == 200 and "Gästbilder" in html(r), "översikt med nya kort")

# ---------------------------------------------------------------- inställningar + automatiska deadlines
SET = {"csrf": c, "couple_names": "Anna & Erik", "wedding_date": "2027-06-12", "wedding_time": "14:00",
     "venue": "Ulriksdals slott", "address": "Slottsvägen 1", "rsvp_deadline": "2027-04-01", "total_budget": "250000",
     "info_text": "Välkomna!", "directions": "Buss 503", "accommodation": "Hotell X", "gift_info": "Swish 123",
     "photos_enabled": "on", "photo_quota_mb": "500",
     "invite_subject": "Inbjudan {brudpar} {__class__}", "invite_body": "Hej {namn}! {länk} {datum} {0.__class__}",
     "reminder_subject": "Påminnelse", "reminder_body": "Svara {länk}", "notify_email": "louise@example.se; anton@example.se",
       "swish_number": "+46 70-123 45 67", "swish_message": "Bröllopsgåva", "capsule_enabled": "on", "digest_enabled": "on"}
r = req(a, "/settings", SET)
h = html(r); ok("Sparat" in h and "deadlines" in h, "inställningar sparas + deadlines fylls i")
ok(q("SELECT value FROM settings WHERE key='notify_email'")[0][0] == "louise@example.se, anton@example.se", "aviseringsadresser normaliseras")
r = req(a, "/settings", {"csrf": c, "notify_email": "louise@example.se, inte-en-adress"})
ok(r[0] == 400 and "ogiltig adress" in html(r), "ogiltig aviseringsadress nekas")
ok(q("SELECT value FROM settings WHERE key='swish_number'")[0][0] == "0701234567", "Swish-nummer normaliseras")
r = req(a, "/settings", {**SET, "swish_number": "12345"}); ok(r[0] == 400 and "Swish-nummer" in html(r), "ogiltigt Swish-nummer nekas")
r = req(a, "/settings", {**SET, "swish_message": "a;b"}); ok(r[0] == 400 and "Meddelande i Swish" in html(r), "semikolon i Swish-meddelandet nekas")
d = q("SELECT due_date FROM tasks WHERE title LIKE 'Begär hindersprövning%'")[0][0]
ok(d == "2027-05-12", f"hindersprövning-deadline = 1 mån före ({d})")
ok(q("SELECT due_date FROM tasks WHERE period='Efteråt' LIMIT 1")[0][0] == "2027-07-12", "efteråt-deadline")
ok(q("SELECT COUNT(*) FROM tasks WHERE COALESCE(due_date,'')=''")[0][0] == 0, "alla uppgifter fick deadline")
own = q("SELECT id FROM tasks WHERE title LIKE 'Boka fotograf%'")[0][0]
DB.execute("UPDATE tasks SET due_date = '2026-12-24' WHERE id = ?", (own,)); DB.commit()
h = html(req(a, "/settings", {**SET, "wedding_date": "2027-08-14"}))
ok(q("SELECT due_date FROM tasks WHERE title LIKE 'Begär hindersprövning%'")[0][0] == "2027-07-14" and "flyttades" in h,
   "nytt bröllopsdatum flyttar uträknade deadlines")
ok(q("SELECT due_date FROM tasks WHERE id=?", own)[0][0] == "2026-12-24", "egna deadlines rörs inte vid nytt datum")
req(a, "/settings", SET)
ok(q("SELECT due_date FROM tasks WHERE title LIKE 'Begär hindersprövning%'")[0][0] == "2027-05-12", "och tillbaka igen")

# ---------------------------------------------------------------- bord & placering
for name, seats in (("Bord 1", 4), ("Bord 2", 8)):
    req(a, "/m/tables/new", {"csrf": c, "name": name, "seats": seats, "shape": "Runt", "sort_no": 0})
t1, t2 = [r_[0] for r_ in q("SELECT id FROM tables ORDER BY id")]
def add_guest(name, n=2, email=""):
    req(a, "/m/guests/new", {"csrf": c, "name": name, "invited_count": n, "rsvp": "pending", "side": "Gemensam", "email": email})
    return q("SELECT id, rsvp_token FROM guests WHERE name=?", name)[0]
gA = add_guest("Familjen Andersson", 3, "a@example.se")
gB = add_guest("Bertil", 1, "b@example.se")
gC = add_guest("Cecilia & Carl", 2)
r = req(a, f"/m/guests/{gA[0]}", {"csrf": c, "name": "Familjen Andersson", "invited_count": 3, "rsvp": "pending", "side": "Gemensam", "table_id": "9999"})
ok(r[0] == 400 and "ogiltigt val" in html(r), "ogiltigt bord-id nekas")
J = {"Content-Type": "application/json", "X-CSRF-Token": c}
r = req(a, "/seating/assign", raw=json.dumps({"guest_id": gA[0], "table_id": t1}).encode(), headers=J)
ok(r[0] == 200 and q("SELECT table_id FROM guests WHERE id=?", gA[0])[0][0] == t1, "placering via dra-och-släpp-API")
r = req(a, "/seating/assign", raw=json.dumps({"guest_id": gB[0], "table_id": t1}).encode(), headers={"Content-Type": "application/json"})
ok(r[0] == 403, "placering utan CSRF-header nekas")
r = req(a, "/seating/assign", raw=b"guest_id=1&table_id=1", headers={"Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": c})
ok(r[0] == 415, "placering måste vara JSON")
r = req(a, "/seating/assign", raw=json.dumps({"guest_id": gB[0], "table_id": 9999}).encode(), headers=J); ok(r[0] == 404, "okänt bord 404")
ok(req(a, "/seating/assign", raw=b'{"guest_id": 1e400}', headers=J)[0] == 400
   and req(a, "/seating/assign", raw=json.dumps({"guest_id": 10**20}).encode(), headers=J)[0] == 400, "orimligt stort id i placering → 400")
ok(req(a, "/m/guests/99999999999999999999")[0] == 404, "orimligt stort id i adressen → 404")
req(a, "/seating/assign", raw=json.dumps({"guest_id": gB[0], "table_id": t1}).encode(), headers=J)
r = req(a, "/seating"); h = html(r)
ok("4</b>/4" in h or "<b data-used>4</b>/4" in h, "kapacitet räknas (3+1 av 4)")
req(a, "/seating/assign", raw=json.dumps({"guest_id": gC[0], "table_id": t1}).encode(), headers=J)
ok('seat-table runt over' in html(req(a, "/seating")), "överfullt bord markeras")
r = req(a, "/m/guests"); ok("Bord 1" in html(r), "bordsnamn i gästlistan")
req(a, f"/m/tables/{t2}/delete", {"csrf": c})
req(a, "/seating/assign", raw=json.dumps({"guest_id": gC[0], "table_id": None}).encode(), headers=J)
ok(q("SELECT table_id FROM guests WHERE id=?", gC[0])[0][0] is None, "flytta tillbaka till ”utan bord”")

# ---------------------------------------------------------------- gästportal, OSA + tal
p = client()
r = req(p, f"/r/{gA[1]}"); h = html(r)
ok(r[0] == 200 and "Information" in h and "/info" in h, "gästportal med flikar")
FAM = {"answer": "yes", "name_1": "Anders", "coming_1": "on", "allergy_1": "Nötter", "name_2": "Annika", "coming_2": "on",
       "name_3": "Albin", "coming_3": "on"}
r = req(p, f"/r/{gA[1]}", {**FAM, "speech": "on"})
ok(q("SELECT COUNT(*) FROM speeches WHERE guest_id=? AND status='Anmäld'", gA[0])[0][0] == 1, "talanmälan via OSA → talarlistan")
req(p, f"/r/{gA[1]}", FAM)
ok(q("SELECT status FROM speeches WHERE guest_id=?", gA[0])[0][0] == "Struken", "ångrat tal → struket")
for _ in range(30):
    if "OSA: Familjen Andersson kommer (3 av 3)" in read_mail(): break
    time.sleep(0.1)
m = read_mail()
ok("OSA: Familjen Andersson kommer (3 av 3)" in m and "- Anders (allergi/specialkost: N" in m and "- Albin" in m
   and "Vill h" in m and f"/m/guests/{gA[0]}" in m, "brudparet får mejl när någon svarar på OSA")
ok(q("SELECT COUNT(*) FROM mail_log WHERE kind='notify' AND ok=1")[0][0] >= 2, "aviseringen går till båda adresserna")
pp = q("SELECT pos, name, attending, allergies FROM guest_people WHERE guest_id=? ORDER BY pos", gA[0])
ok([tuple(x) for x in pp] == [(1, "Anders", 1, "Nötter"), (2, "Annika", 1, ""), (3, "Albin", 1, "")]
   and q("SELECT attending FROM guests WHERE id=?", gA[0])[0][0] == 3, "OSA sparar namn och allergi per person")
h = html(req(p, f"/r/{gA[1]}")); ok('value="Annika"' in h and 'value="Nötter"' in h, "OSA-formuläret visar sparade personer")
r = req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, "name_1": "Anders", "coming_1": "on", "allergy_1": "Nötter",
                                         "name_2": "Annika", "name_3": "Albin", "coming_3": "on"})
ok(q("SELECT attending FROM guests WHERE id=?", gA[0])[0][0] == 2, "admin bockar ur en person → antal som kommer räknas om")
ok(req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, "name_1": "Anders"})[0] == 400, "admin: minst en måste komma vid ”Kommer”")
ok(req(a, f"/m/guests/{gA[0]}/people", {"name_1": "X", "coming_1": "on"})[0] == 403, "personer kräver CSRF")
req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, **{k: v for k, v in FAM.items() if k != "answer"}, "allergy_2": "Gluten, nötter", "allergy_3": "<i>Soja"})

# ---------------------------------------------------------------- veckobrev
open(S + "/mail.txt", "w").close()
r = req(a, "/mail/veckobrev", {"csrf": c})
ok(r[0] == 200 and "Veckobrevet är skickat" in html(r), "veckobrev: skicka nu")
m = read_mail()
ok("Veckobrev:" in m and "personer kommer" in m and "Nya svar den senaste veckan" in m and "Familjen Andersson: kommer (3)" in m
   and "/\n" in m.replace("\r", ""), "veckobrev: nya svar, OSA-läge och länk")
ok(req(a, "/mail/veckobrev", {"csrf": "fel"})[0] == 403 and req(client(), "/mail/veckobrev", {"csrf": c}, follow=False)[0] == 303,
   "veckobrev kräver CSRF och inloggning")

# ---------------------------------------------------------------- frågor och svar i gästportalen
ok("Frågor och svar" not in html(req(p, f"/r/{gA[1]}/info")), "FAQ: inget avsnitt när listan är tom")
req(a, "/m/faq/new", {"csrf": c, "question": "Får barn följa med?", "answer": "Ja, alla barn är välkomna.\nSäg till om barnstol.", "sort_no": "1"})
req(a, "/m/faq/new", {"csrf": c, "question": "<b>Parkering?</b>", "answer": "Finns vid slottet.", "sort_no": "0"})
h = html(req(p, f"/r/{gA[1]}/info"))
ok("Frågor och svar" in h and h.index("Parkering") < h.index("Får barn") and "&lt;b&gt;Parkering" in h,
   "FAQ: frågorna visas i gästportalen, sorterade och escapade")
ok(req(a, "/m/faq/new", {"csrf": c, "question": "Utan svar"})[0] == 400, "FAQ: svar krävs")

# ---------------------------------------------------------------- egna OSA-frågor
qid = {r[0]: r[1] for r in q("SELECT label, id FROM questions")}
q_ride, q_stay, q_chair = qid["Behöver ni skjuts från stationen?"], qid["Var bor ni under helgen?"], qid["Behöver ni barnstol?"]
h = html(req(p, f"/r/{gA[1]}"))
ok(all(f'name="q_{i}"' in h for i in (q_ride, q_stay, q_chair)) and "Hotellet vi tipsat om" in h, "OSA-frågor: förslagen visas i formuläret")
r = req(p, f"/r/{gA[1]}", {**FAM, f"q_{q_stay}": "Slottet"})
ok(r[0] == 400 and "Ogiltigt val" in html(r), "OSA-frågor: ogiltigt alternativ nekas")
req(p, f"/r/{gA[1]}", {**FAM, f"q_{q_ride}": "ja", f"q_{q_stay}": "Hotellet vi tipsat om", f"q_{q_chair}": "nej"})
ok({r[0]: r[1] for r in q("SELECT question_id, value FROM answers WHERE guest_id=?", gA[0])}
   == {q_ride: "ja", q_stay: "Hotellet vi tipsat om", q_chair: "nej"}, "OSA-frågor: svaren sparas")
for _ in range(30):
    if "Behöver ni skjuts från stationen? ja" in read_mail(): break
    time.sleep(0.1)
ok("stationen? ja" in read_mail(), "OSA-frågor: svaren står i mejlet till brudparet")
req(a, f"/m/questions/{q_chair}", {"csrf": c, "label": "Behöver ni barnstol?", "kind": "yesno", "options": "", "sort_no": "2"})
ok(f'name="q_{q_chair}"' not in html(req(p, f"/r/{gA[1]}")), "OSA-frågor: avstängd fråga visas inte för gästerna")
h = html(req(a, "/rapport/svar"))
ok("Familjen Andersson" in h and "Avstängd" in h and "1 hushåll (3 pers.)" in h, "OSA-frågor: sammanställning med antal personer")
ok(f"Familjen Andersson;3;ja;Hotellet vi tipsat om;nej" in req(a, "/rapport/svar.csv")[2].decode("utf-8-sig"), "OSA-frågor: CSV")
ok("Var bor ni under helgen?" in html(req(a, f"/m/guests/{gA[0]}")), "OSA-frågor: svaren syns på gästsidan")
req(a, "/m/questions/new", {"csrf": c, "label": "<i>Ny</i> fråga?", "kind": "text", "enabled": "on", "sort_no": "9"})
ok("&lt;i&gt;Ny" in html(req(p, f"/r/{gA[1]}")), "OSA-frågor: egen fråga visas och escapas")
req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, **{k: v for k, v in FAM.items() if k != "answer"}, "allergy_2": "Gluten, nötter", "allergy_3": "<i>Soja"})

# ---------------------------------------------------------------- rapporter: mat, bordskort, placeringslista
tname = q("SELECT t.name FROM tables t JOIN guests g ON g.table_id = t.id WHERE g.id=?", gA[0])[0][0]
h = html(req(a, "/rapport/mat"))
ok("Anders" in h and "Nötter" in h and "<strong>2</strong> × nötter" in h and "<strong>1</strong> × gluten" in h,
   "matrapport: allergier per person och sammanställning")
ok("&lt;i&gt;Soja" in h and "<i>Soja" not in h, "matrapport escapar allergitext")
body = req(a, "/rapport/mat.csv")[2].decode("utf-8-sig")
ok(f"{tname};Anders;Familjen Andersson;Nötter" in body, "matrapport som CSV")
h = html(req(a, "/seating/kort"))
ok(h.count('class="place-card"') == 3 and "Albin" in h and tname in h, "bordskort: ett per person som kommer")
h = html(req(a, "/seating/lista"))
ok(h.index("Albin") < h.index("Anders") < h.index("Annika"), "placeringslista i bokstavsordning")
ok(req(client(), "/rapport/mat", follow=False)[0] == 303 and req(client(), "/seating/kort", follow=False)[0] == 303,
   "rapporter kräver inloggning")
req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, **{k: v for k, v in FAM.items() if k != "answer"}})
r = req(p, f"/r/{gA[1]}/info"); h = html(r)
ok("Buss 503" in h and "Hotell X" in h, "informationssida")
for t, title in (("15:00", "Vigsel i parken"), ("01:00", "Nattmat"), ("18:00", "Middag")):
    req(a, "/m/timeline/new", {"csrf": c, "time": t, "title": title, "public": "on"})
r = req(p, f"/r/{gA[1]}/brollop.ics"); body = r[2].decode()
ok(r[0] == 200 and "BEGIN:VEVENT" in body and "DTSTART:20270612T140000" in body and "\r\n" in body, "gästens .ics")
ok("DTSTART:20270613T010000" in body and "DTSTART:20270612T150000" in body, "programpunkt efter midnatt hamnar på dagen efter i .ics")
h = html(req(p, f"/r/{gA[1]}/info"))
ok(h.index("Vigsel i parken") < h.index("Middag") < h.index("Nattmat"), "programmet sorterar nattens punkter sist")
h = html(req(a, "/m/timeline"))
ok(h.index("Vigsel i parken") < h.index("Middag") < h.index("Nattmat"), "körschemat sorterar nattens punkter sist")
h = html(req(a, "/dagen"))
ok("Förhandsvisa" in h and h.index("Vigsel i parken") < h.index("Nattmat"), "dagen: hela körschemat före bröllopet")
h = html(req(a, "/dagen?tid=19:30"))
now_box = h.split('class="card now"')[1].split("</section>")[0]
ok("Middag" in now_box and "Nattmat" in h.split("Härnäst")[1].split("</section>")[0], "dagen: nu = senast startade punkt, härnäst = nästa")
ok("om 5 h 30 min" in h, "dagen: tid kvar till nästa punkt räknas över midnatt")
h = html(req(a, "/dagen?tid=02:00"))
ok("Nattmat" in h.split('class="card now"')[1].split("</section>")[0], "dagen: efter midnatt är nattens punkt aktuell")
ok(req(a, "/dagen?tid=25:99")[0] == 200 and "Förhandsvisa" in html(req(a, "/dagen?tid=25:99")), "dagen: ogiltig tid ignoreras")

# ---------------------------------------------------------------- önskelista
req(a, "/m/wishlist/new", {"csrf": c, "title": "Kaffemaskin", "quantity": 1, "price": "3000", "url": "https://shop.example/kaffe"})
gift = q("SELECT id FROM wishlist")[0][0]
p2 = client()
r = req(p, f"/r/{gA[1]}/gifts", {"gift_id": gift, "action": "reserve"}); ok("Ni har reserverat" in html(r), "gäst A reserverar")
r = req(p2, f"/r/{gB[1]}/gifts", {"gift_id": gift, "action": "reserve"}); ok(r[0] == 409, "gäst B kan inte ta samma (409)")
r = req(p2, f"/r/{gB[1]}/gifts", {"gift_id": gift, "action": "release"})
ok(q("SELECT COUNT(*) FROM gift_reservations")[0][0] == 1, "gäst B kan inte släppa A:s reservation")
h = html(req(a, "/m/wishlist")); ok("1 / 1" in h and "Andersson" not in h, "brudparet ser antal men inte vem")
req(p, f"/r/{gA[1]}/gifts", {"gift_id": gift, "action": "release"})
ok(q("SELECT COUNT(*) FROM gift_reservations")[0][0] == 0, "gäst A ångrar")
ok(req(client(), f"/r/{gB[1]}/gifts", {"gift_id": "9" * 25, "action": "reserve"})[0] == 400, "orimligt stort present-id → 400")
ok('rel="noopener noreferrer nofollow"' in html(req(p, f"/r/{gA[1]}/gifts")), "externa länkar med noopener")
h = html(req(p, f"/r/{gA[1]}/gifts"))
ok("Swisha en gåva" in h and 'value="070-123 45 67"' in h and h.count("<svg") >= 1, "Swish-QR och nummer i gästportalen")

# ---------------------------------------------------------------- kalenderprenumeration
r = req(a, "/account/ics", {"csrf": c, "action": "create"}); feed = re.search(r'id="icsurl" value="[^"]+(/cal/[^"]+)"', html(r)).group(1)
r = req(client(), feed); body = r[2].decode()
ok(r[0] == 200 and "Att göra:" in body and "Sista dag för OSA" in body, "personlig kalenderprenumeration")
req(a, "/account/ics", {"csrf": c, "action": "revoke"})
ok(req(client(), feed)[0] == 404, "återkallad kalenderlänk slutar fungera")

# ---------------------------------------------------------------- bilder
r = req(a, "/photos"); h = html(r)
ptok = re.search(r'id="upurl" value="[^"]*/p/([^"]+)"', h).group(1)
ok("<svg" in h, "QR-kod på bildsidan")
def jpeg_with_gps():
    im = Image.new("RGB", (4000, 3000), (200, 100, 50))
    exif = Image.Exif(); exif[0x010F] = "SpionKamera"; gps = exif.get_ifd(0x8825); gps[2] = (59.0, 19.0, 0.0)
    b = io.BytesIO(); im.save(b, "JPEG", exif=exif.tobytes()); return b.getvalue()
raw = jpeg_with_gps()
ok(b"SpionKamera" in raw, "(testbild har EXIF)")
body, hd = multipart({"name": "Moster Agda"}, [("photos", ("IMG_1.jpg", raw, "image/jpeg")), ("photos", ("evil.jpg", b"<script>alert(1)</script>", "image/jpeg"))])
r = req(client(), f"/p/{ptok}", raw=body, headers=hd); h = html(r)
ok("1 bild" in h and "kunde inte läsas" in h, "uppladdning: bild sparas, falsk bild nekas")
f = q("SELECT file, width FROM photos")[0]
stored = open(f"{S}/data/photos/{f['file']}", "rb").read()
ok(b"SpionKamera" not in stored and b"Exif" not in stored[:200] and f["width"] == 2560, "EXIF/GPS borttaget, nedskalad till 2560px")
b = io.BytesIO(); Image.new("L", (9000, 9000)).save(b, "PNG")
body, hd = multipart({}, [("photos", ("bomb.png", b.getvalue(), "image/png"))])
r = req(client(), f"/p/{ptok}", raw=body, headers=hd); ok("kunde inte läsas" in html(r), "dekomprimeringsbomb (81 MP) nekas")
ok(req(client(), f"/p/{'x'*24}")[0] == 404, "fel uppladdningstoken 404")
ok(req(client(), f"/p/{ptok}/img/{f['file']}")[0] == 404, "galleri avstängt → bilder ej publika")
ok(req(a, f"/photos/img/{f['file']}")[0] == 200, "admin ser bilden")
ok(req(a, "/photos/img/..%2Fwedding.db")[0] == 404 and req(a, "/photos/img/../wedding.db")[0] == 404, "path traversal på bilder")
body, hd = multipart({"name": "Någon annan"}, [("photos", ("p.jpg", raw, "image/jpeg"))])
r = req(p, f"/r/{gA[1]}/photos", raw=body, headers=hd)
last = q("SELECT guest_id, uploader FROM photos ORDER BY id DESC LIMIT 1")[0]
ok(last[0] == gA[0], "uppladdning via gästportal kopplas till gästen")
ok(last[1] == "Familjen Andersson", "gäst kan inte ange annat uppladdarnamn")
chid = q("SELECT id FROM challenges WHERE text='Bästa dansmovet'")[0][0]
h = html(req(p, f"/r/{gA[1]}/photos"))
ok("Fotoutmaningar" in h and "Bästa dansmovet" in h and f'value="{chid}"' in h, "fotoutmaningar visas på uppladdningssidan")
body, hd = multipart({"challenge": str(chid)}, [("photos", ("p.jpg", raw, "image/jpeg"))])
req(p, f"/r/{gA[1]}/photos", raw=body, headers=hd)
ok(q("SELECT challenge_id FROM photos ORDER BY id DESC LIMIT 1")[0][0] == chid, "fotoutmaning sparas med bilden")
body, hd = multipart({"challenge": "99999"}, [("photos", ("p.jpg", raw, "image/jpeg"))])
req(p, f"/r/{gA[1]}/photos", raw=body, headers=hd)
ok(q("SELECT challenge_id FROM photos ORDER BY id DESC LIMIT 1")[0][0] is None, "okänd utmaning ignoreras")
DB.execute("UPDATE photos SET hidden = 0"); DB.commit()
r = req(a, "/photos/bildspel"); h = html(r)
ok(r[0] == 200 and "data-slideshow" in h and "<svg" in h and 'class="top"' not in h, "bildspel: helskärmssida med QR för uppladdning")
sj = json.loads(req(a, "/photos/bildspel.json")[2])
hidden_files = {x[0] for x in q("SELECT file FROM photos WHERE hidden=1")}
ok(sj["photos"] and all(p["src"].startswith("/photos/img/") for p in sj["photos"])
   and not any(p["src"].rsplit("/", 1)[1] in hidden_files for p in sj["photos"]), "bildspel: bara synliga bilder")
ok(req(client(), "/photos/bildspel.json", follow=False)[0] == 303, "bildspel kräver inloggning")
ok(any(p_["caption"] == "Bästa dansmovet" for p_ in sj["photos"]), "bildspel: utmaningen följer med som bildtext")
ok("🎯 Bästa dansmovet" in html(req(a, "/photos")), "fotoutmaning syns i admin")

# gästbok
r = req(client(), f"/p/{ptok}/halsning", {"name": "Moster Berit", "greeting": "  Grattis <3  "})
ok("Tack för hälsningen" in html(r), "gästbok: hälsning via QR-sidan")
req(p, f"/r/{gA[1]}/halsning", {"name": "Någon annan", "greeting": "Vi älskar er!"})
gb = q("SELECT name, text, hidden FROM greetings ORDER BY id")
ok([tuple(x) for x in gb] == [("Moster Berit", "Grattis <3", 0), ("Familjen Andersson", "Vi älskar er!", 0)],
   "gästbok: sparas (gästportalen med gästens namn)")
ok("Skriv en hälsning först" in html(req(client(), f"/p/{ptok}/halsning", {"greeting": "   "}))
   and "högst 280" in html(req(client(), f"/p/{ptok}/halsning", {"greeting": "x" * 281})), "gästbok: tom och för lång nekas")
ok(req(client(), f"/p/{'y' * 24}/halsning", {"greeting": "hej"})[0] == 404, "gästbok: fel token 404")
sj = json.loads(req(a, "/photos/bildspel.json")[2])
ok({"name": "Moster Berit", "text": "Grattis <3"} in sj["greetings"], "gästbok: hälsningen visas i bildspelet")
gid1 = q("SELECT id FROM greetings ORDER BY id LIMIT 1")[0][0]
ok(req(a, f"/photos/halsning/{gid1}", {"action": "toggle"})[0] == 403, "gästbok: godkänna kräver CSRF")
req(a, f"/photos/halsning/{gid1}", {"csrf": c, "action": "toggle"})
sj = json.loads(req(a, "/photos/bildspel.json")[2])
ok(sj["greetings"] == [{"name": "Familjen Andersson", "text": "Vi älskar er!"}], "gästbok: dold hälsning syns inte i bildspelet")
ok("Grattis &lt;3" in html(req(a, "/photos")), "gästbok: escapas i adminvyn")
req(a, f"/photos/halsning/{gid1}", {"csrf": c, "action": "delete"})
ok(not q("SELECT 1 FROM greetings WHERE id=?", gid1), "gästbok: ta bort")
# tidskapsel
ok("Tidskapseln" in html(req(client(), f"/p/{ptok}")) and "/tidskapsel" in html(req(p, f"/r/{gA[1]}")), "tidskapsel: på bildsidan och som flik i gästportalen")
r = req(p, f"/r/{gA[1]}/tidskapsel", {"letter": "Kära ni,\nhoppas första året blev fint! <3"})
ok("Brevet ligger i tidskapseln" in html(r) and "lagt 1 brev" in html(r), "tidskapsel: brev från gästportalen")
req(client(), f"/p/{ptok}/tidskapsel", {"name": "Moster Berit", "letter": "Hemligt brev"})
ok(tuple(q("SELECT name, text FROM capsule ORDER BY id")[0]) == ("Familjen Andersson", "Kära ni,\nhoppas första året blev fint! <3")
   and q("SELECT COUNT(*) FROM capsule")[0][0] == 2, "tidskapsel: sparas med gästens namn, även via QR-sidan")
h = html(req(a, "/mail"))
ok("2 brev väntar" in h and "Hemligt brev" not in h and "hoppas första" not in h, "tidskapsel: brudparet ser bara antalet")
ok("högst 2000" in html(req(p, f"/r/{gA[1]}/tidskapsel", {"letter": "x" * 2001})), "tidskapsel: för långt brev nekas")
ok(req(client(), f"/p/{'z' * 24}/tidskapsel", {"letter": "hej"})[0] == 404, "tidskapsel: fel token 404")
for i in range(12): r = req(client(), f"/p/{ptok}/halsning", {"greeting": f"spam {i}"})
ok("För många hälsningar" in html(r), "gästbok: rate limit per IP")
ok(req(client(), f"/r/{gA[1]}/photos?ok=%C2%B2")[0] == 200 and req(client(), f"/p/{ptok}?ok=" + "9" * 5000)[0] == 200,
   "konstigt ?ok= ger ingen krasch")
s2 = html(req(a, "/settings"))
form = {"csrf": c, "couple_names": "Anna & Erik", "wedding_date": "2027-06-12", "wedding_time": "14:00", "venue": "Ulriksdals slott",
        "rsvp_deadline": "2027-04-01", "photos_enabled": "on", "gallery_public": "on", "photo_moderation": "on", "photo_quota_mb": "500", "capsule_enabled": "on",
        "invite_subject": "Inbjudan {brudpar} {__class__}", "invite_body": "Hej {namn}! {länk} {datum} {0.__class__}",
        "reminder_subject": "Påminnelse", "reminder_body": "Svara {länk}"}
req(a, "/settings", form)
ok(req(client(), f"/p/{ptok}/img/{f['file']}")[0] == 200, "galleri på → bild publik")
body, hd = multipart({}, [("photos", ("p.jpg", raw, "image/jpeg"))])
req(client(), f"/p/{ptok}", raw=body, headers=hd)
newest = q("SELECT file, hidden FROM photos ORDER BY id DESC LIMIT 1")[0]
ok(newest["hidden"] == 1 and req(client(), f"/p/{ptok}/img/{newest['file']}")[0] == 404, "granskning: ny bild dold tills godkänd")
r = req(a, "/photos/all.zip"); ok(r[0] == 200 and r[2][:2] == b"PK", "ladda ner alla som zip")
ok("<svg" in html(req(a, "/photos/cards?n=4")), "bordskort med QR")
big = b"x" * (130 * 1024 * 1024)
try:
    rq = urllib.request.Request(B + f"/p/{ptok}", data=big[:1], headers={"Content-Length": str(len(big)), "Content-Type": "multipart/form-data; boundary=x"})
    r = urllib.request.urlopen(rq); ok(False, "för stor uppladdning")
except urllib.error.HTTPError as e: ok(e.code == 413, "uppladdning över 120 MB → 413")
except Exception as e: ok(True, f"uppladdning över 120 MB avbryts ({type(e).__name__})")

# ---------------------------------------------------------------- e-post
r = req(a, "/mail"); h = html(r); ok("Bara nya (2)" in h, "utskickssida räknar gäster med e-post")
req(a, "/mail/test", {"csrf": c, "to": "test@example.se"})
r = req(a, "/mail/send", {"csrf": c, "kind": "invite", "scope": "new"}); ok("Kryssa i" in html(r), "utskick kräver bekräftelse")
req(a, "/mail/send", {"csrf": c, "kind": "invite", "scope": "new", "confirm": "on"})
time.sleep(2)
mail = read_mail()
ok(f"/r/{gA[1]}" in mail and f"/r/{gB[1]}" in mail, "inbjudan med personliga länkar skickad")
ok("__class__" in mail and "<class" not in mail, "mallar kan inte läsa interna objekt")
ok(q("SELECT COUNT(*) FROM guests WHERE invite_sent_at IS NOT NULL")[0][0] == 2, "invite_sent_at sparas")
open(S + "/mail.txt", "w").close()
req(a, "/mail/send", {"csrf": c, "kind": "reminder", "confirm": "on"}); time.sleep(1.5)
mail = read_mail()
ok(f"/r/{gB[1]}" in mail and f"/r/{gA[1]}" not in mail, "påminnelse bara till dem som inte svarat")
r = req(a, "/mail/test", {"csrf": c, "to": "x@example.se\r\nBcc: evil@example.se"}); ok(r[0] == 400, "header-injektion i mottagare nekas")

# ---------------------------------------------------------------- API (Hemmahub)
ok(req(client(), "/api/v1/countdown")[0] == 401, "API utan nyckel → 401")
ok(req(client(), "/api/v1/countdown", headers={"Authorization": "Bearer wp_" + "a" * 43})[0] == 401, "API med fel nyckel → 401")
r = req(a, "/api-keys", {"csrf": c, "name": "Hemmahub", "scope_countdown": "on"}); key = re.search(r'id="newkey" value="(wp_[^"]+)"', html(r)).group(1)
r = req(client(), "/api/v1/countdown", headers={"Authorization": f"Bearer {key}"}); j = json.loads(r[2])
ok(r[0] == 200 and j["date"] == "2027-06-12" and j["days_left"] > 0 and j["status"] == "upcoming" and "stats" not in j, f"nedräkning: {j['label']}")
ok(j["seconds_left"] and j["couple"] == "Anna & Erik", "sekunder kvar + brudpar")
ok(req(client(), "/api/v1/countdown", headers={"X-API-Key": key})[0] == 200, "X-API-Key-header fungerar")
ok(req(client(), f"/api/v1/countdown?key={key}")[0] == 401, "nyckel i URL accepteras inte")
r = req(client(), "/api/v1/countdown", headers={"X-API-Key": key, "Origin": "http://hemmahub.lan:3000"})
ok(r[1].get("Access-Control-Allow-Origin") == "http://hemmahub.lan:3000", "CORS för Hemmahub")
r = req(client(), "/api/v1/countdown", headers={"X-API-Key": key, "Origin": "https://evil.example"})
ok(r[1].get("Access-Control-Allow-Origin") is None, "CORS nekas för okänd origin")
r = req(client(), "/api/v1/countdown", method="OPTIONS", headers={"Origin": "http://hemmahub.lan:3000"}); ok(r[0] == 204, "CORS preflight")
r = req(a, "/api-keys", {"csrf": c, "name": "Stats", "scope_countdown": "on", "scope_stats": "on"}); key2 = re.search(r'id="newkey" value="(wp_[^"]+)"', html(r)).group(1)
j = json.loads(req(client(), "/api/v1/countdown", headers={"X-API-Key": key2})[2])
ok(j["stats"]["guests"]["attending"] == 3 and "Andersson" not in json.dumps(j), "statistik utan persondata")
ok("tasks" not in j, "att göra-listan kräver egen behörighet")
r = req(a, "/api-keys", {"csrf": c, "name": "Lista", "scope_countdown": "on", "scope_tasks": "on"}); key3 = re.search(r'id="newkey" value="(wp_[^"]+)"', html(r)).group(1)
j = json.loads(req(client(), "/api/v1/countdown", headers={"X-API-Key": key3})[2])
open_n = q("SELECT COUNT(*) FROM tasks WHERE done=0")[0][0]
ok(isinstance(j.get("tasks"), list) and len(j["tasks"]) == min(open_n, 50) and "stats" not in j, "att göra-listan med bara tasks-behörighet")
ok(all(set(t) == {"id", "title", "period", "due_date", "assignee", "overdue"} for t in j["tasks"]), "att göra-listan har rätt fält")
ok(key not in html(req(a, "/api-keys")), "nyckeln visas bara en gång")
ok(q("SELECT key_hash FROM api_keys LIMIT 1")[0][0] != key, "nyckeln lagras hashad")
kid = q("SELECT id FROM api_keys WHERE name='Hemmahub'")[0][0]
req(a, "/api-keys", {"csrf": c, "action": "delete", "id": kid})
ok(req(client(), "/api/v1/countdown", headers={"X-API-Key": key})[0] == 401, "återkallad nyckel → 401")

# ---------------------------------------------------------------- roller
req(a, "/users", {"csrf": c, "username": "toast", "password": "Toastmaster-2027!", "role": "viewer"})
v = client(); r = req(v, "/login", {"username": "toast", "password": "Toastmaster-2027!"}); c2 = csrf(html(r))
req(v, "/account/password", {"csrf": c2, "current": "Toastmaster-2027!", "new": "En-helt-annan-fras-99", "new2": "En-helt-annan-fras-99"})
ok(req(v, "/m/speeches")[0] == 200, "läsare (toastmaster) ser talarlistan")
ok(req(v, "/dagen")[0] == 200 and req(client(), "/dagen", follow=False)[0] == 303, "läsare ser dagen, utloggad gör det inte")
req(a, "/m/speeches/new", {"csrf": c, "speaker": "Morbror Sten", "part": "Under varmrätten", "order_no": "1", "minutes": "4", "status": "Bekräftad"})
sid = q("SELECT id FROM speeches WHERE speaker='Morbror Sten'")[0][0]
ok("data-timer-start=\"4\"" in html(req(v, "/dagen")), "dagen: timer per tal")
req(v, f"/dagen/tal/{sid}", {"csrf": c2})
ok(q("SELECT status FROM speeches WHERE id=?", sid)[0][0] == "Hållen", "dagen: toastmastern (läsare) bockar av ett tal")
ok("1 av" in html(req(v, "/dagen")) and "↺ Ångra" in html(req(v, "/dagen")), "dagen: hållna tal räknas och kan ångras")
req(v, f"/dagen/tal/{sid}", {"csrf": c2})
ok(q("SELECT status FROM speeches WHERE id=?", sid)[0][0] == "Bekräftad", "dagen: ångra hållet tal")
ok(req(v, f"/dagen/tal/{sid}", {"csrf": "fel"})[0] == 403 and req(client(), f"/dagen/tal/{sid}", {"csrf": c2}, follow=False)[0] == 303,
   "dagen: avbockning kräver CSRF och inloggning")
DB.execute("UPDATE speeches SET status='Struken' WHERE id=?", (sid,)); DB.commit()
ok(req(v, f"/dagen/tal/{sid}", {"csrf": c2})[0] == 404, "dagen: strukna tal kan inte bockas av")
h = html(req(v, "/dagen"))
ok('rel="manifest"' in h and "apple-touch-icon" in h, "hemskärm: manifest och ikon länkas")
r = req(client(), "/static/manifest.json")
ok(r[0] == 200 and json.loads(r[2])["start_url"] == "/dagen", "hemskärm: manifestet öppnar Dagen")
ok(req(v, "/api-keys")[0] == 403 and req(v, "/mail/send", {"csrf": c2, "kind": "invite", "confirm": "on"})[0] == 403, "läsare når inte API-nycklar/utskick")
ok(req(v, "/seating/assign", raw=b"{}", headers={"Content-Type": "application/json", "X-CSRF-Token": c2})[0] == 403, "läsare kan inte flytta gäster")
ok('draggable' not in html(req(v, "/seating")), "läsare ser placering utan dra-funktion")
ok(req(v, "/seating/forslag", {"csrf": c2})[0] == 403 and req(a, "/seating/forslag", {"csrf": "x"})[0] == 403,
   "placeringsförslag kräver skrivbehörighet och CSRF")
before = q("SELECT id, table_id FROM guests WHERE table_id IS NOT NULL")
r = req(a, "/seating/forslag", {"csrf": c})
ok(r[0] == 200 and "hushåll placerades" in html(r) and all(q("SELECT table_id FROM guests WHERE id=?", g)[0][0] == t for g, t in before),
   "placeringsförslag: redan placerade flyttas inte")
ok(req(a, "/seating?placerade=" + "9" * 5000)[0] == 200, "placering: konstiga parametrar ger ingen krasch")
ok(req(v, f"/m/guests/{gA[0]}/people", {"csrf": c2, "name_1": "X", "coming_1": "on"})[0] == 403, "läsare kan inte ändra personer")
ok(req(v, f"/m/questions/{q_ride}", {"csrf": c2, "label": "x", "kind": "text"})[0] == 403, "OSA-frågor: läsare kan inte ändra frågorna")
ok(req(v, "/rapport/svar")[0] == 200, "läsare ser svaren på OSA-frågorna")
_gid = q("SELECT id FROM greetings ORDER BY id DESC LIMIT 1")[0][0]
ok(req(v, f"/photos/halsning/{_gid}", {"csrf": c2, "action": "delete"})[0] == 403, "läsare kan inte ta bort hälsningar")
h = html(req(v, f"/m/guests/{gA[0]}"))
ok("rsvplink" not in h and gA[1] not in h and "Anders" in h, "läsare ser gästen men inte OSA-länken")
ok(gA[1] not in req(v, "/m/guests/export.csv")[2].decode("utf-8-sig"), "läsare får inte OSA-länkar i CSV-exporten")
ok(gA[1] in req(a, "/m/guests/export.csv")[2].decode("utf-8-sig"), "redigerare får OSA-länkar i CSV-exporten")
ok(all(req(v, u)[0] == 403 for u in ("/m/guests/qr", "/m/guests/qr.zip", f"/m/guests/{gA[0]}/qr.svg")),
   "läsare når inte OSA-kort och QR-koder")

# ---------------------------------------------------------------- mobilapparna /tm och /plan + rollen toastmaster
req(a, "/users", {"csrf": c, "username": "tmaster", "password": "Mikrofon-och-Glas-1", "role": "toastmaster"})
t = client(); r = req(t, "/login", {"username": "tmaster", "password": "Mikrofon-och-Glas-1"}); c3 = csrf(html(r))
req(t, "/account/password", {"csrf": c3, "current": "Mikrofon-och-Glas-1", "new": "Talare-Skål-Tårta-77", "new2": "Talare-Skål-Tårta-77"})
r = req(client(), "/tm/tal", follow=False)
ok(r[0] == 303 and r[1]["location"] == "/login?next=/tm/tal", "appar: utloggad skickas till inloggning med väg tillbaka")
r = req(client(), "/login?next=/tm/tal", {"username": "tmaster", "password": "Talare-Skål-Tårta-77", "next": "/tm/tal"}, follow=False)
ok(r[0] == 303 and r[1]["location"] == "/tm/tal", "appar: inloggning går tillbaka till appen")
r = req(client(), "/login", {"username": "tmaster", "password": "Talare-Skål-Tårta-77", "next": "https://evil.example/"}, follow=False)
ok(r[0] == 303 and r[1]["location"] == "/", "appar: next till annan sajt ignoreras")
h = html(req(t, "/tm"))
ok("manifest-tm.json" in h and "icon-tm-180.png" in h and "apple-mobile-web-app-capable" in h, "toastmasterappen: egen hemskärmsikon och manifest")
m = json.loads(req(client(), "/static/manifest-tm.json")[2]); m2 = json.loads(req(client(), "/static/manifest-plan.json")[2])
ok(m["start_url"] == "/tm" and m["scope"] == "/tm" and m2["start_url"] == "/plan", "manifesten öppnar rätt app")
ok(req(client(), m["icons"][0]["src"])[0] == 200 and req(client(), m2["icons"][1]["src"])[0] == 200, "appikonerna finns")
req(t, "/tm/tal/ny", {"csrf": c3, "speaker": "Kusin <Vera>", "part": "Under förrätten", "order_no": "5", "minutes": "3", "status": "Bekräftad"})
vera = q("SELECT id FROM speeches WHERE speaker='Kusin <Vera>'")
ok(bool(vera), "toastmaster lägger till tal i appen"); vera = vera[0][0]
req(t, "/tm/tal/ny", {"csrf": c3, "speaker": "Moster Ulla", "part": "Under förrätten", "order_no": "6", "minutes": "4", "status": "Bekräftad"})
ulla = q("SELECT id FROM speeches WHERE speaker='Moster Ulla'")[0][0]
h = html(req(t, "/tm/tal"))
ok("Kusin &lt;Vera&gt;" in h and "<Vera>" not in h and 'data-timer-start="3"' in h, "taltlistan: escapas och har timer")
req(t, f"/tm/tal/{ulla}/flytta", {"csrf": c3, "riktning": "upp"})
o = dict(q("SELECT id, order_no FROM speeches WHERE id IN (?, ?)", vera, ulla))
ok(o[ulla] < o[vera], "tal flyttas upp i ordningen")
ok(req(t, f"/tm/tal/{ulla}/flytta", {"csrf": "fel", "riktning": "ner"})[0] == 403, "flytta tal kräver CSRF")
r = req(t, f"/tm/tal/{vera}", {"csrf": c3, "speaker": "Kusin Vera", "part": "Under förrätten", "order_no": "5", "minutes": "abc", "status": "Bekräftad"})
ok(r[0] == 400, "tal: felaktigt formulär ger 400")
req(t, f"/tm/tal/{vera}", {"csrf": c3, "speaker": "Kusin Vera", "part": "Under förrätten", "order_no": "5", "minutes": "6", "status": "Bekräftad"})
ok(q("SELECT speaker, minutes FROM speeches WHERE id=?", vera)[0][:] == ("Kusin Vera", 6), "toastmaster ändrar ett tal")
h = html(req(t, "/tm"))
ok("Nästa tal" in h and "✓ Hållet" in h, "Nu-fliken visar nästa tal")
r = req(t, f"/tm/tal/{ulla}/hallen?fran=nu", {"csrf": c3}, follow=False)
ok(r[0] == 303 and r[1]["location"] == "/tm" and q("SELECT status FROM speeches WHERE id=?", ulla)[0][0] == "Hållen", "tal bockas av från Nu-fliken")
req(v, f"/tm/tal/{ulla}/hallen", {"csrf": c2})
ok(q("SELECT status FROM speeches WHERE id=?", ulla)[0][0] == "Bekräftad", "läsare får också bocka av tal i appen")
ok(req(v, f"/tm/tal/{ulla}", {"csrf": c2, "speaker": "x", "part": "Under förrätten", "minutes": "1", "status": "Bekräftad"})[0] == 403
   and req(v, f"/tm/tal/{ulla}/flytta", {"csrf": c2, "riktning": "upp"})[0] == 403, "läsare kan inte ändra eller flytta tal")
h = html(req(v, "/tm/tal")); ok("/flytta" not in h and "+ Nytt" not in h, "läsare ser inga ändringsknappar")
# programmet
_tl = [dict(x) for x in q("SELECT * FROM timeline")]
DB.execute("DELETE FROM timeline"); DB.executemany("INSERT INTO timeline (time, title) VALUES (?, ?)",
    [("15:00", "Vigsel"), ("18:00", "Middag"), ("23:50", "Tårta"), ("01:00", "Nattmacka")]); DB.commit()
mid = q("SELECT id FROM timeline WHERE title='Middag'")[0][0]
h = html(req(t, "/tm/program"))
ok(h.index("Tårta") < h.index("Nattmacka") and "/tm/program/forskjut" in h, "programmet i appen: natten sist + flytta-knappar")
req(t, "/tm/program/forskjut", {"csrf": c3, "fran": mid, "minuter": "15"})
ok(dict(q("SELECT title, time FROM timeline")) == {"Vigsel": "15:00", "Middag": "18:15", "Tårta": "00:05", "Nattmacka": "01:15"},
   "skjut programmet: punkten och allt efter flyttas, även över midnatt")
req(t, "/tm/program/forskjut", {"csrf": c3, "fran": mid, "minuter": "-15"})
ok(q("SELECT time FROM timeline WHERE title='Tårta'")[0][0] == "23:50", "och tillbaka igen")
ok(req(t, "/tm/program/forskjut", {"csrf": c3, "fran": mid, "minuter": "999"})[0] == 400
   and req(t, "/tm/program/forskjut", {"csrf": c3, "fran": "x", "minuter": "5"})[0] == 400
   and req(t, "/tm/program/forskjut", {"csrf": c3, "fran": "999999", "minuter": "5"})[0] == 404, "skjut programmet: rimliga värden krävs")
ok(req(v, "/tm/program/forskjut", {"csrf": c2, "fran": mid, "minuter": "5"})[0] == 403
   and req(t, "/tm/program/forskjut", {"csrf": "fel", "fran": mid, "minuter": "5"})[0] == 403, "skjut programmet: roll och CSRF")
req(t, "/plan/program/ny", {"csrf": c3, "time": "21:00", "title": "Första dansen"})
dans = q("SELECT id FROM timeline WHERE title='Första dansen'")
ok(bool(dans), "ny programpunkt från appen"); dans = dans[0][0]
req(t, f"/plan/program/{dans}", {"csrf": c3, "time": "21:30", "title": "Första dansen"})
ok(q("SELECT time FROM timeline WHERE id=?", dans)[0][0] == "21:30", "programpunkt ändras i appen")
req(t, f"/plan/program/{dans}/ta-bort", {"csrf": c3})
ok(not q("SELECT id FROM timeline WHERE id=?", dans), "programpunkt tas bort i appen")
DB.execute("DELETE FROM timeline")  # tillbaka till körschemat som senare tester räknar med
for x in _tl: DB.execute(f"INSERT INTO timeline ({', '.join(x)}) VALUES ({', '.join('?' * len(x))})", list(x.values()))
DB.commit()
# toastmastern når inget annat
ok(req(t, "/m/guests/new", {"csrf": c3, "name": "X"})[0] == 403 and req(t, "/m/tasks/new", {"csrf": c3, "title": "X"})[0] == 403,
   "toastmaster kan inte ändra gäster eller att göra")
h = html(req(t, f"/m/guests/{gA[0]}"))
ok("rsvplink" not in h and gA[1] not in h, "toastmaster ser inte OSA-länkar")
ok(all(req(t, u)[0] == 403 for u in ("/m/guests/qr", "/users", "/backup")), "toastmaster når inte QR, användare eller kopior")
ok(req(t, "/m/speeches/new", {"csrf": c3, "speaker": "Via listan", "part": "Under förrätten", "minutes": "2", "status": "Bekräftad"})[0] == 200
   and bool(q("SELECT id FROM speeches WHERE speaker='Via listan'")), "toastmaster kan ändra tal även i vanliga listan")
# planeringsappen
r = req(t, "/plan/uppgift/ny", {"csrf": c3, "title": "Hack"}); ok(r[0] == 403, "toastmaster kan inte lägga till uppgifter")
h = html(req(t, "/plan")); ok("/plan/uppgift/ny" not in h and "manifest-plan.json" in h, "planeringsappen: läsläge för toastmaster")
req(a, "/plan/uppgift/ny", {"csrf": c, "title": "Köp <ringkuddar>", "due_date": "2026-01-01"})
tid = q("SELECT id FROM tasks WHERE title='Köp <ringkuddar>'")[0][0]
h = html(req(a, "/plan"))
ok("Köp &lt;ringkuddar&gt;" in h and "Försenade" in h, "planering: snabbtillägg, escapas, försenade grupperas")
req(a, "/plan/uppgift/ny", {"csrf": c, "title": "Utan datum", "period": "1–3 mån före"})
ok(bool(q("SELECT due_date FROM tasks WHERE title='Utan datum'")[0][0]), "planering: deadline räknas ut när datum saknas")
req(a, f"/plan/uppgift/{tid}/klar", {"csrf": c})
ok(q("SELECT done FROM tasks WHERE id=?", tid)[0][0] == 1 and "Köp &lt;ringkuddar&gt;" in html(req(a, "/plan/klart")), "planering: bocka av")
r = req(a, f"/plan/uppgift/{tid}/klar?fran=klart", {"csrf": c}, follow=False)
ok(r[1]["location"].startswith("/plan/klart") and q("SELECT done FROM tasks WHERE id=?", tid)[0][0] == 0, "planering: ångra från Klart")
req(a, f"/plan/uppgift/{tid}", {"csrf": c, "title": "Köp ringkuddar", "period": "1–3 mån före", "due_date": "2027-05-01", "assignee": "Louise"})
ok(tuple(q("SELECT title, assignee FROM tasks WHERE id=?", tid)[0]) == ("Köp ringkuddar", "Louise"), "planering: ändra uppgift")
ok(req(a, f"/plan/uppgift/{tid}/klar", {"csrf": "fel"})[0] == 403 and req(v, f"/plan/uppgift/{tid}/klar", {"csrf": c2})[0] == 403,
   "planering: avbockning kräver CSRF och skrivbehörighet")
ok(req(a, "/plan/uppgift/ny", {"csrf": c, "title": ""})[0] == 400, "planering: tom uppgift nekas")
req(a, f"/plan/uppgift/{tid}/ta-bort", {"csrf": c})
ok(not q("SELECT id FROM tasks WHERE id=?", tid), "planering: ta bort uppgift")
ok(req(a, "/plan/uppgift/999999")[0] == 404 and req(a, "/tm/tal/999999")[0] == 404, "appar: okända poster ger 404")

# ---------------------------------------------------------------- säkerhetskopior
ok(req(v, "/backup")[0] == 403 and req(v, "/backup/now.db")[0] == 403, "läsare når inte säkerhetskopior")
h = html(req(a, "/backup")); m = re.search(r'href="/backup/files/(wedding-[0-9-]+\.db)"', h)
ok(m is not None, "daglig kopia skapas automatiskt vid start")
r = req(a, f"/backup/files/{m.group(1)}") if m else (0, {}, b"")
ok(r[0] == 200 and r[2][:16] == b"SQLite format 3\x00", "automatisk kopia går att ladda ner")
r = req(a, "/backup/now.db")
ok(r[0] == 200 and r[2][:16] == b"SQLite format 3\x00", "färsk kopia laddas ner")
import tempfile as _tf
_bk = _tf.NamedTemporaryFile(suffix=".db", delete=False); _bk.write(r[2]); _bk.close()
_bc = sqlite3.connect(_bk.name)
ok(_bc.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0 and _bc.execute("SELECT COUNT(*) FROM guests").fetchone()[0] > 0,
   "kopian innehåller data men inga inloggningssessioner")
_bc.close()
ok(req(a, "/backup/files/..%2Fwedding.db")[0] == 404 and req(a, "/backup/files/wedding.db")[0] == 404, "bara backupfiler kan hämtas")

# ---------------------------------------------------------------- 2FA med QR + headers
r = req(a, "/account/totp/start", {"csrf": c}); h = html(r)
ok("<svg" in h and "otpauth" not in h.split("<details")[0][:0] , "2FA-QR visas")
sec = re.search(r'<code class="secret">([A-Z2-7 ]+)</code>', h).group(1).replace(" ", "")
r = req(a, "/account/totp/confirm", {"csrf": c, "code": totp_now(sec)}); ok("aktiverad" in html(r), "2FA aktiveras via QR-nyckel")
ok(req(a, "/account/totp/start", {"csrf": c})[0] == 400 and req(a, "/account/totp/confirm", {"csrf": c, "code": "123456"})[0] == 400,
   "aktiv 2FA kan inte bytas utan att först stängas av")
r = req(client(), "/login", {"username": "testadmin", "password": NEW, "code": "１２３４５６"})
ok(r[0] == 401, "TOTP-kod med helbreddssiffror → 401, inte 500")
ok(req(a, "/m/guests/new", {"csrf": "å", "name": "x"})[0] == 403, "CSRF-token med icke-ASCII → 403, inte 500")
hd = req(client(), "/login")[1]
ok("'unsafe-inline'" not in hd["Content-Security-Policy"], "CSP utan unsafe-inline")
# ---------------------------------------------------------------- "Kommer" utan antal
req(a, "/m/guests/new", {"csrf": c, "name": "Familjen Ek", "invited_count": 4, "rsvp": "yes", "attending": "", "side": "Gemensam"})
ok(q("SELECT attending FROM guests WHERE name='Familjen Ek'")[0][0] == 4, "Kommer utan antal → alla 4 i hushållet")
ek = q("SELECT id FROM guests WHERE name='Familjen Ek'")[0][0]
req(a, f"/m/guests/{ek}", {"csrf": c, "name": "Familjen Ek", "invited_count": 4, "rsvp": "yes", "attending": "3", "side": "Gemensam"})
ok(q("SELECT attending FROM guests WHERE id=?", ek)[0][0] == 3, "angivet antal respekteras")
r = req(a, f"/m/guests/{ek}", {"csrf": c, "name": "Familjen Ek", "invited_count": 4, "rsvp": "yes", "attending": "5", "side": "Gemensam"})
ok(r[0] == 400 and q("SELECT attending FROM guests WHERE id=?", ek)[0][0] == 3, "fler som kommer än inbjudna nekas")
req(a, f"/m/guests/{ek}", {"csrf": c, "name": "Familjen Ek", "invited_count": 4, "rsvp": "no", "attending": "3", "side": "Gemensam"})
ok(q("SELECT attending FROM guests WHERE id=?", ek)[0][0] == 0, "Kommer inte → 0")

# ---------------------------------------------------------------- OSA via QR / kod
g = q("SELECT id, rsvp_token, rsvp_code FROM guests WHERE name='Bertil'")[0]
ok(g["rsvp_code"] and len(g["rsvp_code"]) == 10, "gäst har OSA-kod")
pub = client()
r = req(pub, f"/o/{g['rsvp_code']}", follow=False)
ok(r[0] == 303 and r[1]["location"] == f"/r/{g['rsvp_token']}", "QR-länk /o/KOD → gästportalen")
fmt = (g["rsvp_code"][:5] + "-" + g["rsvp_code"][5:]).lower()
r = req(pub, "/osa", {"code": f"  {fmt} "}, follow=False)
ok(r[0] == 303 and r[1]["location"] == f"/r/{g['rsvp_token']}", "manuell kod (gemener, bindestreck) fungerar")
ok("Er kod" in html(req(pub, "/osa")), "/osa visar kodformulär")
r = req(pub, "/osa", {"code": "AAAAA-AAAAA"}); ok(r[0] == 400 and "hittade ingen" in html(r), "fel kod → 400")
r = req(a, "/m/guests/qr"); h = html(r)
n_guests = q("SELECT COUNT(*) FROM guests")[0][0]
ok(r[0] == 200 and h.count('class="osa-card"') == n_guests and h.count("<svg") >= n_guests, f"utskriftsark med {n_guests} OSA-kort")
ok(fmt.upper() in h, "koden står på kortet")
r = req(a, "/m/guests/qr?scope=pending"); ok(html(r).count('class="osa-card"') == q("SELECT COUNT(*) FROM guests WHERE rsvp='pending'")[0][0], "filter: bara de som inte svarat")
req(a, "/m/guests/qr", {"csrf": c, "osa_card_footer": "Svara senast {osa_senast}"})
ok("Svara senast 1 april 2027" in html(req(a, "/m/guests/qr")), "standardtext under koden med datum")
r = req(a, "/m/guests/qr", {"csrf": c, "osa_card_footer": "Svara senast {osa_senast}\nVi ses, {namn}! ({antal} pers) <script>x</script>"})
h = html(r)
ok(r[0] == 200 and "Texten är sparad" in h and "Vi ses, Bertil! (1 pers)" in h and "Svara senast 1 april 2027" in h, "egen text med platshållare per hushåll")
ok("<script>x</script>" not in h and "&lt;script&gt;" in h, "text under koden escapas")
r = req(a, "/m/guests/qr", {"csrf": c, "osa_card_footer": "x" * 301}); ok(r[0] == 400 and "högst 300" in html(r), "för lång text nekas")
ok(req(a, "/m/guests/qr", {"csrf": "fel", "osa_card_footer": "hack"})[0] == 403, "texten kräver CSRF-token")
ok(req(v, "/m/guests/qr", {"csrf": c2, "osa_card_footer": "hack"})[0] == 403, "läsare kan inte ändra texten")
ok(req(v, "/m/guests/qr")[0] == 403, "läsare ser inte OSA-korten (koderna ger tillgång till gästernas svar)")
req(a, "/m/guests/qr", {"csrf": c, "osa_card_footer": ""})
ok(html(req(a, "/m/guests/qr")).count("osa-footer\" data-namn") == 0 or 'hidden>' in html(req(a, "/m/guests/qr")), "tom text → ingen rad på korten")
ok(q("SELECT value FROM settings WHERE key='osa_card_footer'")[0][0] == "", "tom text sparas")
req(a, "/m/guests/qr", {"csrf": c, "osa_card_footer": "Svara senast {osa_senast}"})
r = req(a, "/m/guests/qr.zip")
import zipfile as _zf
z = _zf.ZipFile(io.BytesIO(r[2])); names = z.namelist()
ok(r[0] == 200 and "gaster.csv" in names and sum(n.startswith("png/") for n in names) == n_guests and sum(n.startswith("svg/") for n in names) == n_guests, "zip med PNG, SVG och CSV")
ok(z.read([n for n in names if n.startswith("png/")][0])[:8] == b"\x89PNG\r\n\x1a\n", "PNG är giltig")
ok(fmt.upper() in z.read("gaster.csv").decode("utf-8-sig"), "CSV för koppling innehåller koden")
r = req(a, f"/m/guests/{g['id']}/qr.png"); ok(r[0] == 200 and r[1]["Content-Type"] == "image/png", "QR per gäst som PNG")
ok(req(a, f"/m/guests/{g['id']}/qr.exe")[0] == 404, "okänt format 404")
req(a, f"/m/guests/{g['id']}", {"csrf": c, "name": "Bertil", "invited_count": 1, "rsvp": "pending", "side": "Gemensam",
     "email": "b@example.se", "street": "=Storgatan 1", "postcode": "123 45", "city": "Ort"})
z = _zf.ZipFile(io.BytesIO(req(a, "/m/guests/qr.zip")[2]))
gcsv = z.read("gaster.csv").decode("utf-8-sig")
ok("Gatuadress;Postnummer;Ort" in gcsv and "'=Storgatan 1;123 45;Ort" in gcsv, "postadress i CSV för dokumentkoppling (formelskyddad)")
gL = add_guest("Łukasz & Zoë")
r = req(a, f"/m/guests/{gL[0]}/qr.svg")
ok(r[0] == 200 and "Lukasz_Zoe" in r[1]["Content-Disposition"], "QR-filnamn för namn utanför latin-1")
ok("OSA-kod" in req(a, "/m/guests/export.csv")[2].decode("utf-8-sig"), "CSV-export har OSA-kod")
ok(fmt.upper() in html(req(a, f"/m/guests/{g['id']}")), "gästsidan visar kod och QR")
ok(req(client(), "/m/guests/qr", follow=False)[0] == 303 and req(client(), "/m/guests/qr.zip", follow=False)[0] == 303, "OSA-kort kräver inloggning")
req(a, f"/m/guests/{g['id']}/newlink", {"csrf": c})
ok(req(client(), f"/o/{g['rsvp_code']}", follow=False)[0] == 404, "ny länk → gammal QR-kod slutar fungera")
for i in range(16): r = req(pub, "/osa", {"code": "BBBBB-BBBBC"})
ok(r[0] == 429 and "många" in html(r), "gissning av koder stoppas (rate limit)")

# ---------------------------------------------------------------- tackkort
h = html(req(a, "/tack")); ok(f'id="g{gA[0]}"' in h and "0 av" in h, "tackkort: de som kommer listas")
req(a, f"/tack/{gA[0]}", {"csrf": c, "gift_received": "<b>Vas</b>", "thanks_sent": "on"})
ok(tuple(q("SELECT gift_received, thanks_sent FROM guests WHERE id=?", gA[0])[0]) == ("<b>Vas</b>", 1), "tackkort: present och avbockning sparas")
h = html(req(a, "/tack")); ok("&lt;b&gt;Vas" in h and "<b>Vas" not in h and "1 av" in h, "tackkort: escapas och räknas")
ok(f'id="g{gA[0]}"' not in html(req(a, "/tack?f=kvar")), "tackkort: filtret visar bara de som är kvar")
ok(req(a, f"/tack/{gA[0]}", {"gift_received": "x"})[0] == 403 and req(v, f"/tack/{gA[0]}", {"csrf": c2, "gift_received": "x"})[0] == 403,
   "tackkort kräver CSRF och skrivbehörighet")
ok(q("SELECT gift_received FROM guests WHERE id=?", gA[0])[0][0] == "<b>Vas</b>", "tackkort oförändrat efter nekade försök")

# ---------------------------------------------------------------- leverantör → budget
VEND = {"csrf": c, "name": "Blomsterbutiken", "category": "Blommor & dekor", "status": "Förfrågan", "price": "8 000"}
req(a, "/m/vendors/new", VEND)
vid = q("SELECT id FROM vendors WHERE name='Blomsterbutiken'")[0][0]
ok(q("SELECT COUNT(*) FROM budget WHERE vendor_id=?", vid)[0][0] == 0, "leverantör som inte är bokad ger ingen budgetpost")
req(a, f"/m/vendors/{vid}", {**VEND, "status": "Bokad"})
b = q("SELECT item, category, estimated FROM budget WHERE vendor_id=?", vid)
ok(len(b) == 1 and tuple(b[0]) == ("Blomsterbutiken", "Blommor & dekor", 8000), "bokad leverantör → budgetpost med priset")
bid = q("SELECT id FROM budget WHERE vendor_id=?", vid)[0][0]
DB.execute("UPDATE budget SET actual = 7500, paid = 1 WHERE id = ?", (bid,)); DB.commit()
req(a, f"/m/vendors/{vid}", {**VEND, "status": "Bokad", "price": "9500"})
b = q("SELECT estimated, actual, paid FROM budget WHERE vendor_id=?", vid)
ok(len(b) == 1 and tuple(b[0]) == (9500, 7500, 1), "nytt pris uppdaterar budgeterat men rör inte faktiskt/betalt")
ok(f'href="/m/budget/{bid}"' in html(req(a, f"/m/vendors/{vid}")), "leverantören länkar till budgetposten")
req(a, f"/m/vendors/{vid}/delete", {"csrf": c})
ok(q("SELECT vendor_id FROM budget WHERE id=?", bid)[0][0] is None, "borttagen leverantör → budgetposten finns kvar utan koppling")

# ---------------------------------------------------------------- trycksaker
h = html(req(a, "/kort"))
ok(all(t in h for t in ("Save the date", "Inbjudan", "Tackkort", "Meny", "Program", "Välkomstskylt")) and "Anna &amp; Erik Exempel" in h,
   "trycksaker: förslagen finns och förhandsvisas med påhittad gäst")
cid = {r[0]: r[1] for r in q("SELECT kind, id FROM cards")}
inv = cid["invite"]
CARD = {"csrf": c, "title": "Inbjudan", "design": "modern", "color": "bla", "size": "a5", "audience": "all", "show_qr": "on",
        "eyebrow": "Välkommen", "heading": "<b>{namn}</b>", "body": "Vi gifter oss {datum}!", "footer": "OSA med koden {kod}"}
r = req(a, f"/kort/{inv}", CARD)
ok(r[0] == 200 and "Sparat" in html(r) and tuple(q("SELECT design, color, heading FROM cards WHERE id=?", inv)[0]) == ("modern", "bla", "<b>{namn}</b>"),
   "trycksaker: design, färg och text sparas")
ok(req(a, f"/kort/{inv}", {**CARD, "design": "<script>"})[0] == 400 and req(a, f"/kort/{inv}", {**CARD, "body": "x" * 1501})[0] == 400,
   "trycksaker: ogiltig design och för lång text nekas")
ok(req(a, f"/kort/{inv}", {**CARD, "csrf": "fel"})[0] == 403 and req(v, f"/kort/{inv}", {**CARD, "csrf": c2})[0] == 403,
   "trycksaker: kräver CSRF och skrivbehörighet")
h = html(req(a, f"/kort/{inv}/skriv-ut"))
n_households = q("SELECT COUNT(*) FROM guests")[0][0]
codes = [format_code(x[0]) for x in q("SELECT rsvp_code FROM guests")]
ok(h.count('class="pcard ') == n_households and all(k in h for k in codes) and h.count("<svg") >= n_households,
   "trycksaker: personlig inbjudan – ett kort per hushåll med egen kod och QR")
ok("&lt;b&gt;Bertil&lt;/b&gt;" in h and "<b>Bertil" not in h, "trycksaker: texter och namn escapas")
h = html(req(v, f"/kort/{inv}"))
ok(req(v, f"/kort/{inv}")[0] == 200 and not any(k in h for k in codes), "trycksaker: läsare ser förhandsvisning utan riktiga koder")
ok(req(v, f"/kort/{inv}/skriv-ut")[0] == 403, "trycksaker: läsare kan inte skriva ut kort med gästernas QR-koder")
ok(req(v, f"/kort/{cid['menu']}/skriv-ut")[0] == 200, "trycksaker: läsare kan skriva ut menyn")
h = html(req(a, f"/kort/{cid['thanks']}/skriv-ut"))
ok(h.count('class="pcard ') == q("SELECT COUNT(*) FROM guests WHERE rsvp='yes'")[0][0] and "och för &lt;b&gt;Vas" in h,
   "trycksaker: tackkort till dem som kom, med presenten i texten")
ok("Vigsel i parken" in html(req(a, f"/kort/{cid['program']}/skriv-ut")), "trycksaker: {program} fylls med körschemat")
ok(html(req(a, f"/kort/{cid['menu']}/skriv-ut?antal=3")).count('class="pcard ') == 3
   and html(req(a, f"/kort/{cid['menu']}/skriv-ut?antal=999")).count('class="pcard ') == 1, "trycksaker: antal kopior, med gräns")
r = req(a, "/kort/ny", {"csrf": c, "kind": "save"})
new_id = q("SELECT MAX(id) FROM cards")[0][0]
ok(r[0] == 200 and q("SELECT kind FROM cards WHERE id=?", new_id)[0][0] == "save", "trycksaker: ny trycksak från förslag")
ok(req(a, "/kort/ny", {"csrf": c, "kind": "hack"})[0] == 400, "trycksaker: okänt förslag nekas")
req(a, f"/kort/{new_id}/delete", {"csrf": c})
ok(not q("SELECT 1 FROM cards WHERE id=?", new_id), "trycksaker: ta bort")
ok(req(client(), "/kort", follow=False)[0] == 303, "trycksaker kräver inloggning")
h = html(req(a, f"/kort/{inv}"))
ok(h.count("data-pick-design=") == 11 and "Färgat papper: kraft" in h, "trycksaker: designväljare med 11 designer och pappersval")
req(a, f"/kort/{inv}", {**CARD, "design": "krans", "paper": "kraft"})
ok(tuple(q("SELECT design, paper FROM cards WHERE id=?", inv)[0]) == ("krans", "kraft"), "trycksaker: färgat papper sparas")
h = html(req(a, f"/kort/{inv}/skriv-ut"))
ok('p-kraft' in h and 'd-krans' in h and "A &amp; E" in h, "trycksaker: utskrift med färgat papper och initialer i kransen")
ok(req(a, f"/kort/{inv}", {**CARD, "paper": "neon"})[0] == 400, "trycksaker: okänt papper nekas")
r = req(a, "/kort/qr.svg?stil=hjartan&mitt=ringar")
ok(r[0] == 200 and r[1]["Content-Type"].startswith("image/svg+xml") and b"qr-fancy" in r[2] and b"EXEMPEL" not in r[2],
   "rolig QR: förhandsvisning i vald stil")
ok(req(a, "/kort/qr.svg?stil=<x>&mitt=ringar")[0] == 400 and req(client(), "/kort/qr.svg?stil=prickar&mitt=hjarta", follow=False)[0] == 303,
   "rolig QR: ogiltig stil nekas, kräver inloggning")
req(a, f"/kort/{inv}", {**CARD, "qr_style": "romb", "qr_center": "initialer", "qr_color": "svart"})
ok(tuple(q("SELECT qr_style, qr_center, qr_color FROM cards WHERE id=?", inv)[0]) == ("romb", "initialer", "svart"), "rolig QR: valen sparas")
h = html(req(a, f"/kort/{inv}/skriv-ut"))
ok(h.count("qr-fancy") == n_households and "q-svart" in h, "rolig QR: personliga kort får dekorativ kod i vald färg")
ok(req(a, f"/kort/{inv}", {**CARD, "qr_center": "drake"})[0] == 400, "rolig QR: okänt motiv nekas")
ok("qr-fancy" in html(req(a, "/m/guests/qr")) and "qr-fancy" in html(req(a, "/photos/cards")), "rolig QR på OSA-kort och bordskort för bilder")

# ---------------------------------------------------------------- låtönskemål
DB.execute("UPDATE guests SET rsvp='yes', attending=1, song='Dancing Queen' WHERE name='Bertil'")
DB.execute("UPDATE guests SET song='dancing queen!' WHERE id=?", (gA[0],))
DB.execute("UPDATE guests SET rsvp='yes', attending=2, song='<b>September</b>' WHERE name='Cecilia & Carl'")
DB.commit()
h = html(req(a, "/rapport/latar"))
ok(h.count("<li>") == 2 and "2 önskningar" in h and h.index("Dancing Queen") < h.index("September") and "&lt;b&gt;September" in h,
   "låtönskemål: ihopslagna, mest önskad först, escapade")
body = req(a, "/rapport/latar.csv")[2].decode("utf-8-sig")
ok("Dancing Queen;2;" in body and "Bertil" in body and "Familjen Andersson" in body, "låtönskemål som CSV till DJ:n")
ok(req(client(), "/rapport/latar", follow=False)[0] == 303, "låtönskemål kräver inloggning")

# ---------------------------------------------------------------- import av gästlistan
TSV = ("Namn\tE-post\tAntal\tGrupp\tSida\tGatuadress\tPostnummer\tOrt\tOkänd\n"
       "Familjen Östberg\tost@example.se\t4\tGrannar\tpartner a\tByvägen 3\t123 45\tÅre\tx\n"
       "Bertil\t\t1\t\t\t\t\t\t\n"
       "Fel Persson\tinte-en-adress\t2\t\t\t\t\t\t\n"
       "\t\t\t\t\t\t\t\t\n"
       "=Formel AB\t\t\t\t\t\t\t\t\n")
r = req(a, "/m/guests/import", {"csrf": c, "text": TSV}); h = html(r)
ok(r[0] == 200 and "<strong>2</strong> av 4" in h and "Finns redan" in h and "ogiltig e-postadress" in h and "okänd" in h,
   "import: förhandsvisning med dubblett, fel och okänd kolumn")
ok(not q("SELECT 1 FROM guests WHERE name='Familjen Östberg'"), "import: förhandsvisningen sparar inget")
ok(req(a, "/m/guests/import/spara", {"csrf": "fel", "text": TSV})[0] == 403
   and req(v, "/m/guests/import/spara", {"csrf": c2, "text": TSV})[0] == 403, "import kräver CSRF och skrivbehörighet")
r = req(a, "/m/guests/import/spara", {"csrf": c, "text": TSV})
g2 = q("SELECT invited_count, group_name, side, street, postcode, city, rsvp, rsvp_code IS NOT NULL FROM guests WHERE name='Familjen Östberg'")
ok("2 hushåll importerades" in html(r) and g2 and tuple(g2[0]) == (4, "Grannar", "Partner A", "Byvägen 3", "123 45", "Åre", "pending", 1),
   "import: hushåll sparas med adress, sida och egen OSA-kod")
ok(q("SELECT COUNT(*) FROM guests WHERE name='Bertil'")[0][0] == 1 and q("SELECT invited_count FROM guests WHERE name='=Formel AB'")[0][0] == 1,
   "import: dubbletter hoppas över, saknat antal blir 1")
req(a, "/m/guests/import/spara", {"csrf": c, "text": TSV})
ok(q("SELECT COUNT(*) FROM guests WHERE name='Familjen Östberg'")[0][0] == 1, "import: kan göras om utan dubbletter")
csv_bytes = "Namn;Antal\r\nGöran Åkesson;3\r\n".encode("cp1252")
body, hd = multipart({"csrf": c}, [("file", ("gaster.csv", csv_bytes, "text/csv"))])
ok("Göran Åkesson" in html(req(a, "/m/guests/import", raw=body, headers=hd)), "import: CSV-fil från Excel (cp1252, semikolon)")
ok("&lt;b&gt;" in html(req(a, "/m/guests/import", {"csrf": c, "text": "Namn\n<b>Hack</b>"})), "import: förhandsvisningen escapas")

# ---------------------------------------------------------------- cache-busting av statiska filer
import hashlib as _hl
from pathlib import Path as _P
_css = _P(__file__).resolve().parents[1] / "app" / "static" / "style.css"
_h = _hl.sha256(_css.read_bytes()).hexdigest()[:12]
page = html(req(client(), "/login"))
ok(f'/static/style.css?v={_h}' in page and "/static/app.js?v=" in page, "stilmall och skript länkas med innehållshash")
r = req(client(), f"/static/style.css?v={_h}"); ok(r[0] == 200 and "immutable" in r[1]["Cache-Control"], "versionerad fil cachas länge")
r = req(client(), "/static/style.css"); ok(r[0] == 200 and r[1]["Cache-Control"] == "no-cache", "oversionerad fil måste kontrolleras mot servern")
ok(req(client(), "/login")[1]["Cache-Control"] == "no-store", "sidor cachas aldrig")

r = req(client(), "/login", {"username": "nobody", "password": "x"*12}, headers={"X-Forwarded-Proto": "https"})
hx = req(client(), "/login", headers={"X-Forwarded-Proto": "https"})[1]
ok("strict-transport-security" in {k.lower() for k in hx.keys()}, "HTTPS via betrodd proxy → HSTS")
ok("strict-transport-security" not in {k.lower() for k in req(client(), "/login")[1].keys()}, "direkt http → ingen HSTS")
print(f"\n{sum(results)}/{len(results)} godkända")
sys.exit(0 if all(results) else 1)
