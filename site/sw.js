// Offline support, a quick start on a weak signal, and notifications about new menus.
// The app's own files come straight from this release's saved copy: they only change with a new release, which comes
// with a new service worker (a new CACHE) that saves the new files before it takes over. Menus, phrases and cities try
// the network first, so the newest menu wins, and fall back to the saved copy when there's no signal (or it's slow).
// Nothing waits for them: the app shows the menus saved on the phone meanwhile. They're checked, not downloaded afresh,
// so a file that hasn't changed comes back as "not modified". The guides (PDFs) and map tiles are never saved here:
// a guide is fetched when it's opened, and the tile provider's rules forbid keeping tiles.
const CACHE = "gf-menus-v28";
const SHELL = ["./", "index.html", "styles.css", "theme.js", "compare.js", "app.js", "manifest.webmanifest",
  "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css",
  "data/restaurants.json", "phrases.json", "cities.json", "icons/apple-touch-icon.png", "icons/icon-192.png", "icons/favicon.png"];
const TIMEOUT_MS = 4000;
const isData = (url) => url.pathname.endsWith(".json");
const isGuide = (url) => /\/guides\//.test(url.pathname);

self.addEventListener("install", (e) => {
  // past the browser's cache (reload) and the server's (?v=), so a new release never saves an older copy of a file
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map(async (u) => {
    const res = await fetch(new Request(u + "?v=" + CACHE, { cache: "reload" }));
    if (!res.ok) throw new Error(u + " " + res.status);
    await c.put(new URL(u, self.location.href).href, res);
  }))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || isGuide(url)) return;
  url.search = "";
  e.respondWith(isData(url) ? newest(url) : saved(req, url));
});

// the app's own files: this release's copy at once
async function saved(req, url) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(url.href) || (req.mode === "navigate" && await cache.match(new URL("index.html", self.location.href).href));
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(url.href, res.clone());
  return res;
}

// menus, phrases and cities: the network if it answers in time, else the saved copy
async function newest(url) {
  const cache = await caches.open(CACHE);
  let timer;
  try {
    const res = await Promise.race([
      fetch(url.href, { cache: "no-cache" }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), TIMEOUT_MS); }),
    ]);
    if (res.ok) cache.put(url.href, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(url.href);
    if (hit) {
      // Mark saved copies so the app can say it's offline.
      const headers = new Headers(hit.headers);
      headers.set("X-GF-Offline", "1");
      return new Response(hit.body, { status: hit.status, statusText: hit.statusText, headers });
    }
    throw err;
  } finally {
    clearTimeout(timer); // the network answered (or failed) in time: no timer left to fire for nothing
  }
}

// ---------- notifications about new menus (tools/push.py sends them after a publish that brought a new guide) ----------
// The message names the restaurants and what changed, and carries the keys of items that now contain gluten. The app
// keeps a copy of the favourites here (IndexedDB "gf", store "kv", key "favs"; localStorage isn't readable from a
// service worker), so the notification can say when one of them is affected.
function favsSaved() {
  return new Promise((ok) => {
    try {
      const open = indexedDB.open("gf", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("kv");
      open.onerror = () => ok([]);
      open.onsuccess = () => {
        try {
          const get = open.result.transaction("kv").objectStore("kv").get("favs");
          get.onsuccess = () => ok(Array.isArray(get.result) ? get.result : []);
          get.onerror = () => ok([]);
        } catch (e) { ok([]); }
      };
    } catch (e) { ok([]); }
  });
}
self.addEventListener("push", (e) => {
  let msg = {};
  try { msg = e.data ? e.data.json() : {}; } catch (err) { msg = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil((async () => {
    const favs = new Set(await favsSaved());
    const hit = (msg.nowAvoid || []).filter((k) => favs.has(k)).map((k) => k.split("|").slice(2).join("|"));
    let body = msg.body || "New menus are in.";
    if (hit.length) body = "A favourite now contains gluten: " + hit.slice(0, 3).join(", ") + (hit.length > 3 ? " and " + (hit.length - 3) + " more" : "") + ". " + body;
    try { if ("setAppBadge" in self.navigator) await self.navigator.setAppBadge(msg.badge || 1); } catch (err) { /* no badge */ }
    await self.registration.showNotification(msg.title || "Treat Temple", {
      body, tag: msg.tag || "gf-menus", icon: "icons/icon-192.png", badge: "icons/icon-192.png", renotify: !!hit.length,
      data: { url: msg.url || "" },
    });
  })());
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = new URL("./" + ((e.notification.data && e.notification.data.url) || ""), self.location.href).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (list) => {
    const open = list.find((c) => "focus" in c);
    if (open) { await open.focus(); if ("navigate" in open) return open.navigate(target).catch(() => null); return null; }
    return self.clients.openWindow(target);
  }));
});
