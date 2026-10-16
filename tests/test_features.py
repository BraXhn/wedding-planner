import email.policy, re, sys, io, json, time, uuid, sqlite3, urllib.request, urllib.parse, http.cookiejar
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.security import totp_now
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
r = req(a, "/settings", {"csrf": c, "couple_names": "Anna & Erik", "wedding_date": "2027-06-12", "wedding_time": "14:00",
     "venue": "Ulriksdals slott", "address": "Slottsvägen 1", "rsvp_deadline": "2027-04-01", "total_budget": "250000",
     "info_text": "Välkomna!", "directions": "Buss 503", "accommodation": "Hotell X", "gift_info": "Swish 123",
     "photos_enabled": "on", "photo_quota_mb": "500",
     "invite_subject": "Inbjudan {brudpar} {__class__}", "invite_body": "Hej {namn}! {länk} {datum} {0.__class__}",
     "reminder_subject": "Påminnelse", "reminder_body": "Svara {länk}"})
h = html(r); ok("Sparat" in h and "deadlines" in h, "inställningar sparas + deadlines fylls i")
d = q("SELECT due_date FROM tasks WHERE title LIKE 'Begär hindersprövning%'")[0][0]
ok(d == "2027-05-12", f"hindersprövning-deadline = 1 mån före ({d})")
ok(q("SELECT due_date FROM tasks WHERE period='Efteråt' LIMIT 1")[0][0] == "2027-07-12", "efteråt-deadline")
ok(q("SELECT COUNT(*) FROM tasks WHERE COALESCE(due_date,'')=''")[0][0] == 0, "alla uppgifter fick deadline")

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
pp = q("SELECT pos, name, attending, allergies FROM guest_people WHERE guest_id=? ORDER BY pos", gA[0])
ok([tuple(x) for x in pp] == [(1, "Anders", 1, "Nötter"), (2, "Annika", 1, ""), (3, "Albin", 1, "")]
   and q("SELECT attending FROM guests WHERE id=?", gA[0])[0][0] == 3, "OSA sparar namn och allergi per person")
h = html(req(p, f"/r/{gA[1]}")); ok('value="Annika"' in h and 'value="Nötter"' in h, "OSA-formuläret visar sparade personer")
r = req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, "name_1": "Anders", "coming_1": "on", "allergy_1": "Nötter",
                                         "name_2": "Annika", "name_3": "Albin", "coming_3": "on"})
ok(q("SELECT attending FROM guests WHERE id=?", gA[0])[0][0] == 2, "admin bockar ur en person → antal som kommer räknas om")
ok(req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, "name_1": "Anders"})[0] == 400, "admin: minst en måste komma vid ”Kommer”")
ok(req(a, f"/m/guests/{gA[0]}/people", {"name_1": "X", "coming_1": "on"})[0] == 403, "personer kräver CSRF")
req(a, f"/m/guests/{gA[0]}/people", {"csrf": c, **{k: v for k, v in FAM.items() if k != "answer"}})
r = req(p, f"/r/{gA[1]}/info"); h = html(r)
ok("Buss 503" in h and "Hotell X" in h, "informationssida")
r = req(p, f"/r/{gA[1]}/brollop.ics"); body = r[2].decode()
ok(r[0] == 200 and "BEGIN:VEVENT" in body and "DTSTART:20270612T140000" in body and "\r\n" in body, "gästens .ics")

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
ok(req(client(), f"/r/{gA[1]}/photos?ok=%C2%B2")[0] == 200 and req(client(), f"/p/{ptok}?ok=" + "9" * 5000)[0] == 200,
   "konstigt ?ok= ger ingen krasch")
s2 = html(req(a, "/settings"))
form = {"csrf": c, "couple_names": "Anna & Erik", "wedding_date": "2027-06-12", "wedding_time": "14:00", "venue": "Ulriksdals slott",
        "rsvp_deadline": "2027-04-01", "photos_enabled": "on", "gallery_public": "on", "photo_moderation": "on", "photo_quota_mb": "500",
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
ok(req(v, "/api-keys")[0] == 403 and req(v, "/mail/send", {"csrf": c2, "kind": "invite", "confirm": "on"})[0] == 403, "läsare når inte API-nycklar/utskick")
ok(req(v, "/seating/assign", raw=b"{}", headers={"Content-Type": "application/json", "X-CSRF-Token": c2})[0] == 403, "läsare kan inte flytta gäster")
ok('draggable' not in html(req(v, "/seating")), "läsare ser placering utan dra-funktion")

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
ok(req(v, "/m/guests/qr")[0] == 200 and "footer-editor" not in html(req(v, "/m/guests/qr")), "läsare ser korten utan redigering")
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
