// Offline support. Always tries the network first so the newest menu wins;
// falls back to the last saved copy when there's no signal (or it's slow).
const CACHE = "gf-menus-v9";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest",
  "data/restaurants.json", "phrases.json", "cities.json", "icons/apple-touch-icon.png", "icons/icon-192.png", "icons/favicon.png"];
const TIMEOUT_MS = 4000;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
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
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const key = new URL(req.url);
    key.search = "";
    try {
      const res = await Promise.race([
        fetch(req, { cache: "no-store" }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), TIMEOUT_MS)),
      ]);
      if (res.ok) cache.put(key.href, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(key.href) || (req.mode === "navigate" && await cache.match("index.html"));
      if (hit) {
        // Mark saved copies so the app can say it's offline.
        const headers = new Headers(hit.headers);
        headers.set("X-GF-Offline", "1");
        return new Response(hit.body, { status: hit.status, statusText: hit.statusText, headers });
      }
      throw err;
    }
  })());
});
