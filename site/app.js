(() => {
  "use strict";
  // The release. tools/check.py holds it equal to the service worker's cache number (site/sw.js), and the pull request
  // check makes sure it goes up whenever the app's code changes, so phones notice the new code.
  const APP_VERSION = 33;
  document.documentElement.dataset.version = APP_VERSION;
  // Inside another site's page (there's no server, so no header can refuse that), the app shows nothing but a line
  // saying to open it directly: nothing here should be tapped through someone else's page.
  let framed = false;
  try { framed = window.top !== window.self; } catch (e) { framed = true; }
  if (framed) {
    document.body.textContent = "Open Twoo's Treat Temple directly, not inside another page.";
    return;
  }
  const DATA_KEY = "gf-data-v2";
  const SEL_KEY = "gf-selected";
  const FAV_KEY = "gf-favourites";
  const TIP_KEY = "gf-install-tip-dismissed";
  const SEEN_KEY = "gf-changes-seen"; // "<id>@<source>" for each "what's new" banner dismissed
  const REGION_KEY = "gf-region";
  const ALL = "all";
  const UK = "uk"; // the restaurant menus; any other region is a city in cities.json
  // the header's sections: Chains (the chains' menus, region UK), UK cities and Abroad (cities.json, by
  // "group"). Each city section goes back to the city last looked at in it.
  const UKC = "ukcity", INTL = "intl";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // An address from the data before it becomes a link: http(s), or a path of the app's own; anything with another
  // scheme (javascript:, data:) is dropped. tools/check.py refuses such an address at build time; this is the belt.
  // (control characters and spaces go first, since a browser drops them before it reads the scheme; a protocol-relative
  // address, //host, counts as another site's too)
  const safeUrl = (u) => { u = String(u || "").replace(/[\u0000- ]/g, ""); return /^https?:\/\//i.test(u) || !/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(u) ? u : ""; };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
    remove(k) { try { localStorage.removeItem(k); } catch (e) { /* storage unavailable */ } },
  };

  // A simple error log: the last few things that went wrong are kept on this phone (nowhere else, no outside service),
  // and Help can copy them with the app version and menu date to send to the owner.
  const ERR_KEY = "gf-errors";
  const ERR_MAX = 20;
  const errors = (() => { try { const a = JSON.parse(store.get(ERR_KEY) || "[]"); return Array.isArray(a) ? a.slice(-ERR_MAX) : []; } catch (e) { return []; } })();
  function logError(msg, where) {
    errors.push({ at: new Date().toISOString(), v: APP_VERSION, msg: String(msg || "Unknown error").slice(0, 300), where: String(where || "").slice(0, 120) });
    while (errors.length > ERR_MAX) errors.shift();
    store.set(ERR_KEY, JSON.stringify(errors));
    if (typeof renderErrors === "function") renderErrors();
  }
  window.addEventListener("error", (e) => {
    if (e.message) logError(e.message, (e.filename || "").split("/").pop() + (e.lineno ? ":" + e.lineno : ""));
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    logError("Unhandled: " + (r && r.message ? r.message : r), r && r.stack ? String(r.stack).split("\n")[1] || "" : "");
  });

  // state
  let data = null;               // { built, restaurants: [ full restaurant objects ] }
  let selected = ALL;            // restaurant id or ALL
  // the chip under the search box: everything, favourites, one section of a restaurant, or (on All) one restaurant or area
  let filter = { kind: "all" };  // { kind: "all" | "fav" | "section" | "restaurant" | "area", value }
  const sameFilter = (a, b) => a.kind === b.kind && (a.value || "") === (b.value || "");
  let favs = new Set(JSON.parse(store.get(FAV_KEY) || "[]"));
  // The service worker keeps a copy of the favourites (IndexedDB, which it can read; localStorage it can't), so a
  // notification about a new guide can say when a favourite now contains gluten.
  function mirrorFavs() {
    try {
      const open = indexedDB.open("gf", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("kv");
      open.onsuccess = () => { try { open.result.transaction("kv", "readwrite").objectStore("kv").put([...favs], "favs"); } catch (e) { /* not kept */ } };
    } catch (e) { /* no IndexedDB here */ }
  }
  function saveFavs() { store.set(FAV_KEY, JSON.stringify([...favs])); mirrorFavs(); }
  mirrorFavs();
  const firstVisit = !store.get(DATA_KEY); // a new user has nothing to compare, so no "what changed" banners
  let region = store.get(REGION_KEY) || UK;
  let cities = {};               // { <id>: { name, language, checked, list, tips, sections, places } }
  let cityFilter = "all";        // "all" | "open" | "fav" | section name
  let nearSort = false;          // city places sorted by distance from here
  let here = null;               // { lat, lon } from the phone, once asked
  const city = () => cities[region];
  let offlineNow = false;        // showing the copy saved on the phone because there's no signal
  const offlineTag = () => (offlineNow ? " · Offline: saved copy" : "");
  const PICK_KEY = "gf-pick";
  const THEME_KEY = "gf-theme";
  // Status buttons start unselected (show everything); selecting some narrows the list to those
  let pick = JSON.parse(store.get(PICK_KEY) || "null");
  if (!pick) { // carry over a choice saved by the older hide-by-tapping buttons ("gf-show")
    const old = Object.assign({ straight: true, change: true, gluten: true }, JSON.parse(store.get("gf-show") || "{}"));
    const all = old.straight && old.change && old.gluten;
    pick = { straight: !all && old.straight, change: !all && old.change, gluten: !all && old.gluten };
  }
  const picking = () => pick.straight || pick.change || pick.gluten;
  const visible = (k) => !picking() || pick[k];
  // "straight" = no gluten ingredients as served: asis/any/except (fine as served, or with any milk but the ones named); change = swap/modify;
  // "info" = an ingredient listed on its own (not something to order), which none of the status buttons count
  const kindOf = (i) => (!i.order ? "gluten" : i.role === "ingredient" ? "info" : (i.order === "swap" || i.order === "modify") ? "change" : "straight");

  // ---------- helpers ----------
  const byId = (id) => data && data.restaurants.find((r) => r.id === id);
  const favKey = (r, i) => r.id + "|" + i.section + "|" + i.name;
  const today = () => new Date().toISOString().slice(0, 10);
  const isStale = (r) => !!(r.guide && r.guide.validUntil && r.guide.validUntil < today());
  function shortSection(s) {
    const map = {
      "Iced Teas & Starbucks Refresha® Drink": "Iced Teas & Refreshas",
      "Frappuccino® Blended Beverage": "Frappuccino",
      "Syrups, Drizzles & Cream Cold Foams": "Syrups & toppings",
      "Protein Beverages": "Protein",
      "Pret's Hot": "Hot food",
    };
    return map[s] || s.replace(/®/g, "");
  }
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
    return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  // month and year only ("Mar 2024"), so a date in the chooser never breaks across two lines
  function fmtMonth(iso) {
    if (!iso) return "";
    const d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
    return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
  }
  const shortRuns = (s) => (s || "").replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*/g, "$1");
  const possessive = (name) => name + (/s$/.test(name) ? "'" : "'s");
  // a plain name for a guide, for the footer, Warnings and pop-ups. The raw file name (r.source) is kept
  // in Help, "Menus in this app", for the record.
  function plainGuideName(r) {
    const g = r.guide || {};
    const gs = r.guides && r.guides.length > 1 ? r.guides : [g]; // Starbucks: a drinks guide and a food guide
    const titles = gs.map((x) => x.title).filter((t) => t && t !== "Allergen guide").map((t) => t.toLowerCase());
    if (titles.length === gs.length) {
      return possessive(r.name) + " " + (titles.length > 1 ? titles.slice(0, -1).join(", ") + " and " + titles[titles.length - 1] + " guides" : titles[0] + " guide");
    }
    return possessive(r.name) + " allergen guide" + (g.version ? " (" + fmtDate(g.version) + ")" : "");
  }
  function listOr(arr, word = "or") {
    return arr.length < 2 ? arr.join("") : arr.slice(0, -1).join(", ") + " " + word + " " + arr[arr.length - 1];
  }
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  function guideLine(r) {
    const g = r.guide || {};
    const season = (g.title || "").replace(/\s*Beverages$/, "");
    const named = season && season !== "Allergen guide";
    return [named ? season + " menu" : "", shortRuns(g.runs) || (g.version && !named ? "Guide " + fmtMonth(g.version) : "")]
      .filter(Boolean).join(" · ");
  }
  function tagFor(r, i) {
    const label = r.optionLabel || "option";
    if (i.role === "ingredient") return ["t-info", "Ingredient"];
    switch (i.order) {
      case "asis": return ["t-asis", "No gluten ingredients"];
      case "any": return ["t-any", "Any " + label];
      case "swap": return ["t-swap", "Swap " + label];
      case "modify": return ["t-swap", "Ask"];
      default: return ["t-any", "Any " + label + " except " + i.not.join(", ")];
    }
  }
  const pageText = (p) => (!p || !p.length ? "" : (p.length > 1 ? "Guide pages " : "Guide page ") + p.join(", "));
  // a restaurant's own mark (restaurants/<id>/logo.png, the icon its site publishes) or, without one, a lettered badge
  const logoHtml = (name, src, cls) => '<span class="logo-wrap' + (safeUrl(src) ? "" : " none") + (cls ? " " + cls : "") + '" aria-hidden="true">' +
    (safeUrl(src) ? '<img class="logo" src="' + esc(safeUrl(src)) + '" alt="">' : "") +
    '<span class="mono">' + esc(String(name || "?").replace(/^(the|a)\s+/i, "").charAt(0).toUpperCase()) + "</span></span>";
  // a mark that doesn't load (offline before it was ever seen) leaves the lettered badge showing
  document.addEventListener("error", (e) => { const w = e.target && e.target.closest && e.target.closest(".logo-wrap"); if (w) w.classList.add("broken"); }, true);

  // ---------- what changed: the guide's own list (r.changes, built by tools/changes.py) and since you last looked ----------
  // The phone keeps each restaurant's menu as it was when you last dismissed its "new guide" note (or first had it), and
  // compares the newest menu with that (site/compare.js, the same comparison as tools/changes.py). So if a chain brings
  // out two guides between your visits, what changed in the first isn't lost under the second.
  const LOOKED_KEY = "gf-looked";
  const looked = (() => { try { return JSON.parse(store.get(LOOKED_KEY) || "{}") || {}; } catch (e) { return {}; } })();
  const keepOnly = (o, keys) => { const out = {}; keys.forEach((k) => { if (o[k] !== undefined) out[k] = o[k]; }); return out; };
  const snapshot = (r) => ({ source: r.source, guide: keepOnly(r.guide || {}, ["title", "version"]),
    items: r.items.map((i) => keepOnly(i, ["name", "section", "order", "ok", "not", "note"])),
    avoid: r.avoid.map((a) => keepOnly(a, ["name", "section", "gluten"])) });
  // remember these restaurants as you see them now; onlyNew: only those the phone has no copy of yet
  function setLooked(rs, onlyNew) {
    let any = false;
    for (const r of rs) if (!onlyNew || !looked[r.id]) { looked[r.id] = snapshot(r); any = true; }
    if (any) store.set(LOOKED_KEY, JSON.stringify(looked));
  }
  const sinceCache = new WeakMap();
  function sinceLooked(r) {
    const base = looked[r.id];
    if (!base || base.source === r.source || typeof self.gfCompare !== "function") return null;
    const hit = sinceCache.get(r);
    if (hit && hit.base === base) return hit.c;
    const c = self.gfCompare(base, r);
    sinceCache.set(r, { base, c });
    return c;
  }
  const KINDS = ["nowAvoid", "nowOk", "changed", "added", "removed"];
  const namesIn = (c, k) => (c[k] || []).map((x) => x.section + "|" + x.name).sort().join("\n");
  // the two lists start from the same guide and say the same: show one. Otherwise both show, so nothing is hidden.
  const agree = (a, b) => !!(a && b && a.sinceSource === b.sinceSource && KINDS.every((k) => namesIn(a, k) === namesIn(b, k)));
  const chgCache = new WeakMap();
  function changeOf(r, i) {
    const mine = sinceLooked(r);
    if (!r.changes && !mine) return null;
    let m = chgCache.get(r);
    if (!m || m.mine !== mine) {
      const map = new Map();
      // since you last looked first; the guide's own list fills in the rest (an item can only be marked once)
      for (const [c, own] of [[mine, true], [r.changes, false]]) {
        if (!c) continue;
        for (const kind of ["added", "changed", "nowOk", "nowAvoid"]) {
          (c[kind] || []).forEach((x) => { const k = x.section + "|" + x.name; if (!map.has(k)) map.set(k, { kind, ...x, since: c.since, own }); });
        }
      }
      m = { mine, map };
      chgCache.set(r, m);
    }
    return m.map.get(i.section + "|" + i.name) || null;
  }
  const howText = (r, h) => tagFor(r, h)[1] + (h.order === "modify" ? ": " + h.note : "");
  const CHG_LABEL = { added: "New", changed: "Order changed", nowOk: "No longer to avoid", nowAvoid: "Now contains gluten" };
  function changeNote(r, c) {
    const since = "the " + esc(c.since) + " guide" + (c.own ? " you last looked at" : "");
    if (c.kind === "added") return "<div class=\"chg-note\"><b>New</b> since " + since + ".</div>";
    if (c.kind === "nowOk") return "<div class=\"chg-note\"><b>No longer to avoid.</b> It was on the Avoid list in " + since + ".</div>";
    if (c.kind === "nowAvoid") return "<div class=\"chg-note bad\"><b>Now contains gluten.</b> It had no gluten ingredients in " + since + ".</div>";
    return "<div class=\"chg-note\"><b>Ordered differently since " + since + ":</b> it was " + esc(howText(r, c.was)) + ".</div>";
  }
  const chev = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  // rows that aren't things to order as they are (restaurant.json "roles"): no staff card, and they say why
  const ROLE_NOTE = {
    part: "Part of other dishes, listed on its own in the guide. It isn't something to order as it is, so there's no staff card for it on its own: add it to an order for one card with everything on it.",
    ingredient: "An ingredient, listed on its own in the guide. It isn't something to order as it is, so there's no staff card for it.",
  };

  // ---------- personal notes on items and places: kept on this phone, and carried in the favourites link ----------
  const NOTES_KEY = "gf-notes"; // { <favourite key>: text }
  const NOTE_MAX = 300;
  const notes = (() => { try { const o = JSON.parse(store.get(NOTES_KEY) || "{}"); return o && typeof o === "object" && !Array.isArray(o) ? o : {}; } catch (e) { return {}; } })();
  const noteOf = (k) => (typeof notes[k] === "string" ? notes[k] : "");
  function setNote(k, text) {
    text = String(text || "").slice(0, NOTE_MAX);
    if (text.trim()) notes[k] = text; else delete notes[k];
    store.set(NOTES_KEY, JSON.stringify(notes));
  }
  const noteMark = (k) => (noteOf(k) ? '<span class="note-mark">✎<span class="vh"> has a note</span></span>' : "");
  const noteBox = (k) => '<label class="note-box">Your note<textarea data-note="' + esc(k) + '" rows="1" maxlength="' + NOTE_MAX +
    '" placeholder="e.g. ask for a clean jug">' + esc(noteOf(k)) + "</textarea></label>";
  // typing saves after a short pause (one timer per note, so a second box doesn't lose the first), and the row's mark follows
  const noteTimers = {};
  document.addEventListener("input", (e) => {
    const t = e.target.closest && e.target.closest("textarea[data-note]");
    if (!t) return;
    clearTimeout(noteTimers[t.dataset.note]);
    noteTimers[t.dataset.note] = setTimeout(() => {
      setNote(t.dataset.note, t.value);
      const nm = t.closest(".row") && t.closest(".row").querySelector(".nm");
      if (!nm) return;
      const m = nm.querySelector(".note-mark");
      if (noteOf(t.dataset.note) && !m) nm.insertAdjacentHTML("afterbegin", noteMark(t.dataset.note));
      if (!noteOf(t.dataset.note) && m) m.remove();
    }, 300);
  });

  // "Guide page 7" opens the guide itself at that page (the guides are published with the app; whether the phone's
  // PDF viewer jumps to the page is up to it). Starbucks has two guides, so a row says which one its pages are in.
  const guideFile = (r, i) => { const files = r.guideFiles || {}; const src = r.guides && i.src != null ? (r.guides[i.src] || {}).source : r.source; return safeUrl(files[src]); };
  function guideLinkHtml(r, i) {
    const text = pageText(i.pages), file = guideFile(r, i);
    if (!text) return "<span></span>";
    if (!file) return "<span>" + esc(text) + "</span>";
    return '<a class="guide-link" href="' + esc(file + "#page=" + i.pages[0]) + '" target="_blank" rel="noopener">' + esc(text) + '<span class="vh">, opens the guide</span> &rsaquo;</a>';
  }

  // How the app decided an item where the guide wasn't plain (the readers' notes, in plain English)
  const decidedNote = (i) => '<div class="decided"><b>How the app decided:</b> ' + esc(i.decided) + "</div>";
  // the guide page, "Share this item" (a link that opens straight to it) and "Something wrong?" (a ready message to send),
  // on one line under the buttons, so Show staff and its neighbours have the full width
  const moreLinks = (r, i) => '<div class="detail-more">' + guideLinkHtml(r, i) + '<button type="button" class="link-btn" data-share-item="' + esc(itemRef(r, i)) +
    '">Share this item</button><button type="button" class="link-btn" data-wrong="' + esc(itemRef(r, i)) + '">Something wrong?</button></div>';
  function detailFor(r, i) {
    const out = [];
    const c = changeOf(r, i);
    if (c) out.push(changeNote(r, c));
    if (i.role) out.push("<div>" + ROLE_NOTE[i.role] + "</div>");
    if (i.original) {
      out.push('<div>On the menu as <b lang="' + esc(r.language || "") + '">' + esc(i.original) + "</b>" +
        (i.sectionOriginal ? ' under <span lang="' + esc(r.language || "") + '">' + esc(i.sectionOriginal) + "</span>" : "") + "</div>");
    }
    if (i.info) out.push("<div>" + esc(i.info) + "</div>");
    if (i.decided) out.push(decidedNote(i));
    if (i.order === "asis") out.push(i.role ? "<div>No gluten ingredients as listed.</div>" : "<div>No gluten ingredients as listed. No changes needed.</div>");
    if (i.order === "modify") out.push("<div><b>Ask for:</b> " + esc(i.note) + "</div>");
    if (i.order === "swap") {
      const std = i.standard || "";
      out.push(i.standardFrom === "guide"
        ? "<div><b>Comes with " + esc(std) + " as standard.</b> Ask for " + esc(listOr(i.ok)) + ".</div>"
        : "<div><b>Usually made with " + esc(std) + "</b> (going by its name). Ask for " + esc(listOr(i.ok)) + ".</div>");
    }
    if (i.ok) {
      out.push('<div class="milks">' + i.ok.map((m) => '<span class="milk">' + esc(m) + "</span>").join("") +
        (i.not || []).map((m) => '<span class="milk no"><span class="vh">not </span>' + esc(m) + "</span>").join("") + "</div>");
    }
    const k = favKey(r, i);
    const on = favs.has(k);
    const inOrder = canOrder(i) && (orders[r.id] || []).includes(k);
    out.push(noteBox(k));
    // Show staff is the one that matters at a counter, so it's the filled button and the row has the full width
    out.push('<div class="detail-foot"><span class="foot-btns">' +
      (canOrder(i) ? '<button type="button" class="order-btn" data-order="' + esc(k) + '" aria-pressed="' + inOrder + '">' + (inOrder ? "✓ In order" : "Add to order") + "</button>" : "") +
      (i.role ? "" : '<button type="button" class="staff-btn" data-staff="' + esc(k) + '">Show staff</button>') + '<button type="button" class="fav-btn" data-fav="' + esc(k) +
      '" aria-pressed="' + on + '">' + (on ? "★ Saved" : "☆ Save") + "</button></span></div>");
    out.push(moreLinks(r, i));
    return out.join("");
  }

  function rowHtml(r, i, showRestaurant) {
    const [cls, label] = tagFor(r, i);
    const star = favs.has(favKey(r, i)) ? '<span class="star" aria-label="Favourite">★</span>' : "";
    const subs = [];
    const c = changeOf(r, i);
    if (c) subs.push('<span class="chg">' + CHG_LABEL[c.kind] + "</span>");
    if (i.role === "part") subs.push("Part of a dish");
    if (i.order === "modify") subs.push(esc(i.note));
    if (i.original) subs.push('<span lang="' + esc(r.language || "") + '">' + esc(i.original) + "</span>");
    if (showRestaurant) subs.push(esc(r.name));
    const sub = subs.length ? "<small>" + subs.join(" · ") + "</small>" : "";
    // the tag sits under the name, so even "Any milk except oat, almond, coconut" has the full width
    return '<details class="row" data-slug="' + esc(itemSlug(r, i)) + '"><summary><span class="nm">' + star + noteMark(favKey(r, i)) + esc(i.name) + sub + '<span class="tag ' + cls + '">' +
      esc(label) + "</span></span>" + chev + '</summary><div class="detail">' + detailFor(r, i) + "</div></details>";
  }

  // Search: every word must match (in English or the original language). Words like "gluten free" / "gf" are
  // ignored because everything listed is already sorted by gluten, and so are articles ("a latte" means lattes);
  // plurals match singulars ("toasties" -> "toastie").
  const STOP = new Set(["gluten", "free", "gf", "glutenfree", "gluten-free", "no", "without", "and", "with", "a", "an", "the"]);
  const stem = (w) => w.replace(/ies$/, "ie").replace(/(ches|shes|xes)$/, (m) => m.slice(0, -2)).replace(/([^s])s$/, "$1");
  const norm = (t) => t.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  function terms(q) { return norm(q).split(/[^a-z0-9ßäöü]+/).filter((w) => w && !STOP.has(w)).map(stem); }
  // everyday words for the same thing as a menu word, so "chips" finds "fries" (one-way: not the reverse)
  const ALIAS = { chip: ["frie"] };
  // each row's searchable words, worked out once: the search runs over every row on every keystroke
  // notes ("info") aren't searched: "wheat" shouldn't find dishes whose note merely mentions wheat
  const wordsCache = new WeakMap();
  function wordsOf(i) {
    let words = wordsCache.get(i);
    if (!words) {
      words = norm([i.name, i.sub, i.note, i.original, i.section, ...(i.ok || [])].filter(Boolean).join(" ")).split(/[^a-z0-9ßäöü]+/).map(stem);
      wordsCache.set(i, words);
    }
    return words;
  }
  const matches = (i, q) => {
    const ts = typeof q === "string" ? terms(q) : q;
    if (!ts.length) return true;
    const words = wordsOf(i); // match at the start of words, so "latte" doesn't find "platter"
    return ts.every((t) => words.some((w) => w.startsWith(t) || (ALIAS[t] || []).some((a) => w.startsWith(a))));
  };
  // A stable link to one item: #<restaurant>/<slug>. A name used more than once also gets its section (and version).
  const slugOf = (s) => norm(s).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const slugCache = new WeakMap();
  function itemSlug(r, i) {
    let m = slugCache.get(r);
    if (!m) {
      m = new Map();
      const byName = {};
      r.items.concat(r.avoid).forEach((x) => { (byName[slugOf(x.name)] = byName[slugOf(x.name)] || []).push(x); });
      for (const [base, group] of Object.entries(byName)) {
        group.forEach((x) => {
          let sl = base;
          if (group.length > 1) {
            sl += "--" + slugOf(x.section);
            if (group.filter((y) => y.section === x.section).length > 1) {
              if (x.sub) sl += "-" + slugOf(x.sub);
              const twins = group.filter((y) => y.section === x.section && (y.sub || "") === (x.sub || ""));
              if (twins.length > 1) sl += "-" + (twins.indexOf(x) + 1);
            }
          }
          m.set(x, sl);
        });
      }
      slugCache.set(r, m);
    }
    return m.get(i);
  }
  const itemRef = (r, i) => r.id + "/" + itemSlug(r, i);
  function itemByRef(ref) {
    const [rid, sl] = ref.split("/");
    const r = byId(rid);
    return { r, i: r && r.items.concat(r.avoid).find((x) => itemSlug(r, x) === sl) };
  }
  const appUrl = () => location.origin + location.pathname.replace(/index\.html$/, "");
  const itemUrl = (r, i) => appUrl() + "#" + itemRef(r, i);
  const areas = () => [...new Set(data.restaurants.map((r) => r.area).filter(Boolean))];
  const scope = () => (selected === ALL ? data.restaurants : [byId(selected)].filter(Boolean));

  // ---------- rendering ----------
  // The Avoid list opens by itself while searching (or when its status button is chosen). A tap on its heading wins
  // over that until the next search, status button or restaurant.
  let avoidUser = null;
  $("avoidWrap").querySelector("summary").addEventListener("click", (e) => {
    e.preventDefault();
    avoidUser = !$("avoidWrap").open;
    $("avoidWrap").open = avoidUser;
  });
  function renderHeader() {
    const r = byId(selected);
    if (r) {
      $("pickName").innerHTML = logoHtml(r.name, r.logo, "logo-s") + esc(r.name);
      $("pickBtn").setAttribute("aria-label", r.name + ". Choose where to eat");
      $("guideLine").textContent = (guideLine(r) || r.covers) + offlineTag();
      $("q").placeholder = "Search " + r.name;
    } else {
      $("pickName").textContent = "All restaurants";
      $("pickBtn").setAttribute("aria-label", "All restaurants. Choose where to eat");
      const n = data.restaurants.length;
      $("guideLine").textContent = n + (n === 1 ? " restaurant" : " restaurants") + offlineTag();
      $("q").placeholder = "Search all restaurants";
    }
  }

  // a chip: its kind and value as data attributes, which the click handler reads back
  const chipHtml = (kind, value, label, pressed) => '<button type="button" data-kind="' + esc(kind) + '"' + (value ? ' data-value="' + esc(value) + '"' : "") +
    ' aria-pressed="' + pressed + '">' + esc(label) + "</button>";
  function renderChips() {
    const chips = [{ kind: "all", label: "All" }, { kind: "fav", label: "★ Favourites" }];
    if (selected === ALL) {
      const as = areas();
      if (as.length > 1) as.forEach((a) => chips.push({ kind: "area", value: a, label: a }));
      if (data.restaurants.length > 1) data.restaurants.forEach((r) => chips.push({ kind: "restaurant", value: r.id, label: r.name }));
    } else {
      const r = byId(selected);
      r.sections.filter((s) => r.items.some((i) => i.section === s) || r.avoid.some((a) => a.section === s))
        .forEach((s) => chips.push({ kind: "section", value: s, label: shortSection(s) }));
    }
    if (!chips.some((c) => sameFilter(c, filter))) filter = { kind: "all" };
    // on a restaurant's page the order builder is a chip after Favourites: it costs no height above the menu
    const r = byId(selected);
    // "Near me" (which chains are within a kilometre) sits after Favourites on every page; with the look-around switched
    // on it reads off the nearest chain, where it costs no height above the menu
    const nearChip = osmChains().length ? '<button type="button" data-near-uk>' + esc(nearChipText(r)) + "</button>" : "";
    $("chips").innerHTML = chips.map((c) => chipHtml(c.kind, c.value, c.label, sameFilter(c, filter)) +
      (c.kind === "fav" ? (r ? '<button type="button" data-order-open>' + orderChipText(r) + "</button>" : "") + nearChip : "")).join("");
    $("chips").hidden = false; // a city with a few places hides the row
  }
  const orderChipText = (r) => { const n = orderItems(r).length; return n ? "Your order (" + n + ") &rsaquo;" : "Build an order"; };

  function renderBanners() {
    const stale = scope().filter(isStale);
    $("stale").hidden = !stale.length;
    // on All it's one line pointing to the restaurant; the full banner stays on that restaurant's own page
    if (selected === ALL) {
      $("stale").innerHTML = stale.map((r) => '<button type="button" class="stale-line" data-gotorest="' + esc(r.id) + '"><b>' + esc(r.name) +
        ' guide may be out of date</b> <span class="go">&rsaquo;</span></button>').join("");
    } else $("stale").innerHTML = stale.map((r) =>
      "<p><b>" + esc(r.name) + " guide may be out of date.</b> It covered up to " + esc(fmtDate(r.guide.validUntil)) +
      ". Check in store before ordering" + (safeUrl(r.officialUrl) ? ', or see <a href="' + esc(safeUrl(r.officialUrl)) + '" target="_blank" rel="noopener">their allergen info</a>' : "") + "." +
      (r.latestGuide ? " " + esc(r.latestGuide.note) + " (checked " + esc(fmtDate(r.latestGuide.checked)) + ")" : "") + "</p>").join("");
    renderFavAlerts();
    renderNews();
    renderCertNote();
    renderCardLaunch();
    const r = byId(selected);
    const tips = (r && r.tips) || [];
    const full = introFull(MENUS);
    // on All, an out-of-date guide is a few words in the folded line and the chooser's Out of date tag (the Warnings
    // sheet says which guide); the full banner stays on that restaurant's own page
    if (selected === ALL) $("stale").hidden = true;
    // with the card in full, only the first tip shows above the menu; folded, the restaurant's headline tip leads the
    // line ("Never oat milk."); every tip is in the Tips and warnings sheet
    $("tips").hidden = !full || !tips.length;
    $("tips").innerHTML = tipsHtml(tips.slice(0, 1));
    $("certNote").hidden = !full;
    $("openStrip").hidden = full;
    $("stripText").innerHTML = (r && r.headline ? "<b>" + esc(r.headline) + "</b> " : "") + esc(certShort(scope())) +
      (selected === ALL && stale.length ? " " + stale.length + (stale.length === 1 ? " guide" : " guides") + " may be out of date." : "");
    $("stripLabel").textContent = tips.length ? "Tips and warnings" : "Warnings";
  }
  const tipsHtml = (tips) => tips.map((t) => {
    const m = t.match(/^([^:.]+[:.])\s+(.+)$/);
    return "<div>" + (m ? "<b>" + esc(m[1]) + "</b> " + esc(m[2]) : esc(t)) + "</div>";
  }).join("");

  // The first menu page ever opened (a restaurant, or All) shows the certified-or-not card in full, once; every
  // other time it's one line (#strip) above the menu, with every word of it and the tips in the Tips and warnings
  // sheet. A city's introduction folds the same way, per city.
  const INTRO_KEY = "gf-intro-seen";
  const MENUS = "menus"; // the menus' card is read once, not once per restaurant: the food comes first
  const introNow = new Set(); // shown in full during this visit, so the card doesn't fold away while it's being read
  function introFull(key) { // MENUS, or a city (its introduction folds the same way)
    if (introNow.has(key)) return true;
    const seen = new Set(JSON.parse(store.get(INTRO_KEY) || "[]"));
    // a phone from before release 33 marked each restaurant (and All) it had seen: any of those means the card was read
    if (seen.has(key) || (key === MENUS && [...seen].some((k) => !cities[k]))) return false;
    seen.add(key);
    store.set(INTRO_KEY, JSON.stringify([...seen]));
    introNow.add(key);
    return true;
  }
  $("introDone").addEventListener("click", () => { introNow.delete(MENUS); renderBanners(); });
  $("cityStrip").addEventListener("click", () => { introNow.add(region); renderCity(); }); // the folded city introduction, in full for this visit
  // The certified-or-not card in a few words, for the folded line
  function certShort(rs) {
    const claim = rs.filter((r) => (r.notices || []).some((n) => n.kind === "accreditation"));
    if (!claim.length) return "Not certified gluten free.";
    const names = listOr(claim.map((r) => r.name)).replace(/ or /, " and ");
    return (rs.length === 1 ? "" : "Only ") + names + (claim.length === 1 ? " says it's" : " say they're") + " accredited by Coeliac UK.";
  }

  // Saved favourites that are now on the Avoid list, or missing from the latest guide. These stay until removed.
  function favProblems() {
    const out = [];
    let moved = false;
    for (const k of [...favs]) {
      const [rid, section, ...rest] = k.split("|");
      const name = rest.join("|");
      const r = byId(rid);
      if (!r || r.items.some((i) => i.section === section && i.name === name)) continue;
      const same = r.items.filter((i) => norm(i.name) === norm(name));
      if (same.length === 1) { // only its section was renamed: follow it quietly
        favs.delete(k);
        favs.add(favKey(r, same[0]));
        moved = true;
        continue;
      }
      const a = r.avoid.find((x) => x.section === section && x.name === name) || r.avoid.find((x) => norm(x.name) === norm(name));
      out.push({ k, r, name, section, avoid: a });
    }
    if (moved) saveFavs();
    return out;
  }
  function renderFavAlerts() {
    const ids = new Set(scope().map((r) => r.id));
    const all = favProblems();
    const here = all.filter((p) => ids.has(p.r.id));
    const elsewhere = all.filter((p) => !ids.has(p.r.id));
    $("favAlert").hidden = !all.length;
    let html = here.map((p) => "<div class=\"fa-row\"><p>★ <b>" + esc(p.name) + "</b> (" + esc(shortSection(p.section)) + ") at " + esc(p.r.name) + (p.avoid
      ? " is now on the Avoid list: " + esc((p.avoid.reason || "contains " + p.avoid.gluten.join(" and ").toLowerCase()).replace(/\.$/, "")) + "."
      : " isn't in the latest guide. Check in store before ordering it.") +
      '</p><button type="button" class="link-btn" data-unfav="' + esc(p.k) + '">Remove from favourites</button></div>').join("");
    // On other pages, just a line pointing to where the full warning is (All, or that restaurant's page)
    if (elsewhere.length) {
      const names = [...new Set(elsewhere.map((p) => p.r.name))];
      const rid = elsewhere[0].r.id;
      html += '<div class="fa-row"><p><button type="button" class="link-btn" data-gotorest="' + esc(rid) + '">' +
        elsewhere.length + (elsewhere.length === 1 ? " saved item" : " saved items") + " at " + esc(listOr(names)) +
        (elsewhere.length === 1 && names.length === 1 ? " has" : " have") + " changed &rsaquo;</button></p></div>";
    }
    $("favAlert").innerHTML = html;
  }
  $("favAlert").addEventListener("click", (e) => {
    const un = e.target.closest("[data-unfav]");
    if (un) { favs.delete(un.dataset.unfav); saveFavs(); render(); return; }
    const go = e.target.closest("[data-gotorest]");
    if (go) select(go.dataset.gotorest);
  });

  $("stale").addEventListener("click", (e) => { const go = e.target.closest("[data-gotorest]"); if (go) select(go.dataset.gotorest); });

  const seen = () => new Set(JSON.parse(store.get(SEEN_KEY) || "[]"));
  const counts = (c) => [["nowAvoid", "now contain gluten"], ["nowOk", "no longer to avoid"], ["changed", "ordered differently"],
    ["added", "new"], ["removed", "gone"]].filter(([k]) => (c[k] || []).length).map(([k, l]) => c[k].length + " " + l);
  // what the note says: what changed since you last looked if anything did, else the guide's own list until dismissed
  function newsFor(r, s) {
    const mine = sinceLooked(r);
    if (mine && counts(mine).length) return mine;
    if (r.changes && counts(r.changes).length && !s.has(r.id + "@" + r.source)) return r.changes;
    return null;
  }
  // more than one guide since you last looked: the guide's own list starts later than your copy
  const skipped = (r, c) => c === sinceLooked(r) && !!r.changes && r.changes.sinceSource !== c.sinceSource;
  // The question at the counter: did my favourites here survive the new guide? Said from the same comparison the note
  // comes from, so "unchanged" means not in its changed, now-avoid or gone lists.
  function favLine(r, c) {
    const mine = [...favs].filter((k) => k.startsWith(r.id + "|")).map((k) => k.split("|").slice(1).join("|"));
    if (!mine.length) return "";
    const inList = (kind) => mine.filter((m) => (c[kind] || []).some((x) => x.section + "|" + x.name === m)).length;
    // not on the list any more, whenever it went (favourites are kept until removed): now to avoid, gone, or long gone
    const changed = inList("changed"), bad = mine.filter((m) => !r.items.some((i) => i.section + "|" + i.name === m)).length;
    if (!changed && !bad) return " Your " + (mine.length === 1 ? "favourite here is" : mine.length + " favourites here are") + " unchanged.";
    const parts = [];
    if (changed) parts.push(changed + " of your favourites " + (changed === 1 ? "is" : "are") + " ordered differently: see Your usuals");
    if (bad) parts.push(bad + " of your favourites " + (bad === 1 ? "is" : "are") + " now on the Avoid list or gone: see the warning above");
    return " " + parts.join("; ") + ".";
  }
  // A restaurant this phone hasn't seen before gets a note until it's opened or dismissed, and a New tag in the chooser;
  // the first time the app ever loads, nothing is new.
  const KNOWN_KEY = "gf-known-restaurants"; // { <id>: { seen: ISO date, new: true until opened or dismissed } }
  const known = (() => { try { const o = JSON.parse(store.get(KNOWN_KEY) || "{}"); return o && typeof o === "object" && !Array.isArray(o) ? o : {}; } catch (e) { return {}; } })();
  function noteNewRestaurants(rs) {
    const first = !Object.keys(known).length;
    let any = false;
    for (const r of rs) if (!known[r.id]) { known[r.id] = { seen: new Date().toISOString(), new: !first }; any = true; }
    if (any) store.set(KNOWN_KEY, JSON.stringify(known));
  }
  const isNew = (r) => !!(known[r.id] && known[r.id].new);
  function sawRestaurant(id) { if (known[id] && known[id].new) { known[id].new = false; store.set(KNOWN_KEY, JSON.stringify(known)); } }
  const askedFor = (r) => requests.some((q) => sameName(q.name, r.name) || (Array.isArray(r.osm) && r.osm.some((o) => sameName(o, q.name))));
  function renderNews() {
    const s = seen();
    const news = scope().map((r) => [r, newsFor(r, s)]).filter(([, c]) => c);
    const fresh = scope().filter(isNew);
    $("news").hidden = !news.length && !fresh.length;
    $("news").innerHTML = fresh.map((r) => '<div class="news-row"><p><b>' + esc(r.name) + " is new here" + (askedFor(r) ? ", and you asked for it" : "") + ".</b> " +
      esc(r.stats.items) + ' items with no gluten ingredients.</p><p class="news-btns">' +
      (selected === ALL ? '<button type="button" class="pill-btn" data-gotorest="' + esc(r.id) + '">Open</button>' : "") +
      '<button type="button" class="link-btn" data-seen-new="' + esc(r.id) + '">Dismiss</button></p></div>').join("") +
      news.map(([r, c]) => '<div class="news-row' + (c.nowAvoid.length ? " bad" : "") + '"><p><b>' + esc(r.name) +
      (skipped(r, c) ? " has new guides.</b> Since the " + esc(c.since) + " guide you last looked at: " : " has a new guide.</b> Since " + esc(c.since) + ": ") +
      esc(counts(c).join(", ")) + "." + esc(favLine(r, c)) + '</p><p class="news-btns">' +
      '<button type="button" class="pill-btn" data-news="' + esc(r.id) + '">See what changed</button>' +
      '<button type="button" class="link-btn" data-seen="' + esc(r.id) + '">Dismiss</button></p></div>').join("");
  }
  $("news").addEventListener("click", (e) => {
    const open = e.target.closest("[data-news]");
    if (open) { openChanges(byId(open.dataset.news)); return; }
    const go = e.target.closest("[data-gotorest]");
    if (go) { select(go.dataset.gotorest); return; }
    const done = e.target.closest("[data-seen-new]");
    if (done) { sawRestaurant(done.dataset.seenNew); renderNews(); return; }
    const b = e.target.closest("[data-seen]");
    if (!b) return;
    const r = byId(b.dataset.seen);
    const s = seen();
    s.add(r.id + "@" + r.source);
    store.set(SEEN_KEY, JSON.stringify([...s]));
    setLooked([r]); // seen: the next comparison starts from this menu
    renderNews();
    if (region === UK) renderList();
  });
  function openChanges(r) {
    if (!r) return;
    const mine = sinceLooked(r), theirs = r.changes;
    const showMine = !!mine && (counts(mine).length > 0 || mine.newAvoid > 0);
    const showTheirs = !!theirs && !(showMine && agree(mine, theirs));
    if (!showMine && !showTheirs) return;
    const list = (title, arr, fn, cls) => arr && arr.length ? "<h3" + (cls ? ' class="' + cls + '"' : "") + ">" + title + " (" + arr.length + ")</h3><ul class=\"chg-list\">" +
      arr.map((x) => "<li><b>" + esc(x.name) + "</b> <span class=\"muted\">" + esc(shortSection(x.section)) + "</span>" + (fn ? fn(x) : "") + "</li>").join("") + "</ul>" : "";
    const part = (c, intro) => '<p class="muted">' + intro + "</p>" +
      list("Now contain gluten", c.nowAvoid, (x) => x.gluten && x.gluten.length ? ": " + esc(x.gluten.map(cap).join(" & ")) : "", "bad") +
      list("Ordered differently", c.changed, (x) => ": was " + esc(howText(r, x.was)) + ", now " + esc(howText(r, x.now))) +
      list("No longer to avoid", c.nowOk) + list("New", c.added) +
      list("Gone from the guide", c.removed) +
      (c.newAvoid ? "<p class=\"muted\">Plus " + c.newAvoid + " new " + (c.newAvoid === 1 ? "item" : "items") + " on the Avoid list.</p>" : "");
    const both = showMine && showTheirs;
    $("changesTitle").textContent = r.name + ": what changed";
    $("changesBody").innerHTML =
      (showMine ? (both ? '<h4 class="chg-part">Since you last looked</h4>' : "") +
        part(mine, "Compared with the " + esc(mine.since) + " guide, the last one you looked at.") : "") +
      (showTheirs ? (both ? '<h4 class="chg-part">This guide\'s own list</h4>' : "") +
        part(theirs, "Compared with the " + esc(theirs.since) + " guide. Noticed " + esc(fmtDate(theirs.date)) + ".") : "");
    openDialog($("changes"));
  }

  // The note under the search box, adjusted when a restaurant's own guide makes a gluten free claim.
  function renderCertNote() {
    const rs = scope();
    const claim = rs.filter((r) => (r.notices || []).some((n) => n.kind === "accreditation"));
    const names = (arr) => listOr(arr.map((r) => r.name)).replace(/ or /, " and ");
    $("certText").innerHTML = "<b>No gluten ingredients isn't the same as certified gluten free.</b> " + (claim.length
      ? esc(names(claim)) + (claim.length === 1 ? " says it's" : " say they're") + " accredited by Coeliac UK: see " +
        (claim.length === 1 ? "its" : "their") + " own words in the warnings." + (claim.length < rs.length ? " The others don't call the items listed here gluten free." : "") +
        (rs.length === 1 ? " It doesn't guarantee against cross-contact." : " No restaurant here guarantees against cross-contact.")
      : rs.length === 1 ? esc(rs[0].name) + " doesn't call the items listed here gluten free, and doesn't guarantee against cross-contact."
      : "These restaurants don't call the items listed here gluten free, and don't guarantee against cross-contact.");
  }

  // A search word that names an option ruled out everywhere it appears (e.g. "oat" milk) would find nothing,
  // so it's taken out of the search and explained instead: "oat milk latte" lists the lattes, with a note.
  function searchTerms(rs, q) {
    let ts = terms(q);
    const words = (arr) => (arr || []).flatMap((o) => terms(o));
    const out = ts.map((t) => ({ t, rs: rs.filter((r) => r.items.some((i) => words(i.not).includes(t))) }))
      .filter((o) => o.rs.length && !o.rs.some((r) => r.items.some((i) => words(i.ok).includes(t))));
    if (!out.length) {
      // "soya milk latte": soya is searched among the milks that are fine, and "milk" itself is dropped
      const labels = new Set(rs.flatMap((r) => terms(r.optionLabel || "")));
      const rest = ts.filter((t) => !labels.has(t));
      return { ts: rest.length ? rest : ts, note: "" };
    }
    const label = out[0].rs[0].optionLabel || "option";
    ts = ts.filter((t) => !out.some((o) => o.t === t) && !terms(label).includes(t));
    const note = out.map((o) => "<b>" + esc(cap(o.t) + " " + label) + " isn't an option at " + esc(listOr(o.rs.map((r) => r.name))) + ".</b> " +
      (o.t === "oat" ? "Oats count as gluten here, because " + (o.rs.length === 1 ? "its guide lists" : "their guides list") + " them as a gluten cereal." : (o.rs.length === 1 ? "Its guide doesn't" : "Their guides don't") + " show it free from gluten.")).join(" ") +
      (ts.length ? " These have no gluten ingredients with another " + esc(label) + ":" : "");
    return { ts, note };
  }

  // In All restaurants, a restaurant's own name at the start of the search narrows to it, so
  // "pret latte" means lattes at Pret. Tries the longest run of words first ("five guys" before "five").
  // A word counts as the name when it's a whole word of it, or its first four letters or more ("star" for
  // Starbucks). Shorter starts and short name words don't: "a latte" isn't Pret A Manger, and "str" on the
  // way to "strawberry" isn't Blank Street.
  const nameWord = (t, w) => w.length > 2 && (t === w || (t.length >= 4 && w.startsWith(t)));
  function withNameFilter(rs, q) {
    if (selected !== ALL || rs.length < 2) return { rs, q };
    const words = terms(q);
    for (let n = Math.min(3, words.length); n > 0; n--) {
      const head = words.slice(0, n);
      const hit = rs.filter((r) => { const nm = terms(r.name); return head.every((t) => nm.some((w) => nameWord(t, w))); });
      if (hit.length === 1) return { rs: hit, q: words.slice(n).join(" ") };
    }
    return { rs, q };
  }

  // Under a search that found nothing here: matches elsewhere (other restaurants, other cities, the UK menus), and a way to send a menu
  function elsewhere(raw) {
    const ts = terms(raw);
    if (!ts.length) return "";
    const btn = (to, n, text) => n ? '<button type="button" class="link-btn" data-elsewhere="' + esc(to) + '">' + n + " " + text + " &rsaquo;</button>" : "";
    let out = "";
    if (region === UK) {
      if (selected !== ALL) {
        const n = data.restaurants.filter((r) => r.id !== selected).reduce((t, r) => t + r.items.filter((i) => matches(i, ts)).length, 0);
        out += btn(ALL, n, n === 1 ? "match at another restaurant" : "matches at other restaurants");
      }
      for (const [cid, c] of Object.entries(cities)) {
        const n = c.places.filter((p) => matches(placeText(p), ts)).length;
        out += btn(cid, n, n === 1 ? "place in " + esc(c.name) : "places in " + esc(c.name));
      }
    } else if (data) {
      const n = data.restaurants.reduce((t, r) => t + r.items.filter((i) => matches(i, ts)).length, 0);
      out += btn(UK, n, (n === 1 ? "match" : "matches") + " on the UK menus (UK branches only)");
    }
    return out;
  }
  const addMenuLink = '<button type="button" class="link-btn" data-addmenu>A place not here? Ask for it &rsaquo;</button>';
  const emptyExtras = (raw) => raw.trim() ? '<div class="empty-links">' + elsewhere(raw) + addMenuLink + "</div>" : "";
  // What the search box and the chip leave to show: the restaurants in scope, and each one's matching items and
  // Avoid rows (the status buttons are applied by the callers, so the counts on them can be worked out here too).
  function visibleRows() {
    let q = $("q").value.trim().toLowerCase();
    const multi = selected === ALL;
    let rs = scope();
    if (filter.kind === "restaurant") rs = rs.filter((r) => r.id === filter.value);
    if (filter.kind === "area") rs = rs.filter((r) => r.area === filter.value);
    ({ rs, q } = withNameFilter(rs, q));
    const { ts, note } = searchTerms(rs, q);
    const inFilter = (r, i) => (filter.kind === "fav" ? favs.has(favKey(r, i)) : filter.kind !== "section" || multi || i.section === filter.value);
    const items = new Map(rs.map((r) => [r, r.items.filter((i) => matches(i, ts) && inFilter(r, i))]));
    const avoid = new Map(rs.map((r) => [r, r.avoid.filter((a) => matches(a, ts) && inFilter(r, a))]));
    return { q, rs, ts, note, multi, items, avoid };
  }
  function renderList() {
    const { q, rs, multi, note, items: found, avoid: avoidFound } = visibleRows();
    $("searchNote").hidden = !note;
    $("searchNote").innerHTML = note;
    let html = "";
    let shown = 0;
    // "Your usuals": saved favourites first, grouped by restaurant on All. Not while searching or on another chip,
    // and they stay in their own sections too, so nothing moves.
    let usuals = "", usualsN = 0;
    if (!$("q").value.trim() && filter.kind === "all") {
      for (const r of rs) {
        const fav = r.items.filter((i) => favs.has(favKey(r, i)) && visible(kindOf(i)));
        if (!fav.length) continue;
        usualsN += fav.length;
        usuals += (multi ? '<div class="sub-h">' + esc(r.name) + "</div>" : "") + '<div class="card">' + fav.map((i) => rowHtml(r, i, false)).join("") + "</div>";
      }
      if (usuals) usuals = '<h2 class="group-h">Your usuals<small>' + usualsN + "</small></h2>" + usuals;
    }
    for (const r of rs) {
      const items = found.get(r).filter((i) => visible(kindOf(i)));
      if (!items.length) continue;
      shown += items.length;
      if (multi) html += '<h2 class="rest-h">' + esc(r.name) + "<small>" + items.length + "</small></h2>";
      for (const s of r.sections) {
        const inSec = items.filter((i) => i.section === s);
        if (!inSec.length) continue;
        html += multi ? '<div class="sub-h">' + esc(shortSection(s)) + "</div>"
          : '<h2 class="group-h">' + esc(shortSection(s)) + "<small>" + inSec.length + "</small></h2>";
        let k = 0;
        while (k < inSec.length) {
          const sub = inSec[k].sub || "";
          let card = "";
          while (k < inSec.length && (inSec[k].sub || "") === sub) card += rowHtml(r, inSec[k++], false);
          if (sub && !multi) html += '<div class="sub-h">' + esc(cap(sub)) + "</div>";
          html += '<div class="card">' + card + "</div>";
        }
      }
    }
    let empty = "No matches with no gluten ingredients";
    const glutenHits = rs.reduce((n, r) => n + avoidFound.get(r).length, 0);
    if (filter.kind === "fav") empty = favs.size ? "No saved favourites here yet" : "No favourites yet. Open an item and tap ☆ Save.";
    else if (q) empty = 'No items with no gluten ingredients match "' + esc(q) + '".' +
      (glutenHits ? " " + glutenHits + (glutenHits === 1 ? " match is" : " matches are") + " on the Avoid list" + (visible("gluten") ? " below." : ". Tap Avoid above to see " + (glutenHits === 1 ? "it." : "them.")) : "");
    if (!visible("straight") || !visible("change")) empty += " Some items are hidden by the buttons above.";
    $("list").innerHTML = (filter.kind === "fav" ? favShareBar() : "") + (html ? usuals + html : '<p class="empty">' + empty + "</p>" + emptyExtras($("q").value));

    let avoidHtml = "";
    if (filter.kind !== "fav" && visible("gluten")) {
      for (const r of rs) {
        const av = avoidFound.get(r);
        if (!av.length) continue;
        if (multi) avoidHtml += '<div class="sub-h">' + esc(r.name) + "</div>";
        // a name used more than once (Blank Street's croissants, one per store list) says which one it is
        const times = {};
        av.forEach((a) => { const k = norm(a.name); times[k] = (times[k] || 0) + 1; });
        const place = {};
        av.forEach((a) => { const k = norm(a.name) + "|" + a.section + "|" + (a.sub || ""); place[k] = (place[k] || 0) + 1; });
        avoidHtml += '<div class="card">' + av.map((a) => {
          const c = changeOf(r, a);
          const subs = [];
          if (c) subs.push('<span class="chg bad">' + CHG_LABEL[c.kind] + "</span>");
          if (times[norm(a.name)] > 1) {
            subs.push(esc([shortSection(a.section), a.sub && cap(a.sub)].filter(Boolean).join(" · ")) +
              (place[norm(a.name) + "|" + a.section + "|" + (a.sub || "")] > 1 ? " · " + esc(pageText(a.pages).toLowerCase()) : ""));
          }
          if (a.original) subs.push('<span lang="' + esc(r.language || "") + '">' + esc(a.original) + "</span>");
          return '<details class="row" data-slug="' + esc(itemSlug(r, a)) + '"><summary><span class="nm">' + esc(a.name) +
            (subs.length ? "<small>" + subs.join(" · ") + "</small>" : "") + '<span class="tag t-bad">' +
            esc(a.tag || a.gluten.map(cap).join(" & ")) + "</span></span>" + chev + '</summary><div class="detail">' + (c ? changeNote(r, c) : "") + "<div>" +
            (a.reason ? esc(a.reason) : "Every version contains " + esc(a.gluten.join(" and ").toLowerCase()) + ".") + "</div>" +
            (a.info ? "<div>" + esc(a.info) + "</div>" : "") + (a.decided && a.decided !== a.reason ? decidedNote(a) : "") +
            moreLinks(r, a) + "</div></details>";
        }).join("") + "</div>";
      }
    }
    $("avoidWrap").hidden = !avoidHtml;
    $("avoid").innerHTML = avoidHtml;
    // folded until wanted: it opens by itself while searching or when the Avoid button is chosen, and a tap on it overrides that
    $("avoidTitle").textContent = "Avoid: contains gluten or not suitable" + (glutenHits ? " (" + glutenHits + ")" : "");
    $("avoidWrap").open = avoidUser !== null ? avoidUser : !!($("q").value.trim() || pick.gluten);
    return shown;
  }

  function renderStatus() {
    const { rs, items, avoid } = visibleRows();
    const n = { straight: 0, change: 0, gluten: 0 };
    for (const r of rs) {
      for (const i of items.get(r).concat(avoid.get(r))) n[kindOf(i)]++;
    }
    // dot and count together on one line, the label under them, so the buttons are one even row. "Needs a change"
    // with nothing in it (Pret) isn't shown, unless it's the one chosen
    const shown = (k) => n[k] > 0 || pick[k] || k !== "change";
    const b = (k, cls, label) => (shown(k) ? '<button type="button" data-k="' + k + '" aria-pressed="' + pick[k] + '"><span class="num"><span class="dot ' + cls + '"></span>' +
      '<span class="cnt">' + n[k] + '</span></span> <span class="lbl">' + label + "</span></button>" : "");
    $("status").classList.toggle("picking", picking());
    $("status").classList.toggle("two", !shown("change"));
    $("status").innerHTML = b("straight", "d-ok", "No gluten ingredients") + b("change", "d-swap", "Needs a change") + b("gluten", "d-bad", "Avoid");
  }

  // each theme's swatch is a class in styles.css (.sw-auto and so on), so no inline styles are needed anywhere
  const THEMES = [["auto", "Match phone"], ["light", "Light"], ["dark", "Dark"], ["pink-light", "Pink light"], ["pink-dark", "Pink dark"]];
  function applyTheme(t) {
    const root = document.documentElement;
    if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t);
    const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => {
      if (t === "auto") m.setAttribute("content", m.media.includes("dark") ? "#171412" : "#f6f5f2"); else m.setAttribute("content", bg);
    });
  }
  function renderThemes() {
    const cur = store.get(THEME_KEY) || "auto";
    $("themes").innerHTML = THEMES.map(([id, label]) => '<button type="button" data-t="' + id + '" aria-pressed="' + (cur === id) +
      '"><span class="swatch sw-' + id + '"></span>' + label + "</button>").join("");
  }
  $("themes").addEventListener("click", (e) => {
    const b = e.target.closest("[data-t]");
    if (!b) return;
    e.preventDefault();
    store.set(THEME_KEY, b.dataset.t);
    applyTheme(b.dataset.t);
    renderThemes();
  });
  applyTheme(store.get(THEME_KEY) || "auto");
  renderThemes();

  $("status").addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (!b || !data) return;
    pick[b.dataset.k] = !pick[b.dataset.k];
    avoidUser = null;
    store.set(PICK_KEY, JSON.stringify(pick));
    renderStatus();
    renderList();
  });

  function renderSources() {
    const whatChanged = (r) => { const c = sinceLooked(r) || r.changes; return c ? ' <button type="button" class="link-btn" data-whatchanged="' + esc(r.id) + '">What changed, noticed ' +
      esc(fmtDate(c.date)) + " &rsaquo;</button>" : ""; };
    // the guides themselves, as published with the app: one link, or one per guide when there are several
    const guideLinks = (r) => Object.entries(r.guideFiles || {}).filter(([, file]) => safeUrl(file)).map(([src, file], n, all) => ' <a href="' + esc(file) + '" target="_blank" rel="noopener">Open the ' +
      (all.length > 1 ? esc(((r.guides || []).find((g) => g.source === src) || {}).title || "guide " + (n + 1)) + " guide" : "guide") + "</a>").join("");
    const official = (r) => (safeUrl(r.officialUrl) ? ' <a href="' + esc(safeUrl(r.officialUrl)) + '" target="_blank" rel="noopener">Official site</a>' : "");
    const lineShort = (r) => "<p><b>" + esc(r.name) + ":</b> " + esc(r.covers ? r.covers + ". " : "") + "From " + esc(plainGuideName(r)) + ". " +
      esc(r.stats.items) + " with no gluten ingredients, " + esc(r.stats.avoid) + " to avoid." + official(r) + guideLinks(r) + "</p>";
    // "Menus in this app" (Help) keeps the raw file name, for the record
    const lineFull = (r) => {
      const g = r.guide || {};
      return "<p><b>" + esc(r.name) + ":</b> " + esc(r.covers ? r.covers + ". " : "") + "From " + esc(r.source) +
        (g.version ? " (version " + esc(fmtDate(g.version)) + ")" : "") + ". " + esc(r.stats.items) + " with no gluten ingredients, " + esc(r.stats.avoid) +
        " to avoid." + official(r) + guideLinks(r) + whatChanged(r) + "</p>";
    };
    $("sources").innerHTML = scope().map(lineShort).join("");
    $("infoSources").innerHTML = data.restaurants.map(lineFull).join("") + "<p>Rules: " + esc([...new Set(data.restaurants.map((r) => r.rule))].join(" ")) +
      " If the allergen column and ingredients disagree, the item is left out.</p><p>Last built " + esc(fmtDate(data.built)) + ".</p>";
  }

  // The chooser lists the restaurant used last first, then those with saved favourites, then the rest A to Z.
  const LAST_KEY = "gf-last-restaurant";
  const WELCOME_KEY = "gf-welcome-seen";
  let welcomeNow = false; // the welcome is showing in this visit's first chooser
  const hasFavs = (r) => [...favs].some((k) => k.startsWith(r.id + "|"));
  function chooserOrder(rs) {
    const last = store.get(LAST_KEY);
    const rank = (r) => (r.id === last ? 0 : hasFavs(r) ? 1 : 2);
    return rs.slice().sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }
  // A city section's chooser lists that section's cities; Chains' lists the restaurants.
  function renderPicker() {
    const s = sectionOf(region);
    $("pickerTitle").textContent = s === UK ? "Where to eat" : s === UKC ? "UK cities" : "Abroad";
    if (s !== UK) {
      $("pickWelcome").hidden = true;
      $("pickList").innerHTML = citiesIn(s).map((cid) => {
        const c = cities[cid], uk = s === UKC;
        return '<button type="button" class="pick-opt" data-region="' + esc(cid) + '" aria-pressed="' + (region === cid) + '">' +
          '<span class="logo-wrap flag" aria-hidden="true">' + esc(c.flag || "") + '</span><span class="po-main"><b>' + esc(uk ? c.name : c.country || c.name) + "</b><span>" +
          (uk ? "Places" : esc(c.name) + ": places") + " that are all gluten free, by their own word or " + (uk ? "a listing" : "the coeliac society's list") +
          (c.places.some((p) => p.claim === "place-part") ? ", or that say part of what they serve is" : "") +
          (c.places.some((p) => p.claim === "separate") ? ", or that say they have a separate gluten free kitchen" : "") + "</span></span>" +
          '<span class="po-meta">' + c.places.length + (c.places.length === 1 ? " place" : " places") + "</span></button>";
      }).join("");
      return;
    }
    const last = store.get(LAST_KEY);
    // first run: say what the app is, and put the other countries next to All restaurants so they're on the first screen without scrolling
    if (!welcomeNow && !store.get(SEL_KEY) && !store.get(WELCOME_KEY)) { welcomeNow = true; store.set(WELCOME_KEY, "1"); }
    $("pickWelcome").hidden = !welcomeNow;
    // a restaurant this phone hasn't opened since it arrived is tagged New (an out-of-date guide outranks it)
    const opt = (id, name, line, meta, stale, logo, fresh) =>
      '<button type="button" class="pick-opt" data-r="' + esc(id) + '" aria-pressed="' + (region === UK && selected === id) + '">' + logo + '<span class="po-main"><b>' +
      esc(name) + "</b><span>" + esc(line) + "</span></span>" + (stale ? '<span class="tag t-swap">Out of date</span>' : fresh ? '<span class="tag t-any">New</span>' : '<span class="po-meta">' + esc(meta) + "</span>") + "</button>";
    const total = data.restaurants.reduce((n, r) => n + r.stats.items, 0);
    const as = areas();
    const lineOf = (r, withArea) => [r.id === last ? "Last used" : "", r.type, withArea ? r.area : "", guideLine(r)].filter(Boolean).join(" · ");
    const one = (r, withArea) => opt(r.id, r.name, lineOf(r, withArea), r.stats.items + " items", isStale(r), logoHtml(r.name, r.logo), isNew(r));
    const grouped = as.length > 1
      ? as.map((a) => '<div class="sub-h">' + esc(a) + "</div>" + chooserOrder(data.restaurants.filter((r) => r.area === a)).map((r) => one(r, false)).join("")).join("") +
        chooserOrder(data.restaurants.filter((r) => !r.area)).map((r) => opt(r.id, r.name, r.type, r.stats.items + " items", isStale(r), logoHtml(r.name, r.logo), isNew(r))).join("")
      : chooserOrder(data.restaurants).map((r) => one(r, true)).join("");
    // the chains within a kilometre, while the look-around's answer is fresh: nearest first, with distance and hours
    const near = nearAnswer();
    const nearGroup = near ? '<div class="sub-h">Near you</div>' + near.rows.slice(0, 3).map((x) => {
      const r = byId(x.rid);
      return r ? opt(r.id, r.name, [metres(x.km), openText(x.hours), x.where].filter(Boolean).join(" · "), r.stats.items + " items", isStale(r), logoHtml(r.name, r.logo), isNew(r)) : "";
    }).join("") : "";
    // the cities are in their own sections (the switch above), so this lists the restaurants only
    const all = opt(ALL, "All restaurants", "Search and browse everything", total + " items", false, logoHtml("All restaurants", "icons/icon-192.png"));
    $("pickList").innerHTML = nearGroup + '<div class="sub-h">' + (welcomeNow ? "Choose where" : "Chains") + "</div>" + all +
      (welcomeNow ? '<div class="sub-h">Or one restaurant</div>' : "") + grouped +
      '<p class="pick-note">More restaurants can be added by the app\'s owner from each restaurant\'s allergen guide.</p><p class="pick-share">' + addMenuLink + "</p>";
  }

  // The phone's time zone says where it is without asking for its location. Offered once per trip, and UK again on the way home.
  const TZ_KEY = "gf-tz-asked";
  const zoneOf = (c) => c.timeZone || "Europe/Berlin";
  function myZone() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; } }
  function renderTzOffer() {
    const el = $("tzOffer");
    el.hidden = true;
    el.innerHTML = "";
    const zone = myZone();
    if (!zone) return;
    const asked = store.get(TZ_KEY);
    const there = citiesIn(INTL).find((id) => zoneOf(cities[id]) === zone); // a UK city shares UK time, so it's never offered this way
    const btns = (yes) => '<p class="tz-btns"><button type="button" class="pill-btn" data-tz="yes">' + yes + '</button><button type="button" class="link-btn" data-tz="no">Not now</button></p>';
    if (sectionOf(region) !== INTL && there && asked !== zone) {
      el.innerHTML = "<p><b>You're on " + esc(cities[there].name) + " time.</b> Show " + esc(cities[there].name) + " places?</p>" + btns("Show " + esc(cities[there].name));
      el.dataset.to = there;
    } else if (sectionOf(region) === INTL && cities[region] && !there && asked === zoneOf(cities[region])) {
      el.innerHTML = "<p><b>You're back on UK time.</b> Show the UK menus?</p>" + btns("Show UK menus");
      el.dataset.to = UK;
    } else return;
    el.hidden = false;
  }
  $("tzOffer").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tz]");
    if (!b) return;
    store.set(TZ_KEY, myZone());
    const to = $("tzOffer").dataset.to;
    $("tzOffer").hidden = true;
    if (b.dataset.tz === "yes") setRegion(to);
  });
  function render() {
    syncSearching();
    renderRegion();
    renderTzOffer();
    if (region !== UK) { renderCity(); return; }
    if (!data) return;
    if (selected !== ALL && !byId(selected)) selected = ALL;
    renderHeader();
    renderChips();
    renderBanners();
    renderWarnCount();
    renderStatus();
    renderList();
    renderSources();
  }

  function select(id) {
    if (id !== selected) introNow.delete(MENUS); // the card in full is for the page it was first shown on; the next page leads with food
    selected = id;
    filter = { kind: "all" };
    region = UK;
    store.set(REGION_KEY, UK);
    store.set(SEL_KEY, id);
    if (id !== ALL) { store.set(LAST_KEY, id); sawRestaurant(id); }
    avoidUser = null;
    history.replaceState(null, "", id === ALL ? location.pathname : "#" + id);
    $("q").value = "";
    render();
    window.scrollTo({ top: 0 });
  }

  // ---------- the sections: Chains, UK cities, Abroad. A city is a hand-checked list of places (cities.json), not menus ----------
  // A city section goes to the city last looked at in it (the chooser picks another); Chains goes back to the menus.
  const LAST_CITY_KEY = "gf-last-city", LAST_UK_CITY_KEY = "gf-last-uk-city";
  const isUKCity = (c) => !!c && c.group === "uk";
  const sectionOf = (id) => (id === UK ? UK : isUKCity(cities[id]) ? UKC : INTL);
  const citiesIn = (s) => Object.keys(cities).filter((id) => sectionOf(id) === s);
  const lastKeyOf = (s) => (s === UKC ? LAST_UK_CITY_KEY : LAST_CITY_KEY);
  const SECTIONS = [[UK, "Chains"], [UKC, "UK cities"], [INTL, "Abroad"]]; // short, so each fits one line with Larger Text
  function renderRegion() {
    const inCity = region !== UK, on = sectionOf(region);
    $("region").hidden = !Object.keys(cities).length;
    $("region").innerHTML = SECTIONS.filter(([s]) => s === UK || citiesIn(s).length)
      .map(([s, label]) => '<button type="button" data-region="' + s + '" aria-pressed="' + (s === on) + '">' + label + "</button>").join("");
    $("ukView").hidden = inCity;
    $("cityView").hidden = !inCity;
    $("status").hidden = inCity;
  }
  function setRegion(id) {
    if (id === INTL || id === UKC) { const ids = citiesIn(id), last = store.get(lastKeyOf(id)); id = ids.includes(last) ? last : ids[0] || UK; }
    region = id;
    store.set(REGION_KEY, id);
    if (id !== UK) store.set(lastKeyOf(sectionOf(id)), id);
    $("q").value = "";
    cityFilter = "all";
    mapOn = false;
    dropMap();
    history.replaceState(null, "", id !== UK ? "#" + id : selected === ALL ? location.pathname : "#" + selected);
    render();
    window.scrollTo({ top: 0 });
  }
  $("region").addEventListener("click", (e) => {
    const b = e.target.closest("[data-region]");
    if (b && b.dataset.region !== sectionOf(region)) setRegion(b.dataset.region);
  });

  const mapLink = (p, l) => "https://maps.apple.com/?q=" + encodeURIComponent(p.name) + "&address=" + encodeURIComponent(l.address);
  const cityStale = (c) => new Date(c.checked + "T12:00:00Z").getTime() + (c.recheckDays || 90) * 864e5 < Date.now();
  function renderCity() {
    const c = city();
    if (!c) { $("cityList").innerHTML = '<p class="empty">Loading…</p>'; return; }
    store.set(lastKeyOf(sectionOf(region)), region); // where its section goes next time
    syncSearching();
    $("pickName").textContent = c.name;
    $("pickBtn").setAttribute("aria-label", c.name + ". Choose a city");
    $("guideLine").textContent = c.places.length + (c.places.length === 1 ? " place" : " places") + " · checked " + fmtDate(c.checked) + offlineTag();
    $("q").placeholder = "Search " + c.name;
    // The row, in the order it's wanted: abroad, the language card first; then All, Open near me (still open today,
    // nearest first: one chip, where three overlapped), Favourites (the name the menus use), the sections when there's
    // more than one, and the city's own map last. A city with a few places needs no filters, so only its card shows.
    const few = c.places.length < 4;
    const secs = c.sections.filter((s) => c.places.some((p) => p.section === s));
    const chips = few ? [] : [["all", "All"], ["fav", "★ Favourites"]].concat(secs.length > 1 ? secs.map((s) => [s, s]) : []);
    if (cityFilter !== "open" && !chips.some(([v]) => v === cityFilter)) cityFilter = "all";
    const card = phrases[c.language];
    // with the look-around on and the phone inside the city, the chip names the nearest place still open today (no network needed)
    const now0 = cityNow(c);
    const nearest = nearAuto && here && inBounds(c, here) ? c.places.filter((p) => stillOpen(p, now0)).sort((a, b) => placeKm(a) - placeKm(b))[0] : null;
    const chip = ([v, l]) => chipHtml(["all", "fav"].includes(v) ? v : "section", ["all", "fav"].includes(v) ? "" : v, l, v === cityFilter && !(v === "all" && nearSort));
    $("chips").innerHTML = (card ? '<button type="button" data-card>' + esc(card.language) + " card</button>" : "") +
      (few ? "" : chip(chips[0]) + '<button type="button" data-nearopen aria-pressed="' + (nearSort && cityFilter === "open") + '">' +
        (nearest ? "Open near: " + esc(nearest.name) + " " + placeKm(nearest).toFixed(1) + " km ›" : "Open near me") + "</button>" +
        chips.slice(1).map(chip).join("") + '<button type="button" data-map aria-pressed="' + mapOn + '">Map</button>');
    $("chips").hidden = !$("chips").innerHTML;
    const n = (claim) => c.places.filter((p) => p.claim === claim).length;
    // a UK city's places were found through guides and listings rather than a coeliac society's list
    const uk = isUKCity(c);
    $("cityIntroLine").innerHTML = "<b>Tags say who calls a place gluten free</b>, not the app. Tell staff you're coeliac.";
    $("cityIntro").innerHTML = "<b>Each place's tag says who calls it gluten free.</b> " +
      [n("place-all") && n("place-all") + " say so themselves",
        n("list-all") && n("list-all") + (uk ? " are listed as all gluten free by others and have only a social media page or a market's, so their own words weren't checked" : " are listed as all gluten free by the support groups but don't say so on their own websites"),
        n("place-part") && n("place-part") + " says only part of its range is", n("separate") && n("separate") + " says it makes gluten free food in a separate kitchen"]
        .filter(Boolean).join("; ") + ". That's their claim, not the app's. " + (uk ? "They were found through " : "They come from the list kept by ") +
      // who keeps a list is a name ("My Gluten Free Guide"), not the app's words, so it's marked as quoted
      listOr([c.list, ...(c.also || [])].map((a) => "<span data-quote>" + esc(a.by) + "</span>"), "and") +
      ", checked against each place's own website" + (uk ? " where it has one" : "") + " on " + esc(fmtDate(c.checked)) + ". Nobody from this app has seen their kitchens, so tell staff you have coeliac disease.";
    $("cityStale").hidden = !cityStale(c);
    $("cityStale").innerHTML = cityStale(c) ? "<p><b>This list may be out of date.</b> It was checked on " + esc(fmtDate(c.checked)) +
      ". Places open, close and change, so check before you go.</p>" : "";
    $("cityTipsLabel").textContent = "Before you go (" + c.tips.length + ")";
    $("cityTips").innerHTML = tipsHtml(c.tips);
    // after the first visit the introduction folds into one line, as a restaurant's tips do, with its full wording one tap away
    const full = introFull(region);
    $("cityIntroBox").hidden = !full;
    $("cityStrip").hidden = full;
    $("cityStripCount").textContent = "(" + c.tips.length + ")";
    const source = (a) => (safeUrl(a.url) ? '<a href="' + esc(safeUrl(a.url)) + '" target="_blank" rel="noopener" data-quote>' + esc(a.name) + "</a>" : "<span data-quote>" + esc(a.name) + "</span>") + ", kept by <span data-quote>" + esc(a.by) + "</span>";
    $("cityFoot").innerHTML = "<p><b>Sources:</b> " + [c.list, ...(c.also || [])].map(source).join("; ") +
      "; and each place's own website. Checked " + esc(fmtDate(c.checked)) + ".</p>" +
      (c.footNotes || []).map((n) => "<p>" + esc(n) + "</p>").join("");
    renderCityList();
  }
  // Who says it's gluten free: the place itself, only the support groups' list, or the place for part of its range
  const CLAIM_TAGS = { "place-all": "Says all gluten free", "list-all": "Listed as all gluten free", separate: "Separate kitchen" };
  // Opening hours come from each place's website: hours[0..6] = Monday..Sunday, "" = closed, no hours = not known.
  // "Today" is the city's day (cities.json timeZone), wherever the phone is.
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  function cityNow(c) {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: c.timeZone || "Europe/Berlin", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date()).map((x) => [x.type, x.value]));
    return { day: DAYS.indexOf(parts.weekday), min: +parts.hour * 60 + +parts.minute };
  }
  // "09:30–14:30" (perhaps with a note after it) -> [570, 870]; "" -> null
  const span = (h) => { const m = (h || "").match(/(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})/); return m ? [m[1] * 60 + +m[2], m[3] * 60 + +m[4]] : null; };
  const hhmm = (n) => String(Math.floor(n / 60)).padStart(2, "0") + ":" + String(n % 60).padStart(2, "0");
  // still open today: open now, or opening later today
  // The branches that matter: the nearest one when sorting by distance, otherwise all of them. Worked out once per
  // render (placeBranches), since sorting by distance per place per line adds up.
  const branches = (p) => (nearSort && here ? [p.locations.slice().sort((a, b) => kmTo(a, here) - kmTo(b, here))[0]] : p.locations);
  // A branch's day is: a span [open, close] (close = when the kitchen stops, if earlier), "closed", or unknown (no hours, or null).
  // every range in a day: "12:00–14:30, 17:00–21:30" (a break for the afternoon) -> [[720, 870], [1020, 1290]]
  const spans = (h) => [...String(h || "").matchAll(/(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})/g)].map((m) => [m[1] * 60 + +m[2], m[3] * 60 + +m[4]]);
  // On a day with a break, the range that matters at that minute: the one open now, else the next, else the last.
  function branchToday(l, day, min) {
    if (!l.hours || l.hours[day] == null) return { unknown: true };
    const ss = spans(l.hours[day]);
    if (!ss.length) return { closed: true };
    const s = ss.find(([o, c]) => o <= min && min < c) || ss.find(([o]) => o > min) || ss[ss.length - 1];
    const kitchen = span("00:00–" + (l.kitchenCloses || "24:00"));
    return { open: s[0], close: Math.min(s[1], kitchen[1]), kitchen: !!l.kitchenCloses && kitchen[1] < s[1], door: s[1] };
  }
  // now: { day, min } from cityNow(c), worked out once for a whole render; ls: the place's branches, likewise
  const stillOpen = (p, now, ls) => (ls || branches(p)).some((l) => { const b = branchToday(l, now.day, now.min); return b.close > now.min; });
  function todayLine(p, now, ls) {
    const { day, min } = now;
    ls = ls || branches(p);
    const bs = ls.map((l) => ({ l, ...branchToday(l, day, min) }));
    if (bs.every((b) => b.unknown)) return "";
    const where = (list) => (ls.length > 1 && list.length < ls.length ? " at " + listOr([...new Set(list.map((b) => b.l.area))]) : "");
    const openNow = bs.filter((b) => b.open <= min && min < b.close);
    const until = Math.max(...openNow.map((b) => b.close));
    if (openNow.length) return "Open now" + where(openNow) + ", " + (openNow.some((b) => b.kitchen) ? "kitchen until " : "until ") + (until >= 1440 ? "midnight" : hhmm(until));
    const later = bs.filter((b) => b.open > min);
    if (later.length) return "Opens at " + hhmm(Math.min(...later.map((b) => b.open))) + where(later);
    if (bs.some((b) => b.open != null && b.kitchen && min < b.door)) return "Kitchen closed";
    if (bs.some((b) => b.open != null)) return "Closed now";
    return bs.some((b) => b.unknown) ? "" : "Closed today";
  }
  function weekText(hours) {
    const out = [];
    for (let i = 0; i < 7;) {
      let j = i;
      while (j < 6 && hours[j + 1] === hours[i]) j++;
      // a day with a break reads "12:00–14:30 and 17:00–21:30", so the commas are only between days
      out.push((i === j ? DAYS[i] : DAYS[i] + "–" + DAYS[j]) + " " + (hours[i] == null ? "not known" : (hours[i] || "closed").replace(/(\d:\d\d),\s*(?=\d{1,2}:\d\d)/g, "$1 and ")));
      i = j + 1;
    }
    return out.join(", ");
  }
  // distance in km, near enough for "nearest first" within a city
  const kmTo = (l, at) => Math.hypot((l.lat - at.lat) * 111.2, (l.lon - at.lon) * 111.2 * Math.cos(at.lat * Math.PI / 180));
  const placeKm = (p) => Math.min(...p.locations.map((l) => kmTo(l, here)));
  const placeFav = (p) => "city:" + region + "|" + p.name;
  function placeHtml(c, p, now) {
    const ls = branches(p);
    const subs = [esc(p.type), esc([...new Set(p.locations.map((l) => l.area))].join(", "))];
    if (nearSort && here) subs.unshift(placeKm(p).toFixed(1) + " km" + (p.locations.length > 1 ? " (" + esc(ls[0].area) + ")" : ""));
    const today = todayLine(p, now, ls);
    if (today) subs.push('<span class="today' + (/^(Closed|Kitchen closed)/.test(today) ? " shut" : "") + '">' + esc(today) + "</span>");
    if (p.caution) subs.push('<span class="chg">' + esc(p.flag) + "</span>");
    if (p.status !== "confirmed") subs.push('<span class="chg bad">Opening not confirmed</span>');
    const out = [];
    // data-quote marks someone else's words, which ui_check.py doesn't hold to the app's own wording rules
    if (p.says) {
      out.push('<blockquote class="w-quote" lang="' + esc(p.says.lang) + '">' + esc(p.says.text) + "<cite>Its website</cite></blockquote>");
      if (p.says.en) out.push("<div data-quote><b>In English:</b> " + esc(p.says.en) + ' <span class="muted">(the app\'s translation)</span></div>');
    }
    if (p.listed) out.push("<div data-quote><b>" + (p.listedBy ? "From " + esc(p.listedBy) + ":" : "From the coeliac support groups' list:") + "</b> " + esc(p.listed) + "</div>");
    if (p.caution) out.push('<div class="chg-note"><b>Note from this app:</b> ' + esc(p.caution) + "</div>");
    if (p.status !== "confirmed") out.push('<div class="chg-note bad"><b>Not confirmed open.</b> ' + esc(p.statusNote || "") + "</div>");
    (p.notes || []).forEach((n) => out.push("<div>" + esc(n) + "</div>"));
    out.push('<ul class="locs">' + p.locations.map((l) => '<li><a href="' + esc(mapLink(p, l)) + '" target="_blank" rel="noopener">' + esc(l.address) + "</a>" +
      "<span>" + esc([l.area, l.note].filter(Boolean).join(" · ")) + "</span>" +
      "<span>" + (l.hours ? "<b>Hours:</b> " + esc(weekText(l.hours)) + (l.kitchenCloses ? ". Kitchen closes at " + esc(l.kitchenCloses) : "") +
        (l.hoursNote ? ". " + esc(l.hoursNote) : "") + " (from its website, " + esc(fmtDate(p.checked || c.checked)) + ")"
        : "<b>Hours not known.</b> Check its website before going.") + "</span></li>").join("") + "</ul>");
    out.push(noteBox(placeFav(p))); // after where and when, the things needed to go there
    out.push('<div class="detail-more"><button type="button" class="link-btn" data-wrong-place="' + esc(p.name) + '">Something wrong?</button></div>');
    const social = /instagram\.com/.test(p.url) ? "Instagram" : /facebook\.com/.test(p.url) ? "Facebook" : "Website";
    out.push('<div class="place-links">' + (safeUrl(p.url) ? '<a href="' + esc(safeUrl(p.url)) + '" target="_blank" rel="noopener">' + social + "</a>" : "") +
      (safeUrl(p.listPage) ? '<a href="' + esc(safeUrl(p.listPage)) + '" target="_blank" rel="noopener">' + (isUKCity(c) ? "Its listing" : "Support groups' entry") + "</a>" : "") +
      '<button type="button" class="fav-btn" data-fav="' + esc(placeFav(p)) + '" aria-pressed="' + favs.has(placeFav(p)) + '">' + (favs.has(placeFav(p)) ? "★ Saved" : "☆ Save") + "</button></div>");
    // green only when the place itself says everything is gluten free and the app has nothing to add
    // amber is for items that need a change; here it marks a place the app has a caution about, and the rest are plain
    const cls = p.claim === "place-all" && !p.caution ? "t-asis" : p.caution ? "t-swap" : "t-info";
    // an amber tag says why it's amber: the claim, then that there's something to ask (the row's bold flag says what)
    const label = (p.claimLabel || CLAIM_TAGS[p.claim]) + (p.caution ? " · ask" : "");
    const star = favs.has(placeFav(p)) ? '<span class="star" aria-label="Favourite">★</span>' : "";
    return '<details class="row" data-place="' + esc(p.name) + '"><summary><span class="nm">' + star + noteMark(placeFav(p)) + esc(p.name) + "<small>" + subs.join(" · ") + '</small><span class="tag ' + cls + '">' +
      esc(label) + "</span></span>" + chev + '</summary><div class="detail">' + out.join("") + "</div></details>";
  }
  // search what a place is and where it is, not street names or notes ("Sonntag" shouldn't find Sonntagstraße)
  const placeText = (p) => ({ name: [p.name, p.type, p.listed, p.flag, p.caution, p.says && p.says.text, p.says && p.says.en,
    p.locations.map((l) => l.area).join(" ")].filter(Boolean).join(" ") });
  function renderCityList() {
    const c = city();
    if (!c) return;
    const ts = terms($("q").value.trim());
    const now = cityNow(c); // once for the whole list, not once per place
    const places = c.places.filter((p) => matches(placeText(p), ts) && (cityFilter === "all" || (cityFilter === "open" ? stillOpen(p, now)
      : cityFilter === "fav" ? favs.has(placeFav(p)) : p.section === cityFilter)));
    let html = "";
    if (nearSort && here && places.length) {
      const near = places.slice().sort((a, b) => placeKm(a) - placeKm(b));
      html = '<h2 class="group-h">Nearest first<small>' + near.length + "</small></h2>" + '<div class="card">' + near.map((p) => placeHtml(c, p, now)).join("") + "</div>";
    } else for (const s of c.sections) {
      const inSec = places.filter((p) => p.section === s);
      if (!inSec.length) continue;
      html += '<h2 class="group-h">' + esc(s) + "<small>" + inSec.length + "</small></h2>" + '<div class="card">' + inSec.map((p) => placeHtml(c, p, now)).join("") + "</div>";
    }
    html += chainsHere(c, ts);
    const unknown = c.places.filter((p) => !p.locations.some((l) => l.hours)).length;
    const empty = cityFilter === "fav" ? "No favourites here yet. Open a place and tap ☆ Save."
      : cityFilter === "open" ? "None of the places with known hours are open for the rest of today."
      : 'No places match "' + esc($("q").value.trim()) + '".';
    const mapHtml = mapOn ? '<div id="cityMap" class="city-map" role="region" aria-label="Map of the places"></div><p class="muted map-note">' +
      (offlineNow ? "The map needs signal for its background; the pins still show. " : "") + "Green: says all gluten free. Amber: something to ask about. Grey: the rest. Tap a pin, then Open.</p>" : "";
    $("cityList").innerHTML = mapHtml + (cityFilter === "fav" ? favShareBar() : "") + (html || '<p class="empty">' + empty + "</p>" + (cityFilter === "all" ? emptyExtras($("q").value) : "")) +
      (cityFilter === "open" && unknown ? '<p class="muted">' + unknown + " places with unknown hours aren't shown.</p>" : "");
    if (mapOn) drawMap(c, places); else dropMap();
  }
  // A UK city also holds the app's chains: one row each, with how many of its branches are in the city's area (the
  // branch list, so offline too), and its menu one tap away. The area is the city's bounds, a box, hence "in and around".
  let chainsTriedAt = 0;
  function chainsHere(c, ts) {
    if (!isUKCity(c) || cityFilter !== "all" || !data) return "";
    if (!branchList) { // tried at most every half minute, not on every keystroke while there's no list to have
      if (Date.now() - chainsTriedAt > 30000) { chainsTriedAt = Date.now(); loadBranches().then((l) => { if (l && city() === c) renderCityList(); }); }
      return "";
    }
    const count = new Map();
    for (const x of branchList.b) {
      if (!inBox(x, c.bounds.lat[0], c.bounds.lon[0], c.bounds.lat[1], c.bounds.lon[1])) continue;
      const b = branchOf(branchList, x);
      if (b) count.set(b.rid, (count.get(b.rid) || 0) + 1);
    }
    const rows = [...count].map(([rid, n]) => ({ r: byId(rid), n })).filter((x) => x.r && matches({ name: x.r.name + " " + (x.r.type || "") }, ts))
      .sort((a, b) => a.r.name.localeCompare(b.r.name));
    if (!rows.length) return "";
    return '<h2 class="group-h">The app\'s chains here<small>' + rows.length + '</small></h2><div class="pick-list chains-here">' +
      rows.map(({ r, n }) => '<button type="button" class="pick-opt" data-chain="' + esc(r.id) + '">' + logoHtml(r.name, r.logo) + '<span class="po-main"><b>' + esc(r.name) +
        "</b><span>" + n + (n === 1 ? " branch" : " branches") + " in and around " + esc(c.name) + '</span></span><span class="po-meta">Menu &rsaquo;</span></button>').join("") +
      '</div><p class="muted">Branches from OpenStreetMap, which doesn\'t list every one. Each chain\'s menu, from its allergen guide, is under Chains.</p>';
  }
  // ---------- a map of the city's places: Leaflet with OpenStreetMap's tiles, loaded only while the map is open ----------
  // The tiles are fetched while looking and never saved (the tile provider's rules forbid keeping them), so the list
  // keeps working offline and the map shows its pins on a blank background.
  let mapOn = false, leafletMap = null, leafletLoading = null;
  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (leafletLoading) return leafletLoading;
    leafletLoading = new Promise((ok, bad) => {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "vendor/leaflet/leaflet.css";
      document.head.appendChild(css);
      const s = document.createElement("script");
      s.src = "vendor/leaflet/leaflet.js";
      s.onload = ok;
      s.onerror = () => { leafletLoading = null; bad(new Error("the map code didn't load")); };
      document.head.appendChild(s);
    });
    return leafletLoading;
  }
  function dropMap() { if (leafletMap) { leafletMap.remove(); leafletMap = null; } }
  // pins take the row's colours: green for a place's own all-gluten-free claim with nothing to add, amber for a caution
  const pinColour = (p) => getComputedStyle(document.documentElement).getPropertyValue(p.claim === "place-all" && !p.caution ? "--ok" : p.caution ? "--swap" : "--muted").trim();
  async function drawMap(c, places) {
    dropMap();
    try { await loadLeaflet(); } catch (e) { toast("The map couldn't load. Check your signal and try again."); return; }
    const el = $("cityMap");
    if (!el || !mapOn || leafletMap) return;
    const map = L.map(el, { scrollWheelZoom: false });
    leafletMap = map;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors' }).addTo(map);
    const pts = [];
    for (const p of places) {
      for (const l of p.locations) {
        if (l.lat == null || l.lon == null) continue;
        pts.push([l.lat, l.lon]);
        L.circleMarker([l.lat, l.lon], { radius: 9, color: "#ffffff", weight: 2, fillColor: pinColour(p), fillOpacity: 0.95 })
          .bindPopup("<b>" + esc(p.name) + "</b><br>" + esc(l.area) + '<br><button type="button" class="link-btn" data-place-open="' + esc(p.name) + '">Open &rsaquo;</button>').addTo(map);
      }
    }
    if (here && nearSort) L.circleMarker([here.lat, here.lon], { radius: 7, color: "#ffffff", weight: 2, fillColor: "#1e6fd9", fillOpacity: 1 }).bindPopup("You are here").addTo(map);
    if (pts.length) map.fitBounds(pts, { padding: [24, 24], maxZoom: 15 });
    else map.setView([(c.bounds.lat[0] + c.bounds.lat[1]) / 2, (c.bounds.lon[0] + c.bounds.lon[1]) / 2], 11);
  }
  function openPlaceRow(name) {
    const row = [...document.querySelectorAll("#cityList .row")].find((d) => d.dataset.place === name);
    if (!row) return;
    if (leafletMap) leafletMap.closePopup();
    row.open = true;
    window.scrollTo({ top: Math.max(0, row.getBoundingClientRect().top + window.scrollY - topEl.offsetHeight - 12) });
  }
  // "Open near me": still open today, nearest first, in one tap; a second tap turns both off
  function toggleNearOpen() {
    if (nearSort && cityFilter === "open") { nearSort = false; cityFilter = "all"; renderCity(); return; }
    cityFilter = "open";
    if (nearSort) { renderCity(); window.scrollTo({ top: 0 }); return; }
    if (!navigator.geolocation) { renderCity(); toast("This phone can't share its location here"); return; }
    navigator.geolocation.getCurrentPosition((pos) => {
      here = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      nearSort = true;
      renderCity();
      window.scrollTo({ top: 0 });
    }, () => { renderCity(); toast("Couldn't get your location, so this shows what's open today. Check Location Services for Safari in Settings."); }, { timeout: 10000, maximumAge: 300000 });
  }
  function toggleNear() {
    if (nearSort) { nearSort = false; renderCity(); return; }
    if (!navigator.geolocation) { toast("This phone can't share its location here"); return; }
    navigator.geolocation.getCurrentPosition((pos) => {
      here = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      nearSort = true;
      renderCity();
      window.scrollTo({ top: 0 });
    }, () => toast("Couldn't get your location. Check Location Services for Safari in Settings."), { timeout: 10000, maximumAge: 300000 });
  }

  // ---------- "Near me" on the UK menus: the app's chains within a kilometre, from the branch list ----------
  // data/branches.json is every UK branch of the app's chains, fetched from OpenStreetMap by the publish job
  // (tools/fetch_branches.py, weekly), so Near me answers at once, works offline, and where you are never leaves the
  // phone. OpenStreetMap doesn't list every branch, which is a convenience problem, not a safety one: each chain's
  // allergen guide covers all its branches.
  const NEAR_KEY = "gf-near";
  const osmChains = () => data.restaurants.filter((r) => Array.isArray(r.osm) && r.osm.length);
  // { fetched: "YYYY-MM-DD", chains: [restaurant id], b: [[chain number, lat, lon, street, opening_hours]] }
  let branchList = null, branchLoading = null;
  const NO_LIST = "The list of the chains' branches isn't on this phone yet: it downloads when the app has signal.";
  function loadBranches() {
    if (branchList) return Promise.resolve(branchList);
    if (!branchLoading) {
      branchLoading = fetch("data/branches.json", { cache: "no-cache" }).then((res) => (res.ok ? res.json() : null))
        .then((j) => { branchList = j && Array.isArray(j.b) && Array.isArray(j.chains) ? j : null; return branchList; })
        .catch(() => null)
        .finally(() => { branchLoading = null; });
    }
    return branchLoading;
  }
  // one entry of the list as a branch, or null for a chain no longer in the app (or a malformed entry)
  function branchOf(list, x) {
    const r = Array.isArray(x) && byId(list.chains[x[0]]);
    if (!r || !Number.isFinite(x[1]) || !Number.isFinite(x[2])) return null;
    return { rid: r.id, name: r.name, lat: x[1], lon: x[2], where: String(x[3] || ""), hours: String(x[4] || "") };
  }
  // the list's branches inside a box (a cheap test before any distance is worked out)
  const inBox = (x, s, w, n, e) => x[1] > s && x[1] < n && x[2] > w && x[2] < e;
  // one row per chain: its nearest branch (with OpenStreetMap's opening hours, if tagged), and how many are within the kilometre
  function nearRows(list, at) {
    const best = new Map();
    for (const x of list.b) {
      if (!inBox(x, at.lat - 0.01, at.lon - 0.02, at.lat + 0.01, at.lon + 0.02)) continue;
      const b = branchOf(list, x);
      const km = b && kmTo(b, at);
      if (!b || km > 1) continue;
      const cur = best.get(b.rid);
      if (!cur) best.set(b.rid, { ...b, km, n: 1 });
      else { cur.n++; if (km < cur.km) Object.assign(cur, b, { km, n: cur.n }); }
    }
    return [...best.values()].sort((a, b) => a.km - b.km);
  }
  const metres = (km) => (km < 0.95 ? Math.max(10, Math.round(km * 100) * 10) + " m" : km.toFixed(1) + " km");
  // OpenStreetMap's opening_hours tag, read only in its plain shapes ("Mo-Fr 06:30-19:00; Sa-Su 08:00-18:00",
  // "Mo-Su 07:00-20:00", "24/7", a trailing "PH off"): the spans for the given day, [] when closed, or null when the tag
  // is any other shape, which is left unread rather than guessed. A later rule for the same day wins, as in the tag's own rules.
  const OSM_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
  function osmToday(tag, day) {
    tag = String(tag || "").trim();
    if (!tag) return null;
    if (tag === "24/7") return [[0, 1440]];
    let spans = null;
    for (const rule of tag.split(";")) {
      const part = rule.trim();
      if (!part || /^PH\s+(off|closed)$/.test(part)) continue; // the plain holiday rule; "PH,Su …" is another shape, left unread
      const m = part.match(/^([A-Za-z,-]+)\s+(off|closed|[\d:,-]+)$/);
      if (!m) return null;
      const days = new Set();
      for (const d of m[1].split(",")) {
        const dm = d.match(/^(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?$/);
        if (!dm) return null;
        const a = OSM_DAYS.indexOf(dm[1]), b = dm[2] ? OSM_DAYS.indexOf(dm[2]) : a;
        for (let n = a; ; n = (n + 1) % 7) { days.add(n); if (n === b) break; }
      }
      const got = [];
      if (!/^(off|closed)$/.test(m[2])) {
        for (const sp of m[2].split(",")) {
          const tm = sp.match(/^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$/);
          if (!tm) return null;
          const open = +tm[1] * 60 + +tm[2], close = +tm[3] * 60 + +tm[4];
          if (close <= open) return null; // runs past midnight: not a plain shape, so no guess
          got.push([open, close]);
        }
      }
      if (days.has(day)) spans = got;
    }
    return spans;
  }
  // "open now" (until midnight or all day), "open until 19:00", "opens 08:00", "closed today", or "" when the hours
  // aren't known in a plain form. The phone's own clock: the branches are in the UK.
  function openText(tag) {
    const now = new Date();
    const spans = osmToday(tag, (now.getDay() + 6) % 7);
    if (spans === null) return "";
    const min = now.getHours() * 60 + now.getMinutes();
    const on = spans.find(([o, c]) => o <= min && min < c);
    if (on) return on[1] >= 1440 ? "open now" : "open until " + hhmm(on[1]);
    const later = spans.filter(([o]) => o > min);
    if (later.length) return "opens " + hhmm(later[0][0]);
    return "closed today";
  }
  const listDate = (iso) => (iso ? new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
  function renderNear(rows, fetched, note) {
    const hoursNote = rows.some((x) => openText(x.hours)) ? " Hours from OpenStreetMap too, which may be out of date." : "";
    $("nearBody").innerHTML = (note ? '<p class="muted">' + esc(note) + "</p>" : "") + (rows.length
      ? '<ul class="near-list">' + rows.map((x) => '<li><span class="nm"><b>' + esc(x.name) + "</b><small>" + esc([metres(x.km), openText(x.hours), x.where].filter(Boolean).join(" · ")) +
        (x.n > 1 ? " · " + x.n + " within 1 km" : "") + '</small></span><span class="near-btns"><button type="button" class="fav-btn" data-gonear="' + esc(x.rid) + '">Menu</button>' +
        '<a class="fav-btn" href="https://maps.apple.com/?ll=' + esc(x.lat + "," + x.lon) + "&q=" + encodeURIComponent(x.name) + '" target="_blank" rel="noopener">Directions</a></span></li>').join("") + "</ul>"
      : '<p class="empty">None of the app\'s restaurants is listed within 1 km of here.</p>') +
      '<p class="muted">Branches from OpenStreetMap, which doesn\'t list every one' + (fetched ? " (its list from " + esc(listDate(fetched)) + ")" : "") + ". Each chain's allergen guide covers all its branches." + hoursNote + "</p>" +
      // the opt-in, once, in context: the look-around each time the app opens
      (store.get(NEAR_AUTO_KEY) === null ? '<div class="chg-note" data-near-ask><b>Look around each time the app opens?</b> The nearest chain then shows on the chip row under the search box, with no tap. Your position stays on this phone.' +
        '<p class="tz-btns"><button type="button" class="pill-btn" data-near-auto="on">Keep checking</button><button type="button" class="link-btn" data-near-auto="off">Only when I tap</button></p></div>' : "");
  }
  const fmtWhen = (iso) => { const d = new Date(iso); return d.toDateString() === new Date().toDateString() ? "today at " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "on " + d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };
  // the menus cover the chains' UK branches, so the list is only worth reading in the UK (roughly)
  const inUK = (at) => at.lat > 49 && at.lat < 61 && at.lon > -9 && at.lon < 2;
  const inBounds = (c, at) => !!c.bounds && c.bounds.lat[0] < at.lat && at.lat < c.bounds.lat[1] && c.bounds.lon[0] < at.lon && at.lon < c.bounds.lon[1];
  const rounded = (at) => ({ lat: +at.lat.toFixed(3), lon: +at.lon.toFixed(3) });
  const savedNear = () => { try { const s = JSON.parse(store.get(NEAR_KEY) || "null"); return s && Array.isArray(s.rows) ? s : null; } catch (e) { return null; } };
  // the chains near a position, from the branch list; the answer is kept for the chip and the chooser's Near you group
  async function lookNear(at) {
    const list = await loadBranches();
    if (!list) return null;
    const rows = nearRows(list, at);
    store.set(NEAR_KEY, JSON.stringify({ when: new Date().toISOString(), rows, at: rounded(at), fetched: list.fetched }));
    return rows;
  }
  async function nearMe() {
    if (!data) return;
    if (!navigator.geolocation) { toast("This phone can't share its location here"); return; }
    $("nearBody").innerHTML = '<p class="empty">Finding your location…</p>';
    openDialog($("near"));
    const saved = savedNear();
    const fallback = (why) => {
      if (saved) renderNear(saved.rows, saved.fetched, why + " This is the last answer, from " + fmtWhen(saved.when) + ".");
      else $("nearBody").innerHTML = '<p class="empty">' + esc(why) + "</p>";
    };
    let at;
    try {
      const pos = await new Promise((ok, bad) => navigator.geolocation.getCurrentPosition(ok, bad, { timeout: 10000, maximumAge: 120000 }));
      at = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      store.set(NEAR_GRANTED, "1");
    } catch (e) { fallback("Couldn't get your location. Check Location Services for Safari in Settings."); return; }
    if (!inUK(at)) {
      const there = Object.keys(cities).find((id) => inBounds(cities[id], at));
      $("nearBody").innerHTML = '<p class="empty">Near me covers the chains\' UK branches, and you\'re outside the UK.' +
        (there ? " For " + esc(cities[there].name) + ", Abroad has the places and Open near me." : "") + "</p>";
      return;
    }
    const rows = await lookNear(at);
    if (!rows) { fallback(NO_LIST); return; }
    renderNear(rows, branchList && branchList.fetched, "");
    if (data && region === UK) renderChips();
  }

  // ---------- a look around when the app opens (opt-in): the nearest chain on the chip row, from the branch list ----------
  // Never a location prompt unasked: the automatic look only runs when the phone already reports the permission as
  // granted (or a tap on Near me has worked before), and reads the position at most every ten minutes. Nothing leaves
  // the phone. Outside the UK, or on a city page, only the position is taken (for the city's own chip).
  const NEAR_AUTO_KEY = "gf-near-auto"; // "on" | "off"; unset = not asked yet
  const NEAR_GRANTED = "gf-near-granted"; // a tap on Near me has had a position: the permission exists
  const NEAR_EVERY_MS = 10 * 60000, NEAR_FRESH_MS = 60 * 60000;
  let nearAuto = store.get(NEAR_AUTO_KEY) === "on";
  let nearBusy = false, nearTriedAt = 0;
  // the saved answer while it's fresh and the look-around is on, else null
  const nearAnswer = () => { const s = savedNear(); return nearAuto && s && s.rows.length && Date.now() - new Date(s.when).getTime() < NEAR_FRESH_MS ? s : null; };
  function nearChipText(r) {
    if (nearBusy) return "Near me…";
    const s = nearAnswer();
    if (!s) return "Near me";
    const row = (r && s.rows.find((x) => x.rid === r.id)) || s.rows[0];
    // on the chain's own page the name goes without saying, and a shorter chip keeps the section chips within reach
    const lead = r && row.rid === r.id ? "Here: " + metres(row.km) : row.name + " " + metres(row.km);
    return [lead, openText(row.hours)].filter(Boolean).join(" · ") + " ›";
  }
  function locationGranted() {
    const before = store.get(NEAR_GRANTED) === "1";
    if (!(navigator.permissions && navigator.permissions.query)) return Promise.resolve(before);
    return navigator.permissions.query({ name: "geolocation" }).then((p) => p.state === "granted").catch(() => before);
  }
  async function autoNear(userAsked) {
    if (!nearAuto || !data || nearBusy || !navigator.geolocation) return;
    if (!userAsked && (document.querySelector("dialog[open]") || Date.now() - nearTriedAt < NEAR_EVERY_MS || !(await locationGranted()))) return;
    nearTriedAt = Date.now();
    nearBusy = true;
    if (region === UK) renderChips();
    let at;
    try {
      const pos = await new Promise((ok, bad) => navigator.geolocation.getCurrentPosition(ok, bad, { timeout: 8000, maximumAge: 300000 }));
      at = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      store.set(NEAR_GRANTED, "1");
    } catch (e) { nearBusy = false; if (region === UK) renderChips(); return; }
    here = at;
    if (region !== UK) { nearBusy = false; renderCity(); return; } // the city's chip reads from the list itself
    if (inUK(at)) await lookNear(at); // no list yet: the chip keeps the last answer
    nearBusy = false;
    if (region === UK) renderChips(); else renderCity(); // the page may have changed hands meanwhile
    if ($("picker").open) renderPicker();
  }
  function renderNearToggle() {
    const b = $("nearAutoBtn");
    if (!b) return;
    b.setAttribute("aria-pressed", String(nearAuto));
    $("nearAutoState").textContent = nearAuto ? "On: the nearest chain shows on the chip row each time the app opens." : "Off: Near me looks only when you tap it.";
  }
  function setNearAuto(on, fromHelp) {
    store.set(NEAR_AUTO_KEY, on ? "on" : "off");
    nearAuto = on;
    renderNearToggle();
    const ask = $("nearBody").querySelector("[data-near-ask]");
    if (ask) ask.remove();
    if (data && region === UK) renderChips();
    toast(on ? "The app will look around each time it opens" : "Near me looks only when you tap it");
    if (on) autoNear(fromHelp); // switched on from Help: this tap is the asking, so the phone may prompt once
  }
  $("nearAutoBtn").addEventListener("click", () => setNearAuto(!nearAuto, true));
  renderNearToggle();

  // ---------- the map page (the globe by the title): where you are, as you move, and every place the app knows ----------
  // The UK chains' branches come from the branch list (data/branches.json, as Near me), drawn for the part of the map
  // on screen once it's zoomed in to a town; the city lists' places (UK and abroad) come from cities.json. Your position is followed
  // only while this page is open and the app is in front, and it never leaves the phone.
  const MAP_KM = 1.5, MAP_ZOOM = 13, MAP_PINS = 300; // zoom 13: about 3.5 km across a phone, legible even in London
  // pins: the chains' pins on the map now, by branch, so a redraw adds and removes only the difference; openPin: the
  // one whose popup is open, kept whatever the redraw (opening a popup pans the map)
  const live = { map: null, watch: null, me: null, ring: null, places: null, branches: null, at: null, follow: true, pins: new Map(), openPin: null };
  const setMapStatus = (t) => { $("mapStatus").textContent = t; };
  const awayText = (l) => (live.at ? metres(kmTo(l, live.at)) + " away" : "");
  // narrow enough for a small phone's map, and clear of the hint at the top
  const POPUP = { maxWidth: 230, autoPanPaddingTopLeft: [12, 64], autoPanPaddingBottomRight: [12, 12] };
  function openLiveMap() {
    if (!data) return;
    openDialog($("mapPage"));
    live.follow = true;
    setMapStatus(navigator.geolocation ? "Finding where you are…" : "This phone can't share its location here.");
    $("mapOffline").hidden = !offlineNow;
    drawLiveMap();
  }
  async function drawLiveMap() {
    try { await loadLeaflet(); } catch (e) { setMapStatus("The map couldn't load. Check your signal and try again."); return; }
    if (!$("mapPage").open || live.map) return;
    // the zoom buttons go bottom left, out of the way of the popups and the hint at the top
    const map = L.map($("liveMap"), { zoomControl: false });
    L.control.zoom({ position: "bottomleft" }).addTo(map);
    live.map = map;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors' }).addTo(map);
    live.places = L.layerGroup().addTo(map);
    live.branches = L.layerGroup().addTo(map);
    drawPlacePins();
    // until the phone answers: where you were last seen, else the city on screen, else the whole UK
    const c = city(), last = here || (savedNear() || {}).at;
    if (last) map.setView([last.lat, last.lon], 15);
    else if (c) map.fitBounds([[c.bounds.lat[0], c.bounds.lon[0]], [c.bounds.lat[1], c.bounds.lon[1]]]);
    else map.setView([54.4, -2.5], 5);
    map.on("dragstart", () => { live.follow = false; renderMapButtons(); });
    map.on("moveend", () => { drawBranchPins(); renderMapButtons(); });
    renderMapButtons();
    watchMe();
    mapBranches();
  }
  // the branch list, drawn once it's here (on a weak signal the map shouldn't wait for it); tried again at most
  // every half minute while the map is open, on the next position
  let branchTriedAt = 0;
  async function mapBranches() {
    if (!branchList && Date.now() - branchTriedAt < 30000) return;
    branchTriedAt = Date.now();
    await loadBranches();
    if (!live.map) return;
    drawBranchPins();
    renderMapStatus();
    renderMapButtons();
    if (!branchList) setMapStatus(NO_LIST + " Only the city lists' places show for now.");
  }
  function watchMe() {
    if (live.watch != null || !navigator.geolocation || !live.map || document.hidden) return;
    live.watch = navigator.geolocation.watchPosition(onPosition, (e) => {
      if (e.code !== 1) return; // slow to find, or lost for a moment: the watch carries on
      stopWatch();
      setMapStatus("Location is off for this app, so the map can't show where you are. Check Location Services for Safari in Settings.");
      renderMapButtons();
    }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 30000 });
  }
  function stopWatch() { if (live.watch != null) { navigator.geolocation.clearWatch(live.watch); live.watch = null; } }
  function onPosition(pos) {
    if (!live.map) return;
    const at = { lat: pos.coords.latitude, lon: pos.coords.longitude };
    const ll = [at.lat, at.lon], acc = Math.min(pos.coords.accuracy || 0, 2000);
    const first = !live.at;
    here = live.at = at;
    store.set(NEAR_GRANTED, "1");
    if (!live.me) {
      live.ring = L.circle(ll, { radius: acc, color: "#1e6fd9", weight: 1, fillColor: "#1e6fd9", fillOpacity: 0.12, interactive: false, className: "you-ring" }).addTo(live.map);
      live.me = L.circleMarker(ll, { radius: 8, color: "#ffffff", weight: 3, fillColor: "#1e6fd9", fillOpacity: 1, className: "you-dot" }).bindPopup("You are here").addTo(live.map);
    } else { live.me.setLatLng(ll); live.ring.setLatLng(ll).setRadius(acc); }
    if (live.follow) { if (first) live.map.setView(ll, Math.max(live.map.getZoom(), 15)); else live.map.panTo(ll); }
    if (branchList) renderMapStatus(); else mapBranches();
    renderMapButtons();
  }
  // how many of the chains' branches are around you, worked out on the phone from the list
  function renderMapStatus() {
    const at = live.at;
    if (!at || !branchList) return;
    if (!inUK(at)) { setMapStatus("Outside the UK, the map shows the places from the lists abroad. The chains' branches are in the UK only."); return; }
    let n = 0;
    for (const x of branchList.b) {
      if (!inBox(x, at.lat - 0.015, at.lon - 0.03, at.lat + 0.015, at.lon + 0.03)) continue;
      const b = branchOf(branchList, x);
      if (b && kmTo(b, at) <= MAP_KM) n++;
    }
    setMapStatus((n ? n + (n === 1 ? " branch" : " branches") + " of the app's chains within " + MAP_KM + " km of you" : "None of the app's chains is listed within " + MAP_KM + " km of you") +
      ". From OpenStreetMap's list of " + listDate(branchList.fetched) + ", which misses some" + (n ? "; its hours may be out of date." : "."));
  }
  // a pin: the dot you see, inside a clear circle the size of a fingertip (44 px) that takes the tap
  function addPin(layer, ll, colour, cls, popup) {
    const dot = L.circleMarker(ll, { radius: 8, color: "#ffffff", weight: 2, fillColor: colour, fillOpacity: 0.95, interactive: false }).addTo(layer);
    const hit = L.circleMarker(ll, { radius: 22, stroke: false, fillColor: "#000000", fillOpacity: 0, className: cls }).bindPopup(popup, POPUP).addTo(layer);
    return [dot, hit];
  }
  // the chains' pins take the app's own colour; only the branches on screen are drawn, nearest the middle first, and
  // none while the map shows more than a town (thousands of pins would bury the map and slow the phone)
  function drawBranchPins() {
    if (!live.branches || !live.map) return;
    const want = new Map();
    if (branchList && live.map.getZoom() >= MAP_ZOOM) {
      const v = live.map.getBounds(), mid = v.getCenter(), centre = { lat: mid.lat, lon: mid.lng };
      const shown = [];
      for (const x of branchList.b) {
        if (!inBox(x, v.getSouth(), v.getWest(), v.getNorth(), v.getEast())) continue;
        const b = branchOf(branchList, x);
        if (b) shown.push(b);
      }
      shown.sort((a, b) => kmTo(a, centre) - kmTo(b, centre));
      shown.slice(0, MAP_PINS).forEach((b) => want.set(b.rid + "|" + b.lat + "|" + b.lon, b));
    }
    for (const [key, layers] of live.pins) {
      if (want.has(key) || key === live.openPin) continue;
      layers.forEach((l) => live.branches.removeLayer(l));
      live.pins.delete(key);
    }
    const colour = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    for (const [key, b] of want) {
      if (live.pins.has(key)) continue;
      const layers = addPin(live.branches, [b.lat, b.lon], colour, "pin-branch", () => "<b>" + esc(b.name) + "</b><br>" + esc([awayText(b), openText(b.hours), b.where].filter(Boolean).join(" · ")) +
        '<br><span class="pop-btns"><button type="button" class="link-btn" data-map-menu="' + esc(b.rid) + '">Menu &rsaquo;</button>' +
        '<a class="link-btn" href="https://maps.apple.com/?ll=' + esc(b.lat + "," + b.lon) + "&q=" + encodeURIComponent(b.name) + '" target="_blank" rel="noopener">Directions</a></span>');
      // after the close has finished (and not during the map's own removal), so a pin is never removed mid-close
      layers[1].on("popupopen", () => { live.openPin = key; }).on("popupclose", () => { live.openPin = null; setTimeout(() => { if (live.map) drawBranchPins(); }, 0); });
      live.pins.set(key, layers);
    }
  }
  function drawPlacePins() {
    if (!live.places) return;
    live.places.clearLayers();
    for (const [cid, c] of Object.entries(cities)) {
      for (const p of c.places) {
        for (const l of p.locations) {
          if (l.lat == null || l.lon == null) continue;
          addPin(live.places, [l.lat, l.lon], pinColour(p), "pin-place", () => "<b>" + esc(p.name) + "</b><br>" + esc([awayText(l), l.area, todayLine(p, cityNow(c), [l])].filter(Boolean).join(" · ")) +
            "<br>" + esc(p.claimLabel || CLAIM_TAGS[p.claim]) +
            '<br><span class="pop-btns"><button type="button" class="link-btn" data-map-place="' + esc(p.name) + '" data-city="' + esc(cid) + '">Open &rsaquo;</button>' +
            '<a class="link-btn" href="' + esc(mapLink(p, l)) + '" target="_blank" rel="noopener">Directions</a></span>');
        }
      }
    }
  }
  function renderMapButtons() {
    $("mapFollow").hidden = !live.map || !live.at || live.follow;
    if (!live.map) { $("mapHint").hidden = true; return; }
    const mid = live.map.getCenter();
    // zoomed out over the UK: say why the chains' pins have gone
    $("mapHint").hidden = !branchList || live.map.getZoom() >= MAP_ZOOM || !inUK({ lat: mid.lat, lon: mid.lng });
  }
  function leaveMap(then) { $("mapPage").close(); then(); }
  $("mapBtn").addEventListener("click", openLiveMap);
  $("mapFollow").addEventListener("click", () => {
    live.follow = true;
    if (live.at && live.map) live.map.setView([live.at.lat, live.at.lon], Math.max(live.map.getZoom(), 15));
    renderMapButtons();
  });
  $("mapPage").addEventListener("close", () => {
    stopWatch();
    if (live.map) live.map.remove();
    Object.assign(live, { map: null, me: null, ring: null, places: null, branches: null, at: null, pins: new Map(), openPin: null });
  });
  // the phone's position is watched only while the map is in front of you
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopWatch(); else if ($("mapPage").open) watchMe(); });

  // ---------- warnings page ----------
  // The guide's own warnings in the order that matters to a coeliac: cross-contact, then its gluten free claim, then updates
  // that name a gluten cereal, then other updates, then the rest. The quotes themselves are never touched.
  const GLUTEN_WORD = /\b(gluten|wheat|barley|rye|oats?|malt|cereals?)\b/i;
  const WARN_ORDER = ["cross-contact", "accreditation", "update-gluten", "update", "recipes", "diet", "delivery", "coverage", "nutrition"];
  function warnGroups(notices) {
    const groups = {};
    notices.forEach((n) => {
      const split = n.kind === "update" && GLUTEN_WORD.test(n.text);
      const label = split ? "Allergen updates that name gluten" : n.kind === "update" ? "Other allergen updates" : n.label;
      const g = groups[label] = groups[label] || { label, rank: WARN_ORDER.indexOf(split ? "update-gluten" : n.kind), list: [] };
      g.list.push(n);
    });
    return Object.values(groups).sort((a, b) => (a.rank < 0 ? 99 : a.rank) - (b.rank < 0 ? 99 : b.rank));
  }
  function warningsFor(r) {
    const groups = warnGroups(r.notices || []);
    let html = "";
    if (selected === ALL) html += '<h3 class="w-rest">' + esc(r.name) + "</h3>";
    // a restaurant's own tips lead its page of the sheet, so they're one tap away once folded off the first screen
    if (selected !== ALL && r.tips && r.tips.length) html += '<h4>How to order</h4><div class="rules w-tips">' + tipsHtml(r.tips) + "</div>";
    html += '<p class="muted">From ' + esc(plainGuideName(r)) + (r.area ? ", which covers its " + esc(r.area) + " branches" : "") +
      ((sinceLooked(r) || r.changes) ? '. <button type="button" class="link-btn" data-whatchanged="' + esc(r.id) + '">What changed, noticed ' +
        esc(fmtDate((sinceLooked(r) || r.changes).date)) + " &rsaquo;</button>" : ".") + "</p>";
    if (groups.length) {
      html += "<h4>What " + esc(possessive(r.name)) + " guide says</h4>";
      for (const g of groups) {
        html += '<div class="w-group"><div class="w-label">' + esc(g.label) + "</div>" + g.list.map((n) =>
          '<blockquote class="w-quote">' + esc(n.text) + "<cite>" + esc(n.pages && n.pages.length
            ? "Guide page " + n.pages[0] + (n.pagesTotal > 1 ? ", repeated on " + n.pagesTotal + " pages" : "") : "From the menu") +
          "</cite></blockquote>").join("") + "</div>";
      }
    } else {
      html += '<p class="muted">No warnings were found in this guide. That doesn\'t mean there aren\'t any risks.</p>';
    }
    if (r.gaps && r.gaps.length) {
      html += "<h4>What the guide doesn't tell you</h4><ul class=\"w-gaps\">" + r.gaps.map((g) => "<li>" + esc(g) + "</li>").join("") + "</ul>";
    }
    const decided = r.items.concat(r.avoid).filter((i) => i.decided);
    if (decided.length) {
      html += "<h4>How the app decided some items</h4><ul class=\"notes\">" +
        decided.map((i) => "<li><b>" + esc(i.name) + ":</b> " + esc(i.decided) + "</li>").join("") + "</ul>";
    }
    if (isStale(r)) html += '<p class="w-stale">This guide covered up to ' + esc(fmtDate(r.guide.validUntil)) + ". A newer one may be out.</p>";
    return html;
  }
  function openWarnings() {
    if (!data) return;
    const r = byId(selected);
    $("warnTitle").textContent = r ? r.name + (r.tips && r.tips.length ? ": tips and warnings" : ": warnings") : "Warnings";
    const claim = scope().filter((x) => (x.notices || []).some((n) => n.kind === "accreditation")).map((x) => x.name);
    $("warnBody").innerHTML =
      '<div class="w-intro"><p><b>"No gluten ingredients" means the restaurant\'s guide lists no gluten cereal for that item.</b> ' +
      (claim.length
        ? "It isn't the app's gluten free claim. " + esc(listOr(claim)) + " says it's accredited by Coeliac UK, in its own words below; " +
          "the app still lists items by their ingredients. "
        : "It isn't a gluten free claim: these guides don't call the items listed here \"gluten free\", and none claim to test for gluten or promise " +
          "there's been no contact with it. ") +
      "If you have coeliac disease, ask staff about shared equipment such as toasters, fryers and tongs.</p></div>" +
      scope().map(warningsFor).join('<hr class="w-sep">');
    if ($("info").open) $("info").close();
    openDialog($("warnings"));
  }
  function renderWarnCount() {
    const n = scope().reduce((t, r) => t + (r.notices || []).length + (r.gaps || []).length, 0);
    $("warnCount").textContent = n ? "(" + n + ")" : "";
    const r = byId(selected);
    const all = n + (r && r.tips ? r.tips.length : 0);
    $("stripCount").textContent = all ? "(" + all + ")" : "";
  }
  $("openWarnings").addEventListener("click", openWarnings);
  $("openStrip").addEventListener("click", openWarnings);
  $("openWarnings2").addEventListener("click", openWarnings);
  // "What changed" link in Warnings and in Help: stays reopenable until the next guide, unlike the dismissable news banner
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-whatchanged]");
    if (b) openChanges(byId(b.dataset.whatchanged));
  });

  // ---------- coeliac card (phrases for staff) ----------
  let phrases = {};
  async function loadPhrases() {
    try {
      const res = await fetch("phrases.json", { cache: "no-cache" });
      if (res.ok) phrases = await res.json();
    } catch (e) { /* offline and never cached: no card */ }
    $("cardLangs").textContent = Object.values(phrases).map((p) => p.language).join(", ") || "none yet";
    if (data) renderCardLaunch();
    if (city()) renderCity();
  }
  async function loadCities() {
    try {
      const res = await fetch("cities.json", { cache: "no-cache" });
      if (res.ok) cities = await res.json();
    } catch (e) { /* offline and never cached: UK menus only */ }
    if (region !== UK && !cities[region]) { // not a city (or the list couldn't load): back to the menus
      if (region === hashRid) selected = region; // the link was to a restaurant after all
      region = UK;
    }
    render();
    if (data && $("picker").open) renderPicker(); // the first-visit chooser may have opened before the cities arrived
    drawPlacePins(); // the map page may have opened before them too
    importReady.cities = true;
    maybeImport();
  }
  function renderCardLaunch() {
    const r = byId(selected);
    let langs = Object.keys(phrases);
    langs = r ? langs.filter((l) => l === r.language) : [];
    const el = $("cardLaunch");
    el.hidden = !langs.length;
    el.innerHTML = langs.map((l) => '<button type="button" class="pill-btn" data-lang="' + esc(l) + '">Show ' + esc(phrases[l].language) +
      " coeliac card</button>").join("");
  }
  // The screen stays lit while staff read a card. The phone lets go of it whenever the app is hidden, so ask again on coming back.
  let wake = null;
  async function keepAwake() {
    if (wake || !("wakeLock" in navigator)) return;
    try {
      wake = await navigator.wakeLock.request("screen");
      wake.addEventListener("release", () => { wake = null; });
    } catch (e) { wake = null; /* refused, for example on low battery */ }
  }
  function letGo() { if (wake) { const w = wake; wake = null; w.release().catch(() => {}); } }
  // Each phrase can be read aloud by the phone's own voice for that language (offline), for a noisy counter.
  const SPEECH_LANG = { de: "de-DE", nl: "nl-NL", fr: "fr-FR", es: "es-ES", it: "it-IT" };
  const canSpeak = () => !!window.speechSynthesis && typeof window.SpeechSynthesisUtterance === "function";
  function voiceFor(lang) {
    const want = (SPEECH_LANG[lang] || lang).toLowerCase();
    const vs = speechSynthesis.getVoices();
    return vs.find((v) => v.lang.toLowerCase().replace("_", "-") === want) || vs.find((v) => v.lang.toLowerCase().startsWith(lang)) || null;
  }
  function say(text, lang) {
    if (!canSpeak()) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = SPEECH_LANG[lang] || lang;
    const v = voiceFor(lang);
    if (v) u.voice = v;
    u.rate = 0.9;
    speechSynthesis.speak(u);
  }
  // the phone may have no voice for the language yet (iPhone: Settings > Accessibility > Spoken Content > Voices)
  function voiceNote(lang, language) {
    if (!canSpeak() || !speechSynthesis.getVoices().length || voiceFor(lang)) return "";
    return '<p class="muted">No ' + esc(language) + " voice is installed on this phone, so Say it may use another language's voice. Add one under Settings, Accessibility, Spoken Content, Voices.</p>";
  }
  let cardLang = "";
  if (canSpeak()) {
    speechSynthesis.getVoices(); // asks the phone to load its list; the note is redrawn once it arrives
    speechSynthesis.addEventListener("voiceschanged", () => { const n = $("cardBody").querySelector(".voice-note"); if (n && cardLang) n.innerHTML = voiceNote(cardLang, phrases[cardLang].language); });
  }
  function openCard(lang) {
    const p = phrases[lang];
    if (!p) return;
    cardLang = lang;
    $("cardTitle").textContent = p.language + " coeliac card";
    $("cardBody").innerHTML = '<div class="phrase-list" lang="' + esc(lang) + '">' + p.card.map((c, n) =>
      '<div class="phrase"><p class="ph-text">' + esc(c.text) + '</p><p class="ph-en" lang="en-GB">' + esc(c.en) + "</p>" +
      (canSpeak() ? '<button type="button" class="say-btn" lang="en-GB" data-say="' + n + '">Say it</button>' : "") + "</div>").join("") + "</div>" +
      '<div class="voice-note">' + voiceNote(lang, p.language) + "</div>" +
      "<h3>Words to look for</h3><dl class=\"words\">" + p.words.map(([w, en]) =>
        '<div><dt lang="' + esc(lang) + '">' + esc(w) + "</dt><dd>" + esc(en) + "</dd></div>").join("") + "</dl>" +
      '<p class="muted">Turn the screen towards staff. Phrases written by Claude and not yet checked by a native speaker.</p>';
    openDialog($("gfcard"));
    keepAwake();
  }
  $("cardLaunch").addEventListener("click", (e) => { const b = e.target.closest("[data-lang]"); if (b) openCard(b.dataset.lang); });
  $("gfcard").addEventListener("close", () => { if (canSpeak()) speechSynthesis.cancel(); });

  // ---------- staff card: one item, how to order it, in large type to show at the counter ----------
  function orderLine(r, i) {
    const label = r.optionLabel || "option";
    const opt = (o) => (new RegExp("\\b" + label + "$", "i").test(o) ? o : o + " " + label);
    switch (i.order) {
      case "asis": return "As it comes, please.";
      case "any": return "As it comes, please. Any " + label + " is fine.";
      case "except": return "Please don't use " + listOr(i.not.map(opt)) + ". Any other " + label + " is fine.";
      case "swap": {
        const std = i.standard || i.not[0];
        if (i.ok.length <= 2) return "With " + listOr(i.ok.map(opt)) + " instead of " + opt(std) + ", please.";
        const also = i.not.filter((n) => n !== std);
        return "Any other " + label + " instead of " + opt(std) + (also.length ? " (not " + listOr(also.map(opt)) + ")" : "") + ", please.";
      }
      default: return i.note.replace(/[.!]?$/, ".");
    }
  }
  function openStaff(r, i) {
    const local = phrases[r.language];
    $("staffBody").innerHTML = '<p class="staff-where">' + esc(r.name) + "</p>" +
      '<p class="staff-name">' + esc(i.name) + "</p>" +
      '<p class="staff-sec">' + esc([shortSection(i.section), i.sub && cap(i.sub)].filter(Boolean).join(" · ")) + "</p>" +
      (i.original ? '<p class="staff-orig" lang="' + esc(r.language || "") + '">' + esc(i.original) + "</p>" : "") +
      '<p class="staff-order">' + esc(orderLine(r, i)) + "</p>" +
      (local ? local.card.slice(0, 2).map((c) => '<p class="staff-coeliac" lang="' + esc(r.language) + '">' + esc(c.text) + "</p>").join("") : "") +
      '<p class="staff-coeliac">I have coeliac disease, so I can\'t have any gluten, even a trace.</p>' +
      '<p class="staff-coeliac">Could you please use clean equipment?</p>' +
      '<p class="muted">Turn the screen towards staff. From ' + esc(possessive(r.name)) + " allergen guide" +
      (i.pages && i.pages.length ? ", " + esc(pageText(i.pages).toLowerCase()) : "") + ".</p>";
    openDialog($("staff"));
    keepAwake();
  }
  $("list").addEventListener("click", (e) => {
    const b = e.target.closest(".staff-btn");
    if (!b) return;
    e.preventDefault();
    const [rid, section, ...rest] = b.dataset.staff.split("|");
    const r = byId(rid);
    const i = r && r.items.find((x) => x.section === section && x.name === rest.join("|"));
    if (i) openStaff(r, i);
  });

  // ---------- build an order: several items, parts of dishes included, on one staff card ----------
  // What's in an order is only ever a key into the restaurant's own list of items with no gluten ingredients (r.items),
  // never into the Avoid list. A key that no longer resolves (the item is now on the Avoid list, gone from the guide,
  // or an ingredient listed on its own) is dropped whenever the order is next looked at, and the builder says so.
  const ORDER_KEY = "gf-order"; // { <restaurant id>: [keys, as favKey] }
  let orders = (() => { try { const o = JSON.parse(store.get(ORDER_KEY) || "{}"); return o && typeof o === "object" && !Array.isArray(o) ? o : {}; } catch (e) { return {}; } })();
  const saveOrders = () => store.set(ORDER_KEY, JSON.stringify(orders));
  const canOrder = (i) => i.role !== "ingredient"; // dishes and parts of dishes; an ingredient listed on its own isn't something to order
  const orderable = (r, k) => r.items.find((i) => canOrder(i) && favKey(r, i) === k) || null;
  const orderNotes = {}; // what was dropped from each order, shown in the builder until it's closed
  function orderItems(r) {
    const keys = Array.isArray(orders[r.id]) ? orders[r.id].filter((k) => typeof k === "string") : [];
    const items = [], dropped = [];
    for (const k of keys) {
      const i = orderable(r, k);
      if (i) { if (!items.includes(i)) items.push(i); } else dropped.push(k);
    }
    if (dropped.length || items.length !== keys.length) {
      orders[r.id] = items.map((i) => favKey(r, i));
      saveOrders();
      orderNotes[r.id] = (orderNotes[r.id] || []).concat(dropped.map((k) => {
        const name = k.split("|").slice(2).join("|");
        const avoid = r.avoid.some((a) => favKey(r, a) === k || norm(a.name) === norm(name));
        return name + (avoid ? " (now on the Avoid list)" : " (not something to order from this guide)");
      }));
    }
    return items;
  }
  // true: added; false: taken out; null: refused, because it isn't on the list of items with no gluten ingredients
  function toggleOrder(r, k) {
    if (!orderable(r, k)) { toast("That can't go in an order: it isn't on " + possessive(r.name) + " list of items with no gluten ingredients"); return null; }
    const keys = orderItems(r).map((x) => favKey(r, x));
    const at = keys.indexOf(k);
    if (at < 0) keys.push(k); else keys.splice(at, 1);
    orders[r.id] = keys;
    saveOrders();
    syncOrderButtons(r);
    return at < 0;
  }
  // the buttons on the page follow the order: each item's "Add to order", and the pill at the top
  function syncOrderButtons(r) {
    const keys = new Set(orders[r.id] || []);
    document.querySelectorAll("#list .order-btn[data-order]").forEach((b) => {
      if (!b.dataset.order.startsWith(r.id + "|")) return;
      const on = keys.has(b.dataset.order);
      b.setAttribute("aria-pressed", on);
      b.textContent = on ? "✓ In order" : "Add to order";
    });
    if (byId(selected) === r) document.querySelectorAll("#chips [data-order-open]").forEach((b) => { b.innerHTML = orderChipText(r); });
  }
  const ORDER_INTRO = "Tick what you'd like, for one staff card with everything on it.";
  function renderOrder(r) {
    const items = orderItems(r);
    const keys = new Set(items.map((i) => favKey(r, i)));
    const cfg = r.order || {};
    const first = (cfg.first || []).filter((s) => r.sections.includes(s));
    const secs = first.concat(r.sections.filter((s) => !first.includes(s)));
    const notes = orderNotes[r.id] || [];
    // one short paragraph: only items with no gluten ingredients have a box to tick, and each section's Avoid items
    // fold under it saying they can't be added
    let html = "<p>" + esc(cfg.intro || ORDER_INTRO) + " The card ends with " + esc(possessive(r.name)) + " own cross-contact warning.</p>";
    if (notes.length) html += '<div class="chg-note bad"><b>Taken out of your order:</b> ' + notes.map(esc).join("; ") + ".</div>";
    for (const s of secs) {
      const ok = r.items.filter((i) => i.section === s && canOrder(i));
      const av = r.avoid.filter((a) => a.section === s);
      if (!ok.length && !av.length) continue;
      html += "<h3>" + esc(shortSection(s)) + "</h3>";
      let sub = null;
      for (const i of ok) {
        if ((i.sub || "") !== sub) { sub = i.sub || ""; if (sub) html += '<div class="sub-h">' + esc(cap(sub)) + "</div>"; }
        const k = favKey(r, i);
        // only a tag that adds something ("Any milk except oat", "Ask"): every tickable item has no gluten ingredients
        const [cls, label] = tagFor(r, i);
        html += '<label class="o-row"><input type="checkbox" data-key="' + esc(k) + '"' + (keys.has(k) ? " checked" : "") + '><span class="nm">' + esc(i.name) +
          (i.order === "modify" ? "<small>" + esc(i.note) + "</small>" : i.original ? '<small lang="' + esc(r.language || "") + '">' + esc(i.original) + "</small>" : "") +
          "</span>" + (cls === "t-asis" ? "" : '<span class="tag ' + cls + '">' + esc(label) + "</span>") + "</label>";
      }
      if (av.length) {
        html += '<details class="o-avoid"><summary>' + av.length + (av.length === 1 ? " item" : " items") + " on the Avoid list: can't be added</summary>" +
          av.map((a) => '<div class="o-row off"><span class="nm">' + esc(a.name) + '</span><span class="tag t-bad">' + esc(a.tag || a.gluten.map(cap).join(" & ")) + "</span></div>").join("") +
          "</details>";
      }
    }
    $("orderTitle").textContent = "Build an order"; // the restaurant is in the header and on the card
    $("orderBody").innerHTML = html;
    renderOrderFoot(r);
  }
  function renderOrderFoot(r) {
    const n = orderItems(r).length;
    $("orderCount").textContent = n ? n + (n === 1 ? " item" : " items") + " in your order" : "Nothing ticked yet";
    $("orderCard").disabled = !n;
    $("orderClear").hidden = !n;
  }
  let orderFor = null; // the restaurant whose order the builder shows
  function openOrder(r) {
    if (!r) return;
    orderFor = r;
    renderOrder(r);
    openDialog($("order"));
  }
  // the chain's own cross-contact warning for the foot of the card: the one that says so most plainly
  function crossContact(r) {
    const cc = (r.notices || []).filter((n) => n.kind === "cross-contact");
    return cc.find((n) => /cross[ -]?contam|cannot guarantee|can't guarantee|\btraces?\b|always/i.test(n.text)) || cc[0] || null;
  }
  function openOrderCard(r) {
    const items = orderItems(r);
    if (!items.length) { toast("Nothing in the order yet"); return; }
    const local = phrases[r.language];
    const warn = crossContact(r);
    const pages = [...new Set(items.flatMap((i) => i.pages || []))].sort((a, b) => a - b);
    $("staffBody").innerHTML = '<p class="staff-where">' + esc(r.name) + '</p><p class="staff-name">My order</p>' +
      '<ul class="staff-list">' + items.map((i) => "<li><b>" + esc(i.name) + "</b>" +
        (i.original ? '<small lang="' + esc(r.language || "") + '">' + esc(i.original) + "</small>" : "") +
        "<small>" + esc([shortSection(i.section), i.sub && cap(i.sub)].filter(Boolean).join(" · ")) + "</small>" +
        (i.order !== "asis" ? '<span class="staff-ask">' + esc(orderLine(r, i)) + "</span>" : "") + "</li>").join("") + "</ul>" +
      '<p class="staff-order">' + esc((r.order && r.order.cardLine) || "Only what's listed here, please.") + "</p>" +
      (local ? local.card.slice(0, 2).map((c) => '<p class="staff-coeliac" lang="' + esc(r.language) + '">' + esc(c.text) + "</p>").join("") : "") +
      '<p class="staff-coeliac">I have coeliac disease, so I can\'t have any gluten, even a trace.</p>' +
      '<p class="staff-coeliac">Could you please use clean equipment?</p>' +
      (warn ? '<blockquote class="w-quote staff-warn">' + esc(warn.text) + "<cite>" + esc(possessive(r.name)) + " allergen guide" +
        (warn.pages && warn.pages.length ? ", page " + esc(warn.pages[0]) : "") + "</cite></blockquote>" : "") +
      '<p class="muted">Turn the screen towards staff. From ' + esc(possessive(r.name)) + " allergen guide" + (pages.length ? ", " + esc(pageText(pages).toLowerCase()) : "") + ".</p>";
    openDialog($("staff"));
    keepAwake();
  }
  $("orderBody").addEventListener("change", (e) => {
    const cb = e.target.closest("input[data-key]");
    if (!cb || !orderFor) return;
    cb.checked = toggleOrder(orderFor, cb.dataset.key) === true;
    renderOrderFoot(orderFor);
  });
  $("orderClear").addEventListener("click", () => { if (!orderFor) return; orders[orderFor.id] = []; saveOrders(); renderOrder(orderFor); syncOrderButtons(orderFor); });
  $("orderCard").addEventListener("click", () => { if (orderFor) openOrderCard(orderFor); });
  $("order").addEventListener("close", () => { if (orderFor) delete orderNotes[orderFor.id]; orderFor = null; });
  function toggleOrderButton(key) {
    const r = byId(key.split("|")[0]);
    if (!r) return;
    const on = toggleOrder(r, key);
    if (on !== null) toast(on ? "Added to your " + r.name + " order (" + orderItems(r).length + ")" : "Taken out of your " + r.name + " order");
  }

  // ---------- add a menu (owner only): uploads go to inbox/ on the "uploads" branch, never to main ----------
  const KEY_KEY = "gf-github-key";
  const UPLOAD_BRANCH = "uploads";
  const repo = (() => {
    const m = location.hostname.match(/^([^.]+)\.github\.io$/);
    const seg = location.pathname.split("/").filter(Boolean)[0];
    return m && seg ? { owner: m[1], name: seg } : { owner: "T-800IsInevitable", name: "gf-drinks" };
  })();
  const api = (path, opts = {}) => fetch("https://api.github.com/repos/" + repo.owner + "/" + repo.name + path, {
    ...opts,
    headers: { Accept: "application/vnd.github+json", Authorization: "Bearer " + store.get(KEY_KEY), "X-GitHub-Api-Version": "2022-11-28", ...(opts.headers || {}) },
  });
  function showUploadState() {
    const has = !!store.get(KEY_KEY);
    $("keySetup").hidden = has;
    $("uploadFields").hidden = !has;
    $("repoName").textContent = repo.name;
    // what Ask for it does from this phone: files it (with the key), or passes it to the owner as a link
    $("reqHow").textContent = has ? "Know somewhere that should be here? Its own allergen information is looked up and added for you to approve."
      : "Know somewhere that should be here? From this phone it goes to the app's owner as a link; one tap there files it, and its own allergen information is then looked up and added once the owner approves.";
  }
  function openAddMenu() {
    ["info", "picker"].forEach((id) => { if ($(id).open) $(id).close(); });
    showUploadState();
    renderRequests();
    $("upStatus").textContent = "";
    $("reqStatus").textContent = "";
    openDialog($("upload"));
  }
  $("openUpload").addEventListener("click", openAddMenu);
  $("uploadClose").addEventListener("click", () => $("upload").close());
  $("upload").addEventListener("click", (e) => { if (e.target === $("upload")) $("upload").close(); });
  $("keySave").addEventListener("click", async () => {
    const k = $("keyInput").value.trim();
    if (!k) { toast("Paste your GitHub key first"); return; }
    store.set(KEY_KEY, k);
    try {
      const res = await api("");
      const info = res.ok ? await res.json() : null;
      if (!info || !(info.permissions && info.permissions.push)) throw new Error(res.status);
      $("keyInput").value = "";
      toast("Key saved");
      showUploadState();
    } catch (e) {
      store.remove(KEY_KEY);
      toast("That key can't upload to " + repo.name + ". Check it has Contents: Read and write.");
    }
  });
  // A big "Take photos or choose a PDF" button stands in for the browser's own file box, with a small preview of each pick
  function filePreview(input, box) {
    const show = () => {
      box.querySelectorAll("img").forEach((i) => URL.revokeObjectURL(i.src));
      box.textContent = "";
      const files = [...input.files];
      files.forEach((f) => {
        const t = document.createElement("span");
        t.className = "thumb";
        if (/^image\//.test(f.type)) {
          const img = document.createElement("img");
          img.alt = f.name;
          img.src = URL.createObjectURL(f);
          t.appendChild(img);
        } else {
          t.append("PDF");
          const small = document.createElement("small");
          small.textContent = f.name;
          t.appendChild(small);
        }
        box.appendChild(t);
      });
      if (files.length) {
        const c = document.createElement("span");
        c.className = "thumb-count";
        c.textContent = files.length === 1 ? "1 file chosen" : files.length + " files chosen";
        box.appendChild(c);
      }
    };
    input.addEventListener("change", show);
    return show;
  }
  const showShareFiles = filePreview($("shareFiles"), $("shareThumbs"));
  const showUpFiles = filePreview($("upFiles"), $("upThumbs"));
  // Anyone without the key sends the menu to the owner through the iPhone share sheet (Messages, WhatsApp, Mail…)
  $("shareSend").addEventListener("click", async () => {
    const files = [...$("shareFiles").files];
    const status = $("shareStatus");
    status.classList.remove("done");
    if (!files.length) { status.textContent = "Pick at least one photo or PDF of the allergen menu first."; return; }
    const name = $("shareName").value.trim();
    const msg = { files, title: "Allergen menu", text: "Allergen menu" + (name ? " for " + name : "") + ", for Twoo's Treat Temple" };
    if (!(navigator.canShare && navigator.canShare({ files }))) {
      status.textContent = "This phone can't send files from here. Send the photos by message instead.";
      return;
    }
    try {
      await navigator.share(msg);
      status.textContent = "Sent. Thank you!";
      status.classList.add("done");
      $("shareFiles").value = "";
      showShareFiles();
    } catch (e) {
      if (e.name !== "AbortError") status.textContent = "Couldn't send: " + e.message + ". Send the photos by message instead.";
    }
  });
  $("keyForget").addEventListener("click", () => { store.remove(KEY_KEY); showUploadState(); toast("Key removed from this phone"); });

  const slug = (s) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "menu";
  const toB64 = (blob) => new Promise((ok, bad) => {
    const fr = new FileReader();
    fr.onload = () => ok(String(fr.result).split(",")[1]);
    fr.onerror = () => bad(fr.error);
    fr.readAsDataURL(blob);
  });
  // Photos (including iPhone HEIC) are re-saved as JPEG, max 2400px, so they're readable and small.
  async function toJpeg(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = await new Promise((ok, bad) => {
        const i = new Image();
        i.onload = () => ok(i);
        i.onerror = () => bad(new Error("couldn't read the photo " + file.name));
        i.src = url;
      });
      const scale = Math.min(1, 2400 / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * scale);
      c.height = Math.round(img.naturalHeight * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      return await new Promise((ok, bad) => c.toBlob((b) => (b ? ok(b) : bad(new Error("couldn't save the photo " + file.name))), "image/jpeg", 0.88));
    } finally { URL.revokeObjectURL(url); }
  }
  // GitHub's answer, or an error saying what went wrong. 401, or a 403 that isn't GitHub's rate limit, means the
  // saved key no longer works, so it's removed. A rate limit is GitHub's, not the key's: the key stays.
  async function gh(res, what) {
    if (res.ok) return res.json();
    const body = await res.json().catch(() => ({}));
    const limited = res.status === 429 || res.headers.get("x-ratelimit-remaining") === "0" || /rate limit/i.test(body.message || "");
    if (res.status === 401 || (res.status === 403 && !limited)) {
      store.remove(KEY_KEY);
      throw new Error("EXPIRED_KEY");
    }
    const err = new Error(limited ? "GitHub is limiting uploads for now, so wait an hour" : (body.message || "HTTP " + res.status) + " while " + what);
    err.status = res.status;
    throw err;
  }
  const send = (path, body, method = "POST") => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  // Every file goes into one commit (the files, then the folder, then the commit, then moving the branch on to it),
  // so an upload arrives whole or not at all: a half-finished folder is never left for the daily scan.
  // Returns false if the same files were already there (an earlier try that worked but whose answer was lost).
  async function commitFiles(files, message) {
    const entries = [];
    for (const f of files) {
      const blob = await gh(await send("/git/blobs", { content: f.b64, encoding: "base64" }), "saving " + f.path.split("/").pop());
      entries.push({ path: f.path, mode: "100644", type: "blob", sha: blob.sha });
    }
    for (let tries = 1; ; tries++) {
      const ref = await api("/git/ref/heads/" + UPLOAD_BRANCH);
      const fresh = ref.status === 404; // the first upload starts the branch from main
      const parent = (await gh(fresh ? await api("/git/ref/heads/main") : ref, "reading the branch")).object.sha;
      const base = (await gh(await api("/git/commits/" + parent), "reading the branch")).tree.sha;
      const tree = (await gh(await send("/git/trees", { base_tree: base, tree: entries }), "saving the folder")).sha;
      if (tree === base && !fresh) return false;
      // the app's own name as the author, so an upload never reads as a commit the owner made by hand
      const commit = (await gh(await send("/git/commits", { message, tree, parents: [parent], author: { name: "Twoo's Treat Temple app", email: "app@gf-drinks.invalid" } }), "saving the upload")).sha;
      const moved = fresh ? await send("/git/refs", { ref: "refs/heads/" + UPLOAD_BRANCH, sha: commit })
        : await send("/git/refs/heads/" + UPLOAD_BRANCH, { sha: commit, force: false }, "PATCH");
      if (moved.ok) return true;
      // the branch moved (or was made) in the meantime: build on top of it and try again
      if (tries < 3 && (moved.status === 422 || moved.status === 409)) continue;
      await gh(moved, "finishing the upload");
    }
  }
  // What's being uploaded, kept until it arrives, so trying again sends the same folder and the same files:
  // a retry after a lost answer can't make a second copy.
  let pending = null;
  $("uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("upName").value.trim();
    const area = $("upArea").value.trim();
    const notes = $("upNotes").value.trim();
    const files = [...$("upFiles").files];
    const status = $("upStatus");
    status.classList.remove("done");
    if (!name || !area || !files.length) { status.textContent = "Add the restaurant, the city or country, and at least one file."; return; }
    const btn = $("upSend");
    btn.disabled = true;
    const key = JSON.stringify([name, area, notes, files.map((f) => [f.name, f.size, f.lastModified])]);
    try {
      if (!pending || pending.key !== key) {
        const now = new Date();
        const folder = "inbox/" + now.toISOString().slice(0, 16).replace(/:/g, "") + "-" + slug(name) + "-" + slug(area);
        const out = [];
        let n = 0;
        for (const f of files) {
          n++;
          status.textContent = "Getting file " + n + " of " + files.length + " ready…";
          const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
          const fname = isPdf ? (files.length > 1 ? "menu-" + n + ".pdf" : "menu.pdf") : "page-" + n + ".jpg";
          out.push({ path: folder + "/" + fname, b64: await toB64(isPdf ? f : await toJpeg(f)) });
        }
        const meta = { restaurant: name, area, notes, files: files.length, uploadedAt: now.toISOString(), uploadedFrom: "Twoo's Treat Temple app" };
        out.push({ path: folder + "/upload.json", b64: btoa(unescape(encodeURIComponent(JSON.stringify(meta, null, 2)))) });
        pending = { key, folder, files: out };
      }
      status.textContent = "Uploading…";
      await commitFiles(pending.files, "Upload " + name + " menu (" + pending.folder.split("/").pop() + ")");
      pending = null;
      status.textContent = "Uploaded. It'll be scanned within a day and sent to GitHub for you to approve.";
      status.classList.add("done");
      $("uploadForm").reset();
      showUpFiles();
      toast("Menu uploaded");
    } catch (err) {
      if (err.message === "EXPIRED_KEY") {
        status.textContent = "This GitHub key no longer works (it may have expired). Make a new one below.";
        showUploadState();
      } else {
        const why = err instanceof TypeError ? "no connection" : err.message; // fetch fails with a TypeError offline
        status.textContent = "The upload didn't finish (" + why + "). Try again when you have signal: it's safe, and it won't make a second copy.";
      }
    } finally {
      btn.disabled = false;
    }
  });

  // ---------- ask for a place by name ----------
  // The app can't look a place up itself (no server, and its security policy allows only GitHub), so the name goes
  // where the scan routine already looks: inbox/requests/ on the uploads branch, from the phone with the upload key,
  // or as a link to that phone from any other. The routine finds the place's own allergen information and opens a
  // pull request; nothing reaches the app without the owner's merge.
  const REQ_KEY = "gf-requests"; // asked for from this phone: [{ name, area, url, at, how: "filed" | "shared" }]
  const requests = (() => { try { const a = JSON.parse(store.get(REQ_KEY) || "[]"); return Array.isArray(a) ? a.slice(-30) : []; } catch (e) { return []; } })();
  const saveRequests = () => store.set(REQ_KEY, JSON.stringify(requests.slice(-30)));
  const sameName = (a, b) => norm(a).replace(/[^a-z0-9]/g, "") === norm(b).replace(/[^a-z0-9]/g, "");
  const inApp = (name) => (data ? data.restaurants.find((r) => sameName(r.name, name) || (Array.isArray(r.osm) && r.osm.some((o) => sameName(o, name)))) : null);
  function renderRequests() {
    const el = $("reqList");
    el.hidden = !requests.length;
    // honest about where each one stands: in the app, or asked on a date and not in yet (and after a week, worth asking about)
    el.innerHTML = requests.length ? "<p><b>Asked for from this phone</b></p><ul class=\"req-list\">" + requests.slice().reverse().map((q) => {
      const r = inApp(q.name);
      const old = Date.now() - new Date(q.at || 0).getTime() > 7 * 864e5;
      return "<li>" + esc(q.name) + (q.area ? " (" + esc(q.area) + ")" : "") + ": " + (r
        ? 'in the app <button type="button" class="link-btn" data-gotorest-req="' + esc(r.id) + '">Open &rsaquo;</button>'
        : (q.how === "filed" ? "asked " : "sent to the owner ") + esc(fmtDate(String(q.at || "").slice(0, 10))) + " · not in the app yet" + (old ? " · ask the owner whether it was found" : "")) + "</li>";
    }).join("") + "</ul>" : "";
  }
  const requestLink = (q) => appUrl() + "#request=" + toB64url(JSON.stringify({ v: 1, name: q.name, area: q.area, url: q.url }));
  function readRequestCode(code) {
    try {
      const d = JSON.parse(fromB64url(code));
      const s = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "");
      const q = { name: s(d.name, 80), area: s(d.area, 60), url: s(d.url, 200) };
      if (!/^https:\/\/[^\s/]+\.[^\s/]+/.test(q.url)) q.url = "";
      return q.name ? q : null;
    } catch (e) { return null; }
  }
  async function askForPlace() {
    const name = $("reqName").value.trim(), area = $("reqArea").value.trim();
    let url = $("reqUrl").value.trim();
    const status = $("reqStatus");
    status.classList.remove("done");
    if (!name || !area) { status.textContent = "Add the place's name and its city or country."; return; }
    if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
    if (url && !/^https:\/\/[^\s/]+\.[^\s/]+/.test(url)) { status.textContent = "That website address doesn't look right. Leave it out if you're not sure."; return; }
    const have = inApp(name);
    if (have) {
      status.innerHTML = "<b>" + esc(have.name) + "</b> is already in the app. " + '<button type="button" class="link-btn" data-gotorest-req="' + esc(have.id) + '">Open it &rsaquo;</button>';
      return;
    }
    const q = { name, area, url, at: new Date().toISOString() };
    const btn = $("reqSend");
    btn.disabled = true;
    try {
      if (store.get(KEY_KEY)) {
        status.textContent = "Sending…";
        const file = "inbox/requests/" + q.at.slice(0, 16).replace(/:/g, "") + "-" + slug(name) + "-" + slug(area) + ".json";
        const meta = { name, area, url, requestedAt: q.at, requestedFrom: "Twoo's Treat Temple app" };
        await commitFiles([{ path: file, b64: btoa(unescape(encodeURIComponent(JSON.stringify(meta, null, 2)))) }], "Request " + name + " (" + area + ")");
        q.how = "filed";
        status.textContent = "Asked. Its allergen information will be looked up and sent to GitHub for you to approve.";
      } else {
        const sent = await shareOrCopy("Please add " + name + " to Treat Temple", "Could you add " + name + " (" + area + ") to Twoo's Treat Temple? Open this link on your phone to file it.",
          requestLink(q), "Link copied. Send it to whoever looks after the app.");
        if (!sent) { status.textContent = "Not sent."; return; }
        q.how = "shared";
        status.textContent = "Sent to the app's owner. Thank you!";
      }
      status.classList.add("done");
      requests.push(q);
      saveRequests();
      renderRequests();
      ["reqName", "reqArea", "reqUrl"].forEach((id) => { $(id).value = ""; });
    } catch (err) {
      if (err.message === "EXPIRED_KEY") { status.textContent = "This GitHub key no longer works (it may have expired). Make a new one below."; showUploadState(); }
      else status.textContent = "It didn't send (" + (err instanceof TypeError ? "no connection" : err.message) + "). Try again when you have signal.";
    } finally {
      btn.disabled = false;
    }
  }
  $("reqSend").addEventListener("click", askForPlace);
  ["reqName", "reqArea", "reqUrl"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); askForPlace(); } }));
  // a request link (#request=...) from another phone fills the fields in; a tap on Ask for it files it (a link alone files nothing)
  function openRequestFrom(code) {
    const q = readRequestCode(code);
    if (!q) { toast("That request link is damaged. Ask for it to be sent again."); return; }
    openAddMenu();
    $("reqName").value = q.name;
    $("reqArea").value = q.area;
    $("reqUrl").value = q.url;
    $("reqStatus").textContent = store.get(KEY_KEY) ? "From a link. Tap Ask for it to file it." : "From a link. This phone doesn't hold the upload key, so Ask for it passes it on again.";
    $("reqName").focus();
  }

  // ---------- share an item, and "Something wrong?" ----------
  function openReport(subject, lines) {
    $("reportSubject").textContent = subject;
    $("reportText").value = ["Something looks wrong in Twoo's Treat Temple.", ...lines, "", "What happened: "].join("\n");
    $("reportIssue").hidden = !store.get(KEY_KEY); // only for whoever holds the upload key, which is the app's owner
    openDialog($("report"));
    $("reportText").focus();
    $("reportText").setSelectionRange($("reportText").value.length, $("reportText").value.length);
  }
  function reportItem(r, i) {
    const shown = i.order ? howText(r, i) : "Avoid: " + (i.reason || "contains " + (i.gluten || []).join(" and ").toLowerCase());
    openReport(i.name + " at " + r.name, ["Restaurant: " + r.name, "Item: " + i.name + " (" + shortSection(i.section) + ")", "The app shows: " + shown,
      "Guide: " + plainGuideName(r) + (i.pages && i.pages.length ? ", " + pageText(i.pages).toLowerCase() : ""), "Link: " + itemUrl(r, i)]);
  }
  function reportPlace(p) {
    const c = city();
    openReport(p.name + " in " + c.name, ["Place: " + p.name + " (" + c.name + ")", "The app shows: " + (p.claimLabel || CLAIM_TAGS[p.claim]),
      "List checked: " + fmtDate(c.checked), "Link: " + appUrl() + "#" + region]);
  }
  // share text (or a link) through the phone's share sheet, else copy it; true if it went somewhere
  async function shareOrCopy(title, text, url, copied) {
    if (navigator.share) {
      try { await navigator.share(url ? { title, text, url } : { title, text }); return true; } catch (e) { return false; /* share sheet closed */ }
    }
    try { await navigator.clipboard.writeText(url || text); toast(copied); return true; } catch (e) { toast(url || "Couldn't copy it. Select the text and copy it by hand."); return false; }
  }
  const shareLink = (title, text, url) => shareOrCopy(title, text, url, "Link copied");
  $("reportSend").addEventListener("click", async () => {
    if (await shareOrCopy("Something wrong in Treat Temple", $("reportText").value, "", "Message copied. Paste it into a message.")) $("report").close();
  });
  $("reportIssue").addEventListener("click", () => {
    const [first, ...rest] = $("reportText").value.split("\n").filter((l) => l.trim());
    const subject = $("reportSubject").textContent;
    window.open("https://github.com/" + repo.owner + "/" + repo.name + "/issues/new?title=" + encodeURIComponent("Something wrong: " + subject) +
      "&body=" + encodeURIComponent([first, ...rest].join("\n")), "_blank", "noopener");
  });
  $("reportClose").addEventListener("click", () => $("report").close());

  // ---------- a link to one item (#restaurant/item) ----------
  function showItem(rid, sl) {
    const r = byId(rid);
    if (!r) return;
    select(rid);
    const found = r.items.concat(r.avoid).find((x) => itemSlug(r, x) === sl);
    if (!found) { // renamed or gone since the link was made: open the restaurant with the closest matches searched for
      $("q").value = sl.split("--")[0].replace(/-/g, " ");
      syncSearching();
      renderStatus();
      renderList();
      toast("That item has changed, so here are the closest matches");
      return;
    }
    if (!visible(kindOf(found))) { pick = { straight: false, change: false, gluten: false }; store.set(PICK_KEY, JSON.stringify(pick)); }
    if (!r.items.includes(found)) avoidUser = true;
    render();
    const row = [...document.querySelectorAll("#list .row, #avoid .row")].find((d) => d.dataset.slug === sl);
    if (!row) return;
    row.open = true;
    window.scrollTo({ top: Math.max(0, row.getBoundingClientRect().top + window.scrollY - topEl.offsetHeight - 12) });
  }

  // ---------- favourites in a link: back them up, or move them to another phone ----------
  // The link holds the saved keys (restaurant|section|name, or city:<id>|place) as base64url JSON after #favs=
  const toB64url = (str) => btoa(unescape(encodeURIComponent(str))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const fromB64url = (code) => decodeURIComponent(escape(atob(code.replace(/-/g, "+").replace(/_/g, "/"))));
  // The link carries the notes too (v2, "n"), so a backup or a move to another phone keeps them. A link from an
  // older release has none, and an older release ignores them.
  const favsLink = () => appUrl() + "#favs=" + toB64url(JSON.stringify({ v: 2, f: [...favs].sort(), n: Object.fromEntries(Object.entries(notes).slice(0, 200)) }));
  function readFavsCode(code) {
    try {
      const d = JSON.parse(fromB64url(code));
      const keyOk = (k) => typeof k === "string" && k.length > 2 && k.length <= 300 && k.includes("|");
      const keys = (Array.isArray(d && d.f) ? d.f : []).filter(keyOk).slice(0, 500);
      const got = {};
      Object.entries(d && d.n && typeof d.n === "object" ? d.n : {}).slice(0, 200).forEach(([k, t]) => { if (keyOk(k) && typeof t === "string" && t.trim()) got[k] = t.slice(0, NOTE_MAX); });
      return { keys, notes: got };
    } catch (e) { return null; }
  }
  // does a favourite key still name something in the app (for a note that isn't on a favourite): an item with no
  // gluten ingredients or a listed place, never an Avoid row, so a link can't plant a note under something to avoid
  function keyExists(k) {
    const [head, ...rest] = k.split("|");
    if (head.startsWith("city:")) { const c = cities[head.slice(5)]; return !!c && c.places.some((p) => p.name === rest.join("|")); }
    const r = byId(head);
    const [section, ...nm] = rest;
    const name = nm.join("|");
    return !!r && r.items.some((x) => x.section === section && x.name === name);
  }
  // Sort a link's favourites against this phone and the menus as they are now. A dish whose section was renamed
  // follows its name (as saved favourites do); one now on the Avoid list, or gone, isn't added.
  function sortFavs(keys) {
    const add = new Map(), have = [], skip = [];
    for (const k of keys) {
      const [head, ...restParts] = k.split("|");
      if (head.startsWith("city:")) {
        const name = restParts.join("|"), c = cities[head.slice(5)];
        const label = name + (c ? " (" + c.name + ")" : "");
        if (favs.has(k)) have.push(label);
        else if (!c) skip.push({ label, why: "isn't in this app" });
        else if (!c.places.some((pl) => pl.name === name)) skip.push({ label, why: "is no longer on the list" });
        else add.set(k, label);
        continue;
      }
      const [section, ...nameParts] = restParts;
      const name = nameParts.join("|"), r = byId(head);
      if (!r) { skip.push({ label: name, why: "is from a restaurant not in this app" }); continue; }
      let i = r.items.find((x) => x.section === section && x.name === name);
      if (!i) { const same = r.items.filter((x) => norm(x.name) === norm(name)); if (same.length === 1) i = same[0]; }
      const label = (i ? i.name : name) + " at " + r.name;
      if (i) { if (favs.has(favKey(r, i))) have.push(label); else add.set(favKey(r, i), label); continue; }
      const a = r.avoid.find((x) => x.section === section && x.name === name) || r.avoid.find((x) => norm(x.name) === norm(name));
      skip.push({ label, why: a ? "is now on the Avoid list" : "is no longer in the guide" });
    }
    return { add, have, skip };
  }
  let importCode = "";
  let importReady = { data: false, cities: false };
  let importing = null;
  function maybeImport() {
    if (!importCode || !importReady.data || !importReady.cities || !data) return;
    const got = readFavsCode(importCode);
    importCode = "";
    if (!got) { toast("That favourites link is damaged. Ask for it to be sent again."); return; }
    importing = sortFavs(got.keys);
    // notes come along for anything still in the app, without replacing a note this phone already has
    importing.notes = Object.fromEntries(Object.entries(got.notes).filter(([k]) => !noteOf(k) && (importing.add.has(k) || favs.has(k) || keyExists(k))));
    // notes left out, and said so: ones this phone already has (kept as they are), and ones on something now on the
    // Avoid list or gone from the app
    const notesKept = Object.keys(got.notes).filter((k) => noteOf(k)).length;
    const notesLeft = Object.keys(got.notes).filter((k) => !noteOf(k) && !importing.notes[k]).length;
    const { add, have, skip } = importing;
    const nNotes = Object.keys(importing.notes).length;
    const li = (t) => "<li>" + esc(t) + "</li>";
    // the notes are shown in full before anything is added: a note from someone else's link shouldn't read as yours unseen
    const noteLabel = (k) => add.get(k) || (k.startsWith("city:") ? k.split("|").slice(1).join("|")
      : k.split("|").slice(2).join("|") + " at " + ((byId(k.split("|")[0]) || {}).name || k.split("|")[0]));
    $("favImportBody").innerHTML =
      (add.size ? "<h3>To add (" + add.size + ")</h3><ul class=\"chg-list\">" + [...add.values()].map(li).join("") + "</ul>" : '<p class="muted">Nothing new to add.</p>') +
      (have.length ? '<p class="muted">' + have.length + (have.length === 1 ? " is" : " are") + " already saved on this phone.</p>" : "") +
      (nNotes ? "<h3>Notes in the link (" + nNotes + ")</h3><ul class=\"chg-list\">" + Object.entries(importing.notes).map(([k, t]) =>
        "<li><b>" + esc(noteLabel(k)) + ":</b> " + esc(t) + "</li>").join("") + "</ul>" : "") +
      (notesKept ? '<p class="muted">' + notesKept + (notesKept === 1 ? " note stays as it is" : " notes stay as they are") + " on this phone, which already has one there.</p>" : "") +
      (notesLeft ? '<p class="muted">' + notesLeft + (notesLeft === 1 ? " note isn't" : " notes aren't") + " added: on something now on the Avoid list, or gone from the app.</p>" : "") +
      (skip.length ? "<h3>Not added (" + skip.length + ")</h3><ul class=\"chg-list\">" + skip.map((x) => li(x.label + " " + x.why + ".")).join("") + "</ul>" : "");
    $("favImportAdd").hidden = !add.size && !nNotes;
    $("favImportAdd").textContent = add.size === 1 ? "Add this to this phone" : add.size ? "Add these " + add.size + " to this phone" : "Add the notes to this phone";
    ["picker", "info"].forEach((id) => { if ($(id).open) $(id).close(); });
    openDialog($("favImport"));
  }
  $("favImportAdd").addEventListener("click", () => {
    if (!importing) return;
    const n = importing.add.size;
    importing.add.forEach((_, k) => favs.add(k));
    saveFavs();
    const nNotes = Object.keys(importing.notes || {}).length;
    Object.entries(importing.notes || {}).forEach(([k, t]) => setNote(k, t));
    importing = null;
    $("favImport").close();
    if (region === UK) filter = { kind: "fav" }; else cityFilter = "fav";
    render();
    toast((n === 1 ? "Added 1 favourite" : n ? "Added " + n + " favourites" : "Added") + (nNotes ? " and " + nNotes + (nNotes === 1 ? " note" : " notes") : ""));
  });
  $("favImport").addEventListener("close", () => { importing = null; });
  function shareFavs() {
    if (!favs.size) { toast("No favourites to share yet. Open an item and tap ☆ Save."); return; }
    shareLink("My favourites in Twoo's Treat Temple", "My " + favs.size + (favs.size === 1 ? " favourite" : " favourites") + " in Twoo's Treat Temple. Open the link to add them.", favsLink());
  }
  const favShareBar = () => favs.size ? '<p class="fav-share"><button type="button" class="link-btn" data-sharefavs>Share my favourites (' + favs.size + ") &rsaquo;</button></p>" : "";

  // ---------- new app code without a restart ----------
  // When the app comes back to the screen it asks for a new service worker. A new release takes over at once (sw.js skips
  // waiting), and then the page reloads by itself if nothing is open, or offers to.
  const idle = () => !document.querySelector("dialog[open]") && !document.querySelector("details.row[open]") && !$("q").value.trim();
  function reloadNow() {
    try { sessionStorage.setItem("gf-scroll", String(window.scrollY)); } catch (e) { /* not kept */ }
    location.reload();
  }
  function updateReady() {
    if (idle()) reloadNow(); else $("updateBar").hidden = false;
  }
  function checkForUpdate() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.getRegistration().then((reg) => reg && reg.update()).catch(() => { /* offline */ });
  }
  $("updateBar").addEventListener("click", reloadNow);

  // ---------- toast ----------
  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3400);
  }

  // ---------- loading ----------
  async function getJSON(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(url + " " + res.status);
    return { json: await res.json(), offline: res.headers.get("X-GF-Offline") === "1" };
  }

  // what the menus say, as one short string: each restaurant's fingerprint from the build (menus saved by an older
  // release carry none, so they're compared in full once)
  const menusOf = (d) => (d.restaurants.every((r) => r.hash) ? d.restaurants.map((r) => r.id + ":" + r.hash).join(",")
    : JSON.stringify(d.restaurants.map(({ built, ...r }) => r)));
  async function load(manual) {
    if (manual) checkForUpdate();
    const btn = $("refreshBtn");
    btn.disabled = true;
    btn.textContent = "Checking…";
    try {
      const idx = await getJSON("data/restaurants.json");
      const full = await Promise.all(idx.json.restaurants.map((r) => getJSON(r.file)));
      const offline = idx.offline || full.some((f) => f.offline);
      if (!offline) { store.set(CHECKED_KEY, new Date().toISOString()); renderLastChecked(); }
      const fresh = { built: idx.json.built, restaurants: full.map((f) => f.json) };
      const prev = data;
      // every release rebuilds the menus, so compare what they say, not when they were built
      const changed = !prev || menusOf(prev) !== menusOf(fresh);
      const wasOffline = offlineNow;
      offlineNow = offline;
      if (changed) {
        if (!prev && firstVisit && !store.get(SEEN_KEY)) store.set(SEEN_KEY, JSON.stringify(fresh.restaurants.map((r) => r.id + "@" + r.source)));
        setLooked(fresh.restaurants, true); // a restaurant new to this phone starts from what it shows now
        noteNewRestaurants(fresh.restaurants); // and is marked New until it's opened
      }
      if (!prev || prev.built !== fresh.built) {
        data = fresh;
        store.set(DATA_KEY, JSON.stringify(fresh));
      }
      if (changed || wasOffline !== offlineNow) render();
      if (offline) {
        if (manual) toast("No connection. Showing the menus saved on this phone.");
      } else if (prev) {
        const news = fresh.restaurants.filter((r) => {
          const old = prev.restaurants.find((o) => o.id === r.id);
          return !old || old.source !== r.source;
        });
        if (news.length) toast("New guides: " + news.map((r) => r.name).join(", "));
        else if (changed) toast("Menus updated"); // the saved menus showed first; these newer ones replace them
        else if (manual) toast("You have the latest menus");
      }
    } catch (e) {
      if (data) {
        if (!offlineNow) { offlineNow = true; render(); }
        if (manual) toast("No connection. Showing the menus saved on this phone.");
      } else {
        $("guideLine").textContent = "Couldn't load menus";
        $("list").innerHTML = '<p class="empty">Couldn\'t load the menus. Check your connection, then open the app again.</p>';
      }
    } finally {
      btn.disabled = false;
      btn.textContent = "Check for new menus";
    }
  }
  // When the app last reached the menus, shown in Help beside "Check for new menus"
  const CHECKED_KEY = "gf-last-checked";
  function renderLastChecked() {
    const iso = store.get(CHECKED_KEY);
    const d = iso ? new Date(iso) : null;
    const sameDay = d && d.toDateString() === new Date().toDateString();
    $("lastChecked").textContent = !d || isNaN(d) ? "Not checked yet."
      : "Last checked " + (sameDay ? "today at " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + ".") + (offlineNow ? " You're offline, so these are the menus saved on this phone." : "");
  }

  // ---------- events ----------
  // While searching, tips and notes step aside so results sit just under the search box, above the keyboard
  const syncSearching = () => document.body.classList.toggle("searching", !!$("q").value.trim() || (region !== UK && (cityFilter !== "all" || nearSort)));
  $("q").addEventListener("input", () => {
    avoidUser = null;
    syncSearching();
    window.scrollTo({ top: 0 });
    if (region !== UK) renderCityList();
    else if (data) { renderStatus(); renderList(); }
  });
  $("chips").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-kind]");
    if (!b) return; // Open near me, Near me, the card and the order chip have listeners of their own
    const { kind, value } = b.dataset;
    if (region !== UK) {
      cityFilter = kind === "section" ? value : kind;
      renderCity();
      window.scrollTo({ top: 0 });
      return;
    }
    if (!data) return;
    if (kind === "restaurant") { select(value); return; }
    filter = value ? { kind, value } : { kind };
    renderChips();
    renderStatus();
    renderList();
    window.scrollTo({ top: 0 });
  });
  function goElsewhere(to) {
    const q = $("q").value;
    if (to === UK) { selected = ALL; setRegion(UK); } else if (to === ALL) select(ALL); else setRegion(to);
    $("q").value = q;
    syncSearching();
    if (region !== UK) renderCityList(); else { renderStatus(); renderList(); }
    window.scrollTo({ top: 0 });
  }
  // The buttons that can sit anywhere on the page (in lists, sheets and notes), one listener for all of them: each
  // data attribute names what its button does, and the attribute's value is what it does it to.
  const ACTIONS = {
    nearopen: () => toggleNearOpen(),
    near: () => toggleNear(),
    card: () => openCard(city().language),
    orderOpen: () => openOrder(byId(selected)),
    order: (key, b, e) => { e.preventDefault(); toggleOrderButton(key); },
    whatchanged: (rid) => openChanges(byId(rid)),
    addmenu: () => openAddMenu(),
    map: () => { mapOn = !mapOn; renderCity(); },
    placeOpen: (name) => openPlaceRow(name),
    nearUk: () => nearMe(),
    nearAuto: (v) => setNearAuto(v === "on", false),
    gonear: (rid) => { $("near").close(); select(rid); },
    chain: (rid) => select(rid), // a UK city's chain row: its menu, under Chains
    mapMenu: (rid) => leaveMap(() => select(rid)),
    mapPlace: (name, b) => leaveMap(() => { setRegion(b.dataset.city); openPlaceRow(name); }), // the whole list, so the row is there
    say: (n) => { const p = phrases[cardLang]; if (p && p.card[n]) say(p.card[n].text, cardLang); },
    gotorestReq: (rid) => { $("upload").close(); select(rid); },
    elsewhere: (to) => goElsewhere(to),
    sharefavs: () => shareFavs(),
    shareItem: (ref) => { const { r, i } = itemByRef(ref); if (i) shareLink("Twoo's Treat Temple", i.name + " at " + r.name, itemUrl(r, i)); },
    wrong: (ref) => { const { r, i } = itemByRef(ref); if (i) reportItem(r, i); },
    wrongPlace: (name) => { const p = city() && city().places.find((x) => x.name === name); if (p) reportPlace(p); },
  };
  const attrOf = (name) => "data-" + name.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
  document.addEventListener("click", (e) => {
    for (const [name, act] of Object.entries(ACTIONS)) {
      const b = e.target.closest("[" + attrOf(name) + "]");
      if (b) { act(b.dataset[name], b, e); return; }
    }
  });
  $("list").addEventListener("click", onFav);
  $("cityList").addEventListener("click", onFav);
  function onFav(e) {
    const b = e.target.closest(".fav-btn");
    if (!b) return;
    e.preventDefault();
    const k = b.dataset.fav;
    if (favs.has(k)) favs.delete(k); else favs.add(k);
    saveFavs();
    const on = favs.has(k);
    document.querySelectorAll("#list .fav-btn, #cityList .fav-btn").forEach((btn) => {
      if (btn.dataset.fav !== k) return;
      btn.setAttribute("aria-pressed", on);
      btn.textContent = on ? "★ Saved" : "☆ Save";
      const nm = btn.closest(".row").querySelector(".nm");
      const star = nm.querySelector(".star");
      if (on && !star) nm.insertAdjacentHTML("afterbegin", '<span class="star" aria-label="Favourite">★</span>');
      if (!on && star) star.remove();
    });
    toast(on ? "Saved to favourites" : "Removed from favourites");
  }
  function openDialog(d) { if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", ""); }
  $("pickBtn").addEventListener("click", () => { if (!data) return; renderPicker(); openDialog($("picker")); });
  $("pickList").addEventListener("click", (e) => {
    const b = e.target.closest(".pick-opt");
    if (!b) return;
    e.preventDefault();
    $("picker").close();
    if (b.dataset.region) setRegion(b.dataset.region);
    else select(b.dataset.r);
  });
  $("picker").addEventListener("close", () => { welcomeNow = false; });
  $("appVersion").textContent = "App version " + APP_VERSION + ".";
  // ---------- What's new: each announced release's own notes (whatsnew.json), from Help or the notification ----------
  async function openWhatsNew() {
    $("whatsNewBody").innerHTML = '<p class="empty">Loading…</p>';
    if (!$("whatsNew").open) openDialog($("whatsNew"));
    let notes = null;
    try { const res = await fetch("whatsnew.json", { cache: "no-cache" }); if (res.ok) notes = await res.json(); } catch (e) { /* no signal, never saved */ }
    notes = Array.isArray(notes) ? notes.filter((n) => n && Number.isFinite(n.version) && n.title && Array.isArray(n.items)) : [];
    $("whatsNewBody").innerHTML = notes.length
      ? notes.slice(0, 6).map((n) => "<h3>" + esc(n.title) + '</h3><p class="muted">Update ' + n.version + (n.date ? ", " + esc(fmtDate(n.date)) : "") +
          (n.version === APP_VERSION ? " (this one)" : n.version > APP_VERSION ? " (on its way: close the app and open it again)" : "") + "</p>" +
          '<ul class="news-items">' + n.items.map((i) => "<li>" + esc(i) + "</li>").join("") + "</ul>").join("")
      : '<p class="empty">Couldn\'t load the notes. Try again with signal.</p>';
  }
  $("whatsNewBtn").addEventListener("click", openWhatsNew);
  // what to send the owner if something breaks: no tracking, nothing leaves the phone unless you send it
  function errorDetails() {
    const lines = ["Twoo's Treat Temple, app version " + APP_VERSION, "Menus built: " + (data ? data.built : "not loaded"),
      "Phone: " + navigator.userAgent, "Time: " + new Date().toISOString(), "",
      errors.length ? "Last " + errors.length + (errors.length === 1 ? " error:" : " errors:") : "No errors recorded."];
    errors.forEach((x) => lines.push(x.at + " (v" + x.v + ") " + x.msg + (x.where ? " [" + x.where + "]" : "")));
    return lines.join("\n");
  }
  function renderErrors() {
    $("errorCount").textContent = errors.length ? errors.length + (errors.length === 1 ? " error" : " errors") + " recorded on this phone." : "No errors recorded on this phone.";
  }
  renderErrors();
  $("copyDetails").addEventListener("click", async () => {
    const text = errorDetails();
    try { await navigator.clipboard.writeText(text); toast("Details copied. Paste them into a message to the owner."); }
    catch (e) {
      if (navigator.share) { try { await navigator.share({ title: "Treat Temple details", text }); } catch (err) { /* share sheet closed */ } }
      else toast("Couldn't copy them.");
    }
  });
  $("infoBtn").addEventListener("click", () => { renderLastChecked(); openDialog($("info")); });
  ["picker", "info", "gfcard", "warnings", "staff", "changes", "report", "favImport", "order", "near", "mapPage", "whatsNew"].forEach((id) => $(id).addEventListener("click", (e) => { if (e.target === $(id)) $(id).close(); }));
  ["staff", "gfcard"].forEach((id) => $(id).addEventListener("close", () => { if (!$("staff").open && !$("gfcard").open) letGo(); }));
  $("refreshBtn").addEventListener("click", () => load(true));
  $("shareBtn").addEventListener("click", () => {
    const r = region === UK && byId(selected);
    const c = city();
    const url = appUrl() + (c ? "#" + region : r ? "#" + r.id : "");
    const text = c ? "Places in " + c.name + " for coeliacs, " + (isUKCity(c) ? "found through coeliac guides and listings" : "from the coeliac support groups' list")
      : r ? "Food and drinks with no gluten ingredients at " + r.name : "Food and drinks with no gluten ingredients at restaurants and coffee shops";
    shareLink("Twoo's Treat Temple", text, url);
  });
  const hashText = () => { try { return decodeURIComponent(location.hash.slice(1)); } catch (e) { return ""; } };
  window.addEventListener("hashchange", () => {
    const raw = hashText();
    if (raw.startsWith("favs=")) { importCode = raw.slice(5); history.replaceState(null, "", location.pathname); maybeImport(); return; }
    if (raw.startsWith("request=")) { history.replaceState(null, "", location.pathname); openRequestFrom(raw.slice(8)); return; }
    const [id, item] = raw.split("/");
    if (cities[id]) { if (id !== region) setRegion(id); }
    else if (data && id && byId(id)) { if (item) showItem(id, item); else if (id !== selected || region !== UK) select(id); }
  });

  // Reserve space for the floating header at its full (expanded) height.
  const topEl = document.querySelector(".top");
  const reserve = () => { if (!topEl.classList.contains("collapsed")) document.body.style.setProperty("--top-h", topEl.offsetHeight + "px"); };
  if (window.ResizeObserver) new ResizeObserver(reserve).observe(topEl);
  reserve();
  // Hide the filter rows while scrolling down the list; bring them back on scrolling up.
  let lastY = window.scrollY;
  let ticking = false;
  window.addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const y = window.scrollY;
      if (y > 160 && y > lastY + 6) topEl.classList.add("collapsed");
      else if (y < lastY - 6 || y < 160) topEl.classList.remove("collapsed");
      lastY = y;
      ticking = false;
    });
  }, { passive: true });

  // install tip: iPhone/iPad in Safari, not yet on the Home Screen
  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
  if (isIOS && !standalone && store.get(TIP_KEY) !== "1") $("installTip").hidden = false;
  $("installHelp").hidden = standalone;
  $("installClose").addEventListener("click", () => { $("installTip").hidden = true; store.set(TIP_KEY, "1"); });

  // ---------- notifications about new menus (Home Screen app only) ----------
  // The phone subscribes with the public half of the app's push key; the private half is a GitHub secret, and
  // tools/push.py sends one notification after a publish that brought a new guide. There's no server, so the phone's
  // subscription (its notification address) is sent to the owner, who saves it by hand as the PUSH_SUBSCRIPTIONS secret.
  const PUSH_KEY = "BL9p-_E-Ln3CxCioOhIz0WHw9AfDbdNGMfnPuQpZTZiztpvgMxtuS8JBPJSGs5f4qmxAmEUy0pmOIXihW9ncHdk";
  const PUSH_SAVED = "gf-push"; // the subscription this phone last showed, so a replacement by the phone is noticed
  const canPush = () => standalone && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const b64ToBytes = (s) => { const b = atob(s.replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(b, (c) => c.charCodeAt(0)); };
  async function pushState() {
    if (!canPush()) { $("pushHelp").hidden = true; return; }
    $("pushHelp").hidden = false;
    const el = $("pushState");
    if (Notification.permission === "denied") {
      el.textContent = "Switched off for this app under Settings, Notifications.";
      $("pushOn").hidden = true;
      $("pushBox").hidden = true;
      return;
    }
    let sub = null;
    try { sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription(); } catch (e) { /* none */ }
    const was = store.get(PUSH_SAVED);
    $("pushOn").hidden = !!sub;
    $("pushBox").hidden = !sub;
    if (sub) {
      const now = JSON.stringify(sub.toJSON());
      $("pushSub").value = now;
      el.textContent = was && was !== now ? "This phone's address has changed, so send it again." : "On, once the owner has this phone's address.";
    } else el.textContent = was ? "Switched off, or the phone let it go. Tap to switch it on again, then send the new address." : "";
  }
  $("pushOn").addEventListener("click", async () => {
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { toast("Notifications weren't allowed"); pushState(); return; }
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(PUSH_KEY) });
      store.set(PUSH_SAVED, JSON.stringify(sub.toJSON()));
      await pushState();
      toast("Now send the address to the app's owner");
    } catch (e) { logError(e.message, "push"); toast("Couldn't switch notifications on: " + e.message); }
  });
  $("pushSend").addEventListener("click", () => shareOrCopy("Treat Temple notifications",
    "My phone's notification address for Twoo's Treat Temple (add it as a line of the PUSH_SUBSCRIPTIONS secret):\n" + $("pushSub").value, "", "Copied. Paste it into a message to the owner."));
  $("pushOff").addEventListener("click", async () => {
    try { const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription(); if (sub) await sub.unsubscribe(); } catch (e) { /* nothing to undo */ }
    store.remove(PUSH_SAVED);
    pushState();
    toast("Notifications off. Tell the owner to remove this phone's address.");
  });
  pushState();
  // the icon's badge counts guides not yet looked at; opening the app clears it
  if (navigator.clearAppBadge) {
    const clearBadge = () => navigator.clearAppBadge().catch(() => { /* no badge */ });
    clearBadge();
    document.addEventListener("visibilitychange", () => { if (!document.hidden) clearBadge(); });
  }

  // Ask the phone not to clear this site's storage under space pressure, and say in Help whether that worked.
  async function setUpStorage() {
    const el = $("storageState");
    if (!(navigator.storage && navigator.storage.persist && navigator.storage.persisted)) { el.hidden = true; return; }
    try {
      if (standalone) await navigator.storage.persist();
      const persisted = await navigator.storage.persisted();
      el.hidden = false;
      el.textContent = persisted ? "Saved on this phone." : "May be cleared if the phone is short of space.";
    } catch (e) { el.hidden = true; }
  }
  setUpStorage();

  // ---------- start ----------
  const rawHash = hashText();
  importCode = rawHash.startsWith("favs=") ? rawHash.slice(5) : "";
  const requestCode = rawHash.startsWith("request=") ? rawHash.slice(8) : "";
  if (importCode || requestCode) history.replaceState(null, "", location.pathname); // added or not, a reload shouldn't ask again
  const hashId = importCode || requestCode ? "" : rawHash;
  // "?whatsnew": the "Update N is live!" notification (a query, not a #, which the last release would read as a page)
  const wantNews = /(^|[?&])whatsnew(=|&|$)/.test(location.search.slice(1));
  if (wantNews) history.replaceState(null, "", location.pathname + location.hash); // a reload shouldn't open it again
  const [hashRid, hashItem] = hashId.split("/");
  const saved = store.get(DATA_KEY);
  if (saved) {
    try { data = JSON.parse(saved); } catch (e) { data = null; }
  }
  if (data) { setLooked(data.restaurants, true); noteNewRestaurants(data.restaurants); } // the menus saved on this phone are the ones you last saw
  // a link to a restaurant opens the UK menus; any other link (#berlin) is taken as a city until cities.json says otherwise
  if (hashRid) region = data && byId(hashRid) ? UK : hashRid;
  selected = (region === UK && hashRid) || store.get(SEL_KEY) || ALL;
  render();
  if (requestCode) openRequestFrom(requestCode); // a place asked for on another phone, passed on by link
  if (wantNews) openWhatsNew();
  let itemPending = hashItem || "";
  if (itemPending && data && byId(hashRid)) { showItem(hashRid, itemPending); itemPending = ""; }
  try { // back where you were after the app reloaded itself for new code
    const y = sessionStorage.getItem("gf-scroll");
    if (y !== null) { sessionStorage.removeItem("gf-scroll"); window.scrollTo(0, +y); }
  } catch (e) { /* not kept */ }
  const fromFavLink = !!importCode;
  loadPhrases();
  loadCities();
  load(false).then(() => {
    // first visit: one restaurant opens directly; several, the picker opens so you start somewhere specific
    if (data && region === UK && hashRid && byId(hashRid)) { store.set(SEL_KEY, hashRid); store.set(LAST_KEY, hashRid); }
    if (data && itemPending && byId(hashRid)) { showItem(hashRid, itemPending); itemPending = ""; }
    importReady.data = true;
    maybeImport();
    if (data && region === UK && !hashId && !fromFavLink && !requestCode && !wantNews && !store.get(SEL_KEY)) { // not over a request link's form or What's new
      if (data.restaurants.length === 1) select(data.restaurants[0].id);
      else { renderPicker(); openDialog($("picker")); }
    }
    autoNear(false); // the look around, if it's been switched on
    if (data && osmChains().length) loadBranches(); // quietly, so the map and Near me have it without signal later
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if ($("staff").open || $("gfcard").open) keepAwake();
    checkForUpdate();
    load(false).then(() => autoNear(false));
    renderTzOffer();
    if (city()) renderCityList(); // open or closed may have changed while the app was in the background
  });
  // Every minute, bring each place's "Open now / Closed now" up to date without closing the one you're reading
  setInterval(() => {
    const c = city();
    if (!c || document.visibilityState !== "visible") return;
    if (cityFilter === "open" && !document.querySelector("#cityList details[open]")) { renderCityList(); return; }
    const now = cityNow(c);
    document.querySelectorAll("#cityList details[data-place]").forEach((d) => {
      const p = c.places.find((x) => x.name === d.dataset.place);
      const el = d.querySelector(".today");
      const t = p && todayLine(p, now);
      if (el && t) { el.textContent = t; el.classList.toggle("shut", /^(Closed|Kitchen closed)/.test(t)); }
    });
  }, 60000);
  if ("serviceWorker" in navigator) {
    // The first service worker taking charge isn't an update; any later change of worker is a new release
    let hadWorker = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!hadWorker) { hadWorker = true; return; }
      updateReady();
    });
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
})();
