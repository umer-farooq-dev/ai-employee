{% load static %}/* MOB-03: installable app — push alerts and an offline page. Pages are never cached (live data). */
"use strict";
const CACHE = "aie-shell-v1", OFFLINE = "/offline/";
const ICON = "{{ icon|escapejs }}", BADGE = "{% static 'brand/app-badge-96.png' %}";

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, ICON, BADGE])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
    event.waitUntil(caches.keys()
        .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
        .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
    if (event.request.mode === "navigate") {
        event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
    }
});
self.addEventListener("push", (event) => {
    let d = {};
    try { d = event.data ? event.data.json() : {}; } catch (e) { d = {title: event.data.text()}; }
    const url = d.id ? "/app/notifications/" + d.id + "/open/" : (d.url || "/app/");
    event.waitUntil(self.registration.showNotification(d.title || "", {
        body: d.body || "", icon: ICON, badge: BADGE, tag: d.id || undefined, renotify: true,
        requireInteraction: d.kind === "handoff", data: {url: url},
    }));
});
self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || "/app/";
    event.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then((list) => {
        for (const c of list) {
            if (c.url.indexOf(self.location.origin) === 0 && "focus" in c) { c.navigate(url); return c.focus(); }
        }
        return clients.openWindow(url);
    }));
});
