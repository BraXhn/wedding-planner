// Service worker för apparna /tm och /plan: sidorna sparas när de hämtas så att appen fungerar
// utan nät (senast sparade version), och push-aviseringar visas. Ändringar (POST) cachas aldrig.
const CACHE = "app-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

const cacheable = (res) => res && res.ok && res.type === "basic" && !res.redirected;

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {  // versionerade filer: cache först
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (cacheable(res)) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })));
    return;
  }
  const scope = new URL(self.registration.scope).pathname.replace(/\/$/, "");
  if (req.mode !== "navigate" || !(url.pathname === scope || url.pathname.startsWith(scope + "/"))) return;
  // sidor: nätet först, sparad kopia om nätet saknas
  e.respondWith(fetch(req).then((res) => {
    if (cacheable(res)) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(url.pathname + url.search, copy)); }
    return res;
  }).catch(() => caches.match(url.pathname + url.search).then((hit) => hit || caches.match(url.pathname))
    .then((hit) => hit || caches.match(scope))
    .then((hit) => hit || new Response("<meta name=viewport content='width=device-width'><p style='font:18px system-ui;padding:24px'>Offline – sidan är inte sparad än. Öppna den en gång med nät.</p>",
      { headers: { "Content-Type": "text/html; charset=utf-8" } }))));
});

// appen ber om att alla flikar sparas direkt, så att de finns offline även om de inte öppnats
self.addEventListener("message", (e) => {
  const data = e.data || {};
  if (data.type === "warm" && Array.isArray(data.urls)) {
    e.waitUntil(caches.open(CACHE).then((c) => Promise.all(data.urls.map((u) =>
      fetch(u, { credentials: "same-origin" }).then((res) => (cacheable(res) ? c.put(u, res) : null)).catch(() => null)))));
  }
  if (data.type === "clear") e.waitUntil(caches.delete(CACHE));
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "Bröllopet", {
    body: d.body || "", data: { url: d.url || self.registration.scope }, icon: "/static/icon-192.png", badge: "/static/icon-192.png",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || self.registration.scope;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(url).catch(() => {}); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
