// Runs site/sw.js's push and notificationclick handlers in Node with stand-ins for the service worker's world, so
// tests/test_sw_push.py can check what a notification says without a browser delivering a push.
// Usage: node sw_push_harness.js <sw.js path> <favourites JSON> <message JSON>
const fs = require("fs");
const vm = require("vm");
const [, , swPath, favsJson, msgJson] = process.argv;
const handlers = {};
const out = { notifications: [], badge: null, opened: null, navigated: null, focused: false };
const favs = JSON.parse(favsJson);
const req = (result) => { const r = { result }; setTimeout(() => r.onsuccess && r.onsuccess(), 0); return r; };
const self = {
  addEventListener: (name, fn) => { handlers[name] = fn; },
  location: { href: "https://example.test/gf-drinks/sw.js" },
  registration: { showNotification: async (title, opts) => { out.notifications.push({ title, ...opts }); } },
  navigator: { setAppBadge: async (n) => { out.badge = n; } },
  clients: {
    matchAll: async () => (process.env.OPEN_CLIENT ? [{ focus: async () => { out.focused = true; }, navigate: async (u) => { out.navigated = u; } }] : []),
    openWindow: async (u) => { out.opened = u; },
    claim: async () => {},
  },
  skipWaiting: async () => {},
};
const indexedDB = {
  open: () => {
    const r = { result: { createObjectStore() {}, transaction: () => ({ objectStore: () => ({ get: () => req(favs) }) }) } };
    setTimeout(() => r.onsuccess && r.onsuccess(), 0);
    return r;
  },
};
const ctx = { self, indexedDB, caches: { open: async () => ({}), keys: async () => [] }, URL, Headers, Response, Promise, setTimeout, clearTimeout, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(swPath, "utf-8"), ctx);
(async () => {
  const waits = [];
  const msg = JSON.parse(msgJson);
  handlers.push({ data: { json: () => msg, text: () => msgJson }, waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
  const clicks = [];
  handlers.notificationclick({ notification: { close() {}, data: { url: msg.url || "" } }, waitUntil: (p) => clicks.push(p) });
  await Promise.all(clicks);
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
