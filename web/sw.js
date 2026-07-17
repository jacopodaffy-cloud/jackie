/* Jackie service worker — makes the dashboard installable as a phone app.
   Strategy: network-first with cache fallback for the app shell (always
   fresh online, still opens offline); /api/* is never cached (live data). */
const CACHE = "jackie-v1";
const SHELL = ["./", "./index.html", "./style.css", "./app.js",
  "./manifest.json", "./icons/icon-192.png", "./icons/icon-512.png"];

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
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.includes("/api/")) return; // live data only
  if (url.origin !== location.origin) return;                               // CDN/scripts: browser default
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true })
        .then((hit) => hit || caches.match("./index.html")))
  );
});
