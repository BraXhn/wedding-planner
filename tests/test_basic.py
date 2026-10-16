import re, sys, time, urllib.request, urllib.parse, http.cookiejar, subprocess
B="http://127.0.0.1:" + __import__("os").environ.get("TEST_PORT", "8099")
PW=re.search(r"Engångslösenord: (\S+)", open(sys.argv[1]).read()).group(1)
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k): return None
def client():
    cj=http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedir), cj
def req(op, path, data=None, follow=True):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    for _ in range(5):
        try: r = op.open(B+path, body); return r.status, r.headers, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code in (301,302,303) and follow:
                path = e.headers["location"]; body=None; continue
            return e.code, e.headers, e.read().decode()
def csrf(html): return re.search(r'name="csrf" value="([^"]+)"', html).group(1)
FAILS=[]
def ok(c,m):
    print(("PASS " if c else "FAIL ")+m)
    if not c: FAILS.append(m)

a,_=client()
s,_,h=req(a,"/login",{"username":"testadmin","password":"fel"}); ok(s==401,"fel lösenord -> 401")
s,_,h=req(a,"/login",{"username":"TESTADMIN","password":PW}); ok("måste byta lösenord" in h,"tvingas byta lösenord (case-okänsligt namn)")
s,_,h=req(a,"/m/guests"); ok("måste byta" in h,"blockeras från data före byte")
c=csrf(h); NEW="Korrekt-Häst-Batteri-Häftklammer"
s,_,h=req(a,"/account/password",{"csrf":c,"current":PW,"new":"kort","new2":"kort"}); ok(s==400 and "minst 12" in h,"kort lösenord nekas")
s,_,h=req(a,"/account/password",{"csrf":c,"current":PW,"new":NEW,"new2":NEW}); ok("Lösenordet är bytt" in h,"lösenordsbyte")
s,_,h=req(a,"/"); ok("dagar kvar" in h or "Välkommen" in h,"dashboard")
c=csrf(h)
s,_,h=req(a,"/settings",{"csrf":"x","couple_names":"Hack"}); ok(s==403,"CSRF-fel -> 403")
s,_,h=req(a,"/settings",{"csrf":c,"couple_names":"Anna & Erik","wedding_date":"2027-06-12","wedding_time":"14:00","venue":"Ulriksdals slott","rsvp_deadline":"2027-04-01","total_budget":"250 000","info_text":"Rad1\nRad2 <script>alert(1)</script>"}); ok(s==200 and "Sparat" in h,"inställningar sparas")
s,_,h=req(a,"/"); ok("244" in h or "dagar kvar" in h,"nedräkning visas"); 
s,_,h=req(a,"/m/guests/new",{"csrf":c,"name":"<img src=x onerror=alert(1)>","invited_count":"2","rsvp":"pending","side":"Gemensam","email":"anna@ex.se"}); ok(s==200,"gäst skapad")
s,_,h=req(a,"/m/guests"); ok("&lt;img" in h and "<img src=x" not in h,"XSS escapas i lista")
gid=re.search(r'href="/m/guests/(\d+)"',h).group(1)
s,_,h=req(a,f"/m/guests/{gid}"); link=re.search(r'id="rsvplink" value="([^"]+)"',h).group(1); ok("/r/" in link,"OSA-länk "+link)
s,_,h=req(a,"/m/guests/new",{"csrf":c,"name":"","invited_count":"99","email":"nej","rsvp":"evil"}); ok(s==400 and "måste fyllas" in h and "mellan" in h and "e-post" in h and "ogiltigt val" in h,"validering")
s,_,h=req(a,"/m/budget/new",{"csrf":c,"item":"Lokalhyra","category":"Lokal","estimated":"60 000","actual":"","due_date":"2026-01-01"}); ok(s==200,"budgetpost")
s,_,h=req(a,"/m/budget"); ok("60 000 kr" in h,"summering budget")
s,_,h=req(a,"/m/tasks?f=open&q=hinders"); ok("Skatteverket" in h,"förifylld checklista + sök")
tid=re.search(r'/m/tasks/(\d+)/toggle',h).group(1)
s,_,h=req(a,f"/m/tasks/{tid}/toggle",{"csrf":c,"next":"https://evil.example"},follow=False); ok(s==303 and _["location"]=="/m/tasks","toggle, ingen open redirect")
s,_,h=req(a,"/m/vendors/new",{"csrf":c,"name":"Foto AB","website":"javascript:alert(1)"}); ok(s==400,"javascript:-URL nekas")
s,_,h=req(a,"/m/timeline/new",{"csrf":c,"time":"25:00","title":"x"}); ok(s==400,"ogiltig tid nekas")
s,_,h=req(a,"/m/timeline/new",{"csrf":c,"time":"14:00","title":"Vigsel"}); ok(s==200,"körschema")
s,hd,h=req(a,"/m/guests/export.csv"); ok(h.startswith("﻿") and hd["content-type"].startswith("text/csv"),"CSV-export")
s,_,h=req(a,"/m/evil"); ok(s==404,"okänd entitet 404")
s,_,h=req(a,"/m/guests/99999"); ok(s==404,"okänd post 404")
# TOTP
s,_,h=req(a,"/account/totp/start",{"csrf":c}); sec=re.search(r'<code class="secret">([A-Z2-7 ]+)</code>',h).group(1).replace(' ','')
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1])); from app.security import totp_now
s,_,h=req(a,"/account/totp/confirm",{"csrf":c,"code":totp_now(sec)}); ok("aktiverad" in h,"2FA aktiverad")
# users
s,_,h=req(a,"/users",{"csrf":c,"username":"toast","password":"Toastmaster-2027!","role":"viewer"}); ok("skapades" in h,"läsare skapad")
# public rsvp
tok=link.split("/r/")[1]
p,_=client()
s,_,h=req(p,f"/r/{tok}"); ok(s==200 and "Ulriksdals" in h and "&lt;script&gt;" in h,"OSA-sida publik, info escapas")
s,_,h=req(p,f"/r/{tok}",{"answer":"yes","coming_1":"on","name_1":""}); ok(s==400 and "namnet" in h,"den som kommer måste ha namn")
s,_,h=req(p,f"/r/{tok}",{"answer":"yes","name_1":"Anna"}); ok(s==400 and "Kryssa i" in h,"minst en måste komma")
s,_,h=req(p,f"/r/{tok}",{"answer":"yes","name_1":"Anna","coming_1":"on","allergy_1":"Vegan","name_2":"Erik","coming_2":"on",
    "name_5":"Extra","coming_5":"on","speech":"on","song":"Dancing Queen"}); ok("Tack!" in h,"OSA sparad (fler än inbjudna ignoreras)")
