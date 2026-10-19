/*! AI Employee website chat widget (CHAT-01 … CHAT-07).
 * <script src="https://<platform>/static/webchat/widget.js" data-key="wk_…" async></script>
 * No dependencies, loads asynchronously, draws inside a Shadow DOM so the host page's CSS cannot break it.
 * Every text, colour and action comes from the server (Super Admin and the company's widget settings).
 */
(function () {
    "use strict";
    var script = document.currentScript || document.querySelector("script[data-key][src*='webchat/widget']");
    if (!script || window.__aieChat) return;
    window.__aieChat = true;
    var KEY = script.getAttribute("data-key");
    var BASE = new URL(script.src).origin + "/public/v1/chat/" + encodeURIComponent(KEY) + "/";
    var STORE = "aie_chat_" + KEY;
    var cfg, token, lang, last = "", timer, opened = false, startedAt = 0, busy = false, seen = {};
    var host, root, els = {};

    function load(k) { try { return localStorage.getItem(STORE + k) || ""; } catch (e) { return ""; } }
    function save(k, v) { try { v ? localStorage.setItem(STORE + k, v) : localStorage.removeItem(STORE + k); } catch (e) { /* private mode */ } }
    function T(k) { return ((cfg.texts[lang] || cfg.texts[cfg.language] || {})[k]) || ""; }
    function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
    function rich(s) {  // light formatting the AI uses: **bold**, links, line breaks
        return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
            .replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)])/g, '<a href="$1" target="_blank" rel="noopener nofollow">$1</a>')
            .replace(/\n/g, "<br>");
    }
    function api(method, path, body) {
        var headers = {"Accept": "application/json"};
        if (body) headers["Content-Type"] = "application/json";
        if (token) headers["X-Chat-Token"] = token;
        return fetch(BASE + path, {method: method, headers: headers, body: body ? JSON.stringify(body) : undefined, mode: "cors", credentials: "omit"})
            .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return r.ok ? d : Promise.reject({status: r.status, data: d}); }); });
    }

    // ------------------------------------------------------------------ drawing
    function css(c) {
        return ":host{all:initial}*{box-sizing:border-box;font-family:system-ui,-apple-system,'Segoe UI',Roboto,'Noto Sans','Noto Sans Devanagari','Noto Sans Bengali',sans-serif}" +
            ".launch{position:fixed;bottom:20px;" + (cfg.position === "left" ? "left" : "right") + ":20px;z-index:2147483000;display:flex;align-items:center;gap:10px;border:0;border-radius:999px;padding:12px 18px 12px 12px;background:" + c + ";color:#fff;font-size:15px;font-weight:600;cursor:pointer;box-shadow:0 10px 30px rgba(16,21,55,.25);transition:transform .15s}" +
            ".launch:hover{transform:translateY(-2px)}.launch:focus-visible,button:focus-visible,select:focus-visible{outline:3px solid " + c + "55;outline-offset:2px}" +
            ".launch img,.launch .ic{width:34px;height:34px;border-radius:50%;object-fit:cover;background:rgba(255,255,255,.2);display:flex;align-items:center;justify-content:center}" +
            ".panel{position:fixed;bottom:88px;" + (cfg.position === "left" ? "left" : "right") + ":20px;z-index:2147483001;width:380px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 120px);background:#fff;border-radius:18px;box-shadow:0 24px 60px rgba(16,21,55,.28);display:none;flex-direction:column;overflow:hidden;color:#1f2433;font-size:14px}" +
            ".panel.open{display:flex}" +
            ".head{background:" + c + ";color:#fff;padding:14px 16px;display:flex;align-items:center;gap:12px}" +
            ".head img,.head .ic{width:40px;height:40px;border-radius:50%;object-fit:cover;background:rgba(255,255,255,.2);flex:none;display:flex;align-items:center;justify-content:center}" +
            ".head .t{flex:1;min-width:0}.head b{display:block;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.head small{opacity:.85;font-size:12px}" +
            ".head select{background:rgba(255,255,255,.18);color:#fff;border:0;border-radius:8px;padding:4px 6px;font-size:12px}.head select option{color:#1f2433}" +
            ".x{background:transparent;border:0;color:#fff;font-size:22px;line-height:1;cursor:pointer;padding:4px;border-radius:8px}" +
            ".body{flex:1;overflow-y:auto;padding:16px;background:#f6f7fb;display:flex;flex-direction:column;gap:8px}" +
            ".m{max-width:82%;padding:10px 13px;border-radius:16px;line-height:1.45;word-wrap:break-word;white-space:normal}" +
            ".m.ai,.m.human{background:#fff;border:1px solid #e6e8ef;border-bottom-left-radius:6px;align-self:flex-start}" +
            ".m.customer{background:" + c + ";color:#fff;border-bottom-right-radius:6px;align-self:flex-end}.m.customer a{color:#fff}" +
            ".m a{color:" + c + "}.who{font-size:11px;color:#6b7185;margin:-4px 0 2px 4px}" +
            ".n{align-self:center;font-size:12px;color:#5b6175;background:#eceef5;border-radius:999px;padding:5px 12px;text-align:center}" +
            ".typing{align-self:flex-start;background:#fff;border:1px solid #e6e8ef;border-radius:16px;padding:12px 14px;display:none}.typing.on{display:block}" +
            ".typing i{display:inline-block;width:6px;height:6px;margin:0 2px;border-radius:50%;background:#9aa0b4;animation:b 1s infinite}.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}" +
            "@keyframes b{0%,80%,100%{opacity:.3}40%{opacity:1}}" +
            ".chips{display:flex;flex-wrap:wrap;gap:6px;padding:8px 12px 0;background:#fff}" +
            ".chip{border:1px solid " + c + "55;color:" + c + ";background:#fff;border-radius:999px;padding:6px 12px;font-size:12.5px;cursor:pointer}.chip:hover{background:" + c + "12}" +
            ".foot{background:#fff;border-top:1px solid #eceef3;padding:10px 12px 8px}" +
            ".row{display:flex;gap:8px;align-items:flex-end}" +
            "textarea{flex:1;resize:none;border:1px solid #dfe2ea;border-radius:12px;padding:10px 12px;font-size:14px;max-height:110px;min-height:42px;color:#1f2433}textarea:focus,input:focus{outline:0;border-color:" + c + "}" +
            ".send{background:" + c + ";color:#fff;border:0;border-radius:12px;height:42px;padding:0 14px;font-weight:600;cursor:pointer}.send:disabled{opacity:.5;cursor:default}" +
            ".pb{text-align:center;font-size:11px;color:#9aa0b4;margin-top:6px}" +
            ".form{background:#fff;border:1px solid #e6e8ef;border-radius:14px;padding:12px;display:flex;flex-direction:column;gap:8px;align-self:stretch}" +
            ".form b{font-size:13.5px}.form input,.form textarea{width:100%;border:1px solid #dfe2ea;border-radius:10px;padding:9px 11px;font-size:14px;color:#1f2433}" +
            ".form .hp{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}.form .err{color:#c0392b;font-size:12px}" +
            ".end{align-self:center;background:#fff;border:1px solid " + c + ";color:" + c + ";border-radius:999px;padding:7px 14px;cursor:pointer;font-size:13px}" +
            "@media (max-width:520px){.panel{inset:0;width:100%;max-width:none;height:100%;max-height:none;border-radius:0}.launch{bottom:16px;" + (cfg.position === "left" ? "left" : "right") + ":16px}}";
    }
    function avatar() {
        return cfg.avatar ? '<img src="' + esc(cfg.avatar) + '" alt="">' :
            '<span class="ic" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span>';
    }
    function draw() {
        host = document.createElement("div");
        host.setAttribute("data-aie-chat", "");
        root = host.attachShadow ? host.attachShadow({mode: "open"}) : host;
        document.body.appendChild(host);
        var langs = cfg.languages.length > 1 ? '<select aria-label="Language">' + cfg.languages.map(function (l) {
            return '<option value="' + esc(l.code) + '"' + (l.code === lang ? " selected" : "") + ">" + esc(l.name) + "</option>"; }).join("") + "</select>" : "";
        root.innerHTML = "<style>" + css(cfg.color) + "</style>" +
            '<button class="launch" type="button" aria-haspopup="dialog" aria-expanded="false">' + avatar() + '<span class="lt"></span></button>' +
            '<div class="panel" role="dialog" aria-modal="false" aria-label="' + esc(cfg.title) + '">' +
            '<div class="head">' + avatar() + '<div class="t"><b>' + esc(cfg.title) + '</b><small class="st">' + esc(cfg.subtitle) + "</small></div>" + langs +
            '<button class="x" type="button" aria-label="Close">&times;</button></div>' +
            '<div class="body" aria-live="polite"><div class="typing" aria-hidden="true"><i></i><i></i><i></i></div></div>' +
            '<div class="chips"></div>' +
            '<div class="foot"><div class="row"><textarea rows="1" aria-label="Message"></textarea><button class="send" type="button"></button></div>' +
            (cfg.powered_by ? '<div class="pb">' + esc(cfg.powered_by) + "</div>" : "") + "</div></div>";
        ["launch", "panel", "body", "typing", "chips", "foot", "x", "send", "st"].forEach(function (k) { els[k] = root.querySelector("." + k); });
        els.input = root.querySelector("textarea");
        els.select = root.querySelector("select");
        els.launch.addEventListener("click", toggle);
        els.x.addEventListener("click", toggle);
        els.send.addEventListener("click", send);
        els.input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
        els.input.addEventListener("input", function () { els.input.style.height = "auto"; els.input.style.height = Math.min(els.input.scrollHeight, 110) + "px"; });
        root.addEventListener("keydown", function (e) { if (e.key === "Escape" && opened) toggle(); });
        if (els.select) els.select.addEventListener("change", function () { lang = els.select.value; save("lang", lang); labels(); });
        els.chips.addEventListener("click", function (e) { var b = e.target.closest("[data-a]"); if (b) act(b.getAttribute("data-a")); });
        labels();
    }
    function labels() {
        root.querySelector(".lt").textContent = T("launcher");
        els.input.placeholder = T("placeholder");
        els.send.textContent = T("send");
        els.chips.innerHTML = cfg.actions.map(function (a) { return '<button type="button" class="chip" data-a="' + a + '">' + esc(T(a)) + "</button>"; }).join("");
    }

    // ------------------------------------------------------------------ messages
    function bubble(m) {
        if (seen[m.id]) return;
        seen[m.id] = true;
        var el = document.createElement("div");
        if (m.role === "system") {
            if (!m.notice) return;
            el.className = "n";
            el.textContent = T(m.notice.replace(/^chat_/, "")).replace("{name}", m.name || "");
        } else {
            if (m.role === "human" && m.name) { var w = document.createElement("div"); w.className = "who"; w.textContent = m.name; els.body.insertBefore(w, els.typing); }
            el.className = "m " + m.role + (m.pending ? " pending" : "");
            el.innerHTML = rich(m.text);
        }
        els.body.insertBefore(el, els.typing);
        if (m.ask_contact && cfg.actions.indexOf("callback") > -1) form("callback");
    }
    function apply(d) {
        if ((d.messages || []).length) root.querySelectorAll(".pending").forEach(function (p) { p.remove(); });
        (d.messages || []).forEach(function (m) { bubble(m); last = m.id; });
        if (d.handled_by) els.st.textContent = d.handled_by === "human" && d.agent ? d.agent : cfg.subtitle;
        if (d.status === "ended") ended();
        els.body.scrollTop = els.body.scrollHeight;
    }
    function ended() {
        stop();
        els.foot.style.display = "none"; els.chips.style.display = "none";
        if (!root.querySelector(".end")) {
            var b = document.createElement("button"); b.type = "button"; b.className = "end"; b.textContent = T("restart");
            b.addEventListener("click", restart); els.body.insertBefore(b, els.typing);
        }
    }
    function restart() {
        token = ""; save("token", ""); last = ""; seen = {};
        Array.prototype.slice.call(els.body.children).forEach(function (c) { if (c !== els.typing) c.remove(); });
        els.foot.style.display = ""; els.chips.style.display = "";
        begin();
    }
    function fail() {
        var n = document.createElement("div"); n.className = "n"; n.textContent = T("error");
        els.body.insertBefore(n, els.typing); els.body.scrollTop = els.body.scrollHeight;
    }

    // ------------------------------------------------------------------ session, polling
    function begin() {
        if (token) return api("GET", "messages/").then(function (d) { apply(d); poll(); }, function (e) {
            if (e && e.status === 404) { token = ""; save("token", ""); return begin(); }
            fail();
        });
        return api("POST", "sessions/", {language: lang, page: location.href}).then(function (d) {
            token = d.token; save("token", token); startedAt = Date.now(); apply(d); poll();
        }, fail);
    }
    function poll() {
        stop();
        timer = setInterval(function () {
            if (!opened || document.hidden || busy || !token) return;
            api("GET", "messages/?after=" + encodeURIComponent(last)).then(apply, function () { /* offline: try again */ });
        }, Math.max(2, cfg.poll_seconds || 4) * 1000);
    }
    function stop() { if (timer) clearInterval(timer); timer = null; }
    function toggle() {
        opened = !opened;
        els.panel.classList.toggle("open", opened);
        els.launch.setAttribute("aria-expanded", String(opened));
        if (opened) {
            if (!last) begin(); else poll();
            setTimeout(function () { els.input.focus(); }, 50);
        } else stop();
    }
    function later(fn) {  // bot protection: the server ignores a first message sent within cfg.min_seconds
        var wait = (cfg.min_seconds || 0) * 1000 - (Date.now() - startedAt) + 200;
        if (startedAt && wait > 0) setTimeout(fn, wait); else fn();
    }
    function post(path, body) {
        busy = true; els.send.disabled = true; els.typing.classList.add("on"); els.body.scrollTop = els.body.scrollHeight;
        body = body || {}; body.after = last;
        return api("POST", path, body).then(apply, function (e) {
            if (e && e.status === 404) return restart();
            fail();
        }).then(function () { busy = false; els.send.disabled = false; els.typing.classList.remove("on"); });
    }
    function send(text) {
        text = typeof text === "string" ? text : els.input.value.trim();
        if (!text || busy || !token) return;
        if (typeof text === "string" && text === els.input.value.trim()) { els.input.value = ""; els.input.style.height = "auto"; }
        bubble({id: "local-" + Date.now(), role: "customer", text: text, pending: true});
        els.body.scrollTop = els.body.scrollHeight;
        later(function () { post("messages/", {text: text}); });
    }
    function act(a) {
        if (a === "human") return later(function () { post("human/"); });
        if (a === "book") return send(T("book"));
        form(a);
    }

    // ------------------------------------------------------------------ enquiry / callback form (CHAT-03)
    function form(kind) {
        if (root.querySelector(".form")) return;
        var f = document.createElement("form"); f.className = "form"; f.noValidate = true;
        f.innerHTML = "<b>" + esc(T(kind)) + "</b>" +
            '<input name="name" autocomplete="name" placeholder="' + esc(T("name")) + '" aria-label="' + esc(T("name")) + '" required>' +
            '<input name="phone" type="tel" autocomplete="tel" placeholder="' + esc(T("phone")) + '" aria-label="' + esc(T("phone")) + '" required>' +
            '<input name="email" type="email" autocomplete="email" placeholder="' + esc(T("email")) + '" aria-label="' + esc(T("email")) + '">' +
            '<textarea name="message" rows="2" placeholder="' + esc(T("message")) + '" aria-label="' + esc(T("message")) + '"></textarea>' +
            '<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">' +
            '<div class="err" role="alert"></div><button class="send" type="submit">' + esc(T("submit")) + "</button>";
        f.addEventListener("submit", function (e) {
            e.preventDefault();
            var data = {kind: kind, after: last};
            ["name", "phone", "email", "message", "website"].forEach(function (k) { data[k] = f.elements[k].value.trim(); });
            if (!data.name || !data.phone) { f.querySelector(".err").textContent = T("name") + " · " + T("phone"); return; }
            f.querySelector("button").disabled = true;
            api("POST", "contact/", data).then(function (d) { f.remove(); apply(d); }, function (err) {
                f.querySelector("button").disabled = false;
                var e2 = (err && err.data && err.data.error) || {};
                var msg = (Array.isArray(e2.details) && e2.details[0]) || e2.message;
                f.querySelector(".err").textContent = msg || T("error");
            });
        });
        els.body.insertBefore(f, els.typing);
        els.body.scrollTop = els.body.scrollHeight;
        f.elements.name.focus();
    }

    // ------------------------------------------------------------------ start
    function init() {
        fetch(BASE, {headers: {"Accept": "application/json"}, mode: "cors", credentials: "omit"}).then(function (r) { return r.ok ? r.json() : null; }).then(function (c) {
            if (!c) return;  // switched off, unknown key or not allowed on this website
            cfg = c;
            var codes = cfg.languages.map(function (l) { return l.code; });
            lang = load("lang");
            if (codes.indexOf(lang) < 0) {
                var nav = (navigator.language || "").slice(0, 2).toLowerCase();
                lang = codes.indexOf(nav) > -1 && nav !== "en" ? nav : cfg.language;
            }
            token = load("token");
            draw();
        }).catch(function () { /* the page keeps working without the chat */ });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
