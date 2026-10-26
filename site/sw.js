// Offline support, and a quick start on a weak signal.
// The app's own files come straight from this release's saved copy: they only change with a new release, which comes
// with a new service worker (a new CACHE) that saves the new files before it takes over. Menus, phrases and cities try
// the network first, so the newest menu wins, and fall back to the saved copy when there's no signal (or it's slow).
// Nothing waits for them: the app shows the menus saved on the phone meanwhile. They're checked, not downloaded afresh,
// so a file that hasn't changed comes back as "not modified".
const CACHE = "gf-menus-v25";
const SHELL = ["./", "index.html", "styles.css", "compare.js", "app.js", "manifest.webmanifest",
  "data/restaurants.json", "phrases.json", "cities.json", "icons/apple-touch-icon.png", "icons/icon-192.png", "icons/favicon.png"];
const TIMEOUT_MS = 4000;
const isData = (url) => url.pathname.endsWith(".json");

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
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
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
  try {
    const res = await Promise.race([
      fetch(url.href, { cache: "no-cache" }),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), TIMEOUT_MS)),
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
  }
}
