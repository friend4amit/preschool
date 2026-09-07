{% load static %}/* Aaroham's service worker. Deliberately the smallest one that earns its place.
 *
 * It exists for one reason: a parent who taps the home-screen icon with no signal
 * should get an Aaroham page saying so, not the browser's dinosaur. It does NOT
 * exist to make the feed work offline.
 *
 * ── The rule that matters ──────────────────────────────────────────────────────
 *
 * THIS WORKER MUST NEVER CACHE A PHOTOGRAPH OF A CHILD.
 *
 * Caching a photo response would write children's images into browser cache storage
 * and survive there — and "revoking photos_in_app hides the feed on the next request"
 * (docs/implementation-plan.md, Phase 4's own Done-when) would stop being true. The
 * consent gate runs per request on the server; anything this file serves from cache
 * is a request that never reached it.
 *
 * So the fetch handler works from a POSITIVE ALLOWLIST of exact shell URLs, not a
 * denylist of things to skip. A denylist grows a hole the first time somebody adds a
 * route; an allowlist fails closed, which for this app is the correct direction.
 *
 * Presigned R2 GETs expire in five minutes anyway, so caching them would also simply
 * be broken. Wrong AND useless is a comfortable place for a rule to sit.
 */

const VERSION = "aaroham-shell-v1";

/* The allowlist. Every entry is hashed by WhiteNoise's manifest storage, so a deploy
 * that changes any of these changes its URL — the old entry ages out with its cache
 * and there is no stale-asset story to manage. */
const SHELL = [
  "{% static 'css/app.css' %}",
  "{% static 'vendor/htmx.min.js' %}",
  "{% static 'fonts/fraunces-latin.woff2' %}",
  "{% static 'fonts/karla-latin.woff2' %}",
  "{% static 'img/icon-192.png' %}",
  "{% url 'offline' %}",
];

const OFFLINE_URL = "{% url 'offline' %}";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      // Individually, not addAll: addAll rejects the whole install if any one URL
      // 404s, and an install that fails silently leaves no worker at all.
      .then((cache) => Promise.all(SHELL.map((url) => cache.add(url).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== VERSION).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Only ever GET, and only ever this origin. A presigned R2 URL is cross-origin and
  // falls out here before any cache is consulted.
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // The shell: cache first, because these are content-hashed and cannot go stale.
  if (SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request)));
    return;
  }

  // Everything else — every page, every photo, every API call — goes to the network
  // and is NOT cached. When the network is gone and the request was for a page, show
  // the offline page; otherwise let the failure be a failure.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
  }
});
