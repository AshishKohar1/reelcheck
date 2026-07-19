// Minimal service worker — required for PWA install / Android share-target.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {}); // network-only; nothing cached for now