s,_,h=req(p,"/r/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"); ok(s==404,"fel token 404")
s,_,h=req(p,"/m/guests"); ok("Logga in" in h,"publik kommer inte åt admin")
s,_,h=req(a,"/"); ok("2 <small>av 2 kommer" in h and "1 med specialkost" in h,"dashboard räknar OSA")
# viewer
v,_=client()
s,_,h=req(v,"/login",{"username":"toast","password":"Toastmaster-2027!"}); c2=csrf(h)
s,_,h=req(v,"/account/password",{"csrf":c2,"current":"Toastmaster-2027!","new":"En-helt-annan-fras-99","new2":"En-helt-annan-fras-99"})
s,_,h=req(v,"/m/guests"); ok(s==200 and "+ Ny" not in h,"läsare ser lista utan knappar")
s,_,h=req(v,"/m/guests/new",{"csrf":c2,"name":"x"}); ok(s==403,"läsare kan inte skriva")
s,_,h=req(v,"/users"); ok(s==403,"läsare når inte användare")
# login with 2FA required
b,_=client()
s,_,h=req(b,"/login",{"username":"testadmin","password":NEW}); ok(s==401,"2FA krävs")
time.sleep(0)
# rate limit
for i in range(6): s,_,h=req(b,"/login",{"username":"testadmin","password":"x"+str(i)})
ok(s==429,"rate limit efter upprepade fel")
# big body
r=urllib.request.Request(B+"/login",data=b"a="+b"x"*300000); 
try: urllib.request.urlopen(r); ok(False,"stor body")
except urllib.error.HTTPError as e: ok(e.code==413,"för stor body -> 413")
s,hd,h=req(b,"/login")
for hname in ["content-security-policy","x-frame-options","referrer-policy","x-content-type-options"]: ok(hname in {k.lower() for k in hd.keys()},"header "+hname)
ok("server" not in {k.lower() for k in hd.keys()},"ingen server-header")
s,_,h=req(a,"/docs"); ok(s==404,"inga API-docs")
s,_,h=req(a,"/static/../app/main.py"); ok(s==404 or "import" not in h,"path traversal")

print(f"\n{len(FAILS)} fel")
sys.exit(1 if FAILS else 0)
