(() => {
  "use strict";
  // The release. tools/check.py holds it equal to the service worker's cache number (site/sw.js), and the pull request
  // check makes sure it goes up whenever the app's code changes, so phones notice the new code.
  const APP_VERSION = 26;
  document.documentElement.dataset.version = APP_VERSION;
  const DATA_KEY = "gf-data-v2";
  const SEL_KEY = "gf-selected";
  const FAV_KEY = "gf-favourites";
  const TIP_KEY = "gf-install-tip-dismissed";
  const SEEN_KEY = "gf-changes-seen"; // "<id>@<source>" for each "what's new" banner dismissed
  const REGION_KEY = "gf-region";
  const ALL = "all";
  const UK = "uk"; // the restaurant menus; any other region is a city in cities.json
  const INTL = "intl"; // the header switch's other side: the city last looked at
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
  function listOr(arr) {
    return arr.length < 2 ? arr.join("") : arr.slice(0, -1).join(", ") + " or " + arr[arr.length - 1];
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
  const logoHtml = (name, src, cls) => '<span class="logo-wrap' + (src ? "" : " none") + (cls ? " " + cls : "") + '" aria-hidden="true">' +
    (src ? '<img class="logo" src="' + esc(src) + '" alt="">' : "") +
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

  // How the app decided an item where the guide wasn't plain (the readers' notes, in plain English)
  const decidedNote = (i) => '<div class="decided"><b>How the app decided:</b> ' + esc(i.decided) + "</div>";
  // "Share this item" (a link that opens straight to it) and "Something wrong?" (a ready message to send)
  const moreLinks = (r, i) => '<div class="detail-more"><button type="button" class="link-btn" data-share-item="' + esc(itemRef(r, i)) +
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
    out.push('<div class="detail-foot"><span>' + esc(pageText(i.pages)) + '</span><span class="foot-btns">' +
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
    return '<details class="row" data-slug="' + esc(itemSlug(r, i)) + '"><summary><span class="nm">' + star + esc(i.name) + sub + '<span class="tag ' + cls + '">' +
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
      $("guideLine").textContent = n + (n === 1 ? " restaurant" : " restaurants") + (offlineNow ? "" : " · tap to choose") + offlineTag();
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
    $("chips").innerHTML = chips.map((c) => chipHtml(c.kind, c.value, c.label, sameFilter(c, filter)) +
      (c.kind === "fav" && r ? '<button type="button" data-order-open>' + orderChipText(r) + "</button>" : "")).join("");
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
      ". Check in store before ordering" + (r.officialUrl ? ', or see <a href="' + esc(r.officialUrl) + '" target="_blank" rel="noopener">their allergen info</a>' : "") + "." +
      (r.latestGuide ? " " + esc(r.latestGuide.note) + " (checked " + esc(fmtDate(r.latestGuide.checked)) + ")" : "") + "</p>").join("");
    renderFavAlerts();
    renderNews();
    renderCertNote();
    renderCardLaunch();
    const r = byId(selected);
    const tips = (r && r.tips) || [];
    const full = introFull();
    $("tips").hidden = !full || !tips.length;
    $("tips").innerHTML = tipsHtml(tips);
    $("certNote").hidden = !full;
    $("openStrip").hidden = full;
    $("stripText").innerHTML = (r && r.headline ? "<b>" + esc(r.headline) + "</b> " : "") + esc(certShort(scope()));
    $("stripLabel").textContent = tips.length ? "Tips and warnings" : "Warnings";
  }
  const tipsHtml = (tips) => tips.map((t) => {
    const m = t.match(/^([^:.]+[:.])\s+(.+)$/);
    return "<div>" + (m ? "<b>" + esc(m[1]) + "</b> " + esc(m[2]) : esc(t)) + "</div>";
  }).join("");

  // The first time each page (a restaurant, or All) is opened, its tips and the certified-or-not card show in full.
  // After that they fold into one line (#strip), with every word of them in the Tips and warnings sheet.
  const INTRO_KEY = "gf-intro-seen";
  const introNow = new Set(); // shown in full during this visit, so the card doesn't fold away while it's being read
  function introFull() {
    if (introNow.has(selected)) return true;
    const seen = new Set(JSON.parse(store.get(INTRO_KEY) || "[]"));
    if (seen.has(selected)) return false;
    seen.add(selected);
    store.set(INTRO_KEY, JSON.stringify([...seen]));
    introNow.add(selected);
    return true;
  }
  $("introDone").addEventListener("click", () => { introNow.delete(selected); renderBanners(); });
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
    if (moved) store.set(FAV_KEY, JSON.stringify([...favs]));
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
    if (un) { favs.delete(un.dataset.unfav); store.set(FAV_KEY, JSON.stringify([...favs])); render(); return; }
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
  function renderNews() {
    const s = seen();
    const news = scope().map((r) => [r, newsFor(r, s)]).filter(([, c]) => c);
    $("news").hidden = !news.length;
    $("news").innerHTML = news.map(([r, c]) => '<div class="news-row' + (c.nowAvoid.length ? " bad" : "") + '"><p><b>' + esc(r.name) +
      (skipped(r, c) ? " has new guides.</b> Since the " + esc(c.since) + " guide you last looked at: " : " has a new guide.</b> Since " + esc(c.since) + ": ") +
      esc(counts(c).join(", ")) + '.</p><p class="news-btns">' +
      '<button type="button" class="pill-btn" data-news="' + esc(r.id) + '">See what changed</button>' +
      '<button type="button" class="link-btn" data-seen="' + esc(r.id) + '">Dismiss</button></p></div>').join("");
  }
  $("news").addEventListener("click", (e) => {
    const open = e.target.closest("[data-news]");
    if (open) { openChanges(byId(open.dataset.news)); return; }
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
      out += btn(UK, n, n === 1 ? "match on the UK menus" : "matches on the UK menus");
    }
    return out;
  }
  const addMenuLink = '<button type="button" class="link-btn" data-addmenu>A place not here? Send its menu &rsaquo;</button>';
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
            "<div>" + esc(pageText(a.pages)) + "</div>" + moreLinks(r, a) + "</div></details>";
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
    // dot and count on one line, the label under them, so the three buttons are one even row
    const b = (k, cls, label) => '<button type="button" data-k="' + k + '" aria-pressed="' + pick[k] + '"><span class="dot ' + cls + '"></span>' +
      '<span class="lbl">' + label + '</span> <span class="cnt">' + n[k] + "</span></button>";
    $("status").classList.toggle("picking", picking());
    $("status").innerHTML =b("straight", "d-ok", "No gluten ingredients") + b("change", "d-swap", "Needs a change") + b("gluten", "d-bad", "Avoid");
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
    const lineShort = (r) => "<p><b>" + esc(r.name) + ":</b> " + esc(r.covers ? r.covers + ". " : "") + "From " + esc(plainGuideName(r)) + ". " +
      esc(r.stats.items) + " with no gluten ingredients, " + esc(r.stats.avoid) + " to avoid." +
      (r.officialUrl ? ' <a href="' + esc(r.officialUrl) + '" target="_blank" rel="noopener">Official site</a>' : "") + "</p>";
    // "Menus in this app" (Help) keeps the raw file name, for the record
    const lineFull = (r) => {
      const g = r.guide || {};
      return "<p><b>" + esc(r.name) + ":</b> " + esc(r.covers ? r.covers + ". " : "") + "From " + esc(r.source) +
        (g.version ? " (version " + esc(fmtDate(g.version)) + ")" : "") + ". " + esc(r.stats.items) + " with no gluten ingredients, " + esc(r.stats.avoid) +
        " to avoid." + (r.officialUrl ? ' <a href="' + esc(r.officialUrl) + '" target="_blank" rel="noopener">Official site</a>' : "") + whatChanged(r) + "</p>";
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
  function renderPicker() {
    const last = store.get(LAST_KEY);
    // first run: say what the app is, and put the other countries next to All restaurants so they're on the first screen without scrolling
    if (!welcomeNow && !store.get(SEL_KEY) && !store.get(WELCOME_KEY)) { welcomeNow = true; store.set(WELCOME_KEY, "1"); }
    $("pickWelcome").hidden = !welcomeNow;
    const opt = (id, name, line, meta, stale, logo) =>
      '<button type="button" class="pick-opt" data-r="' + esc(id) + '" aria-pressed="' + (region === UK && selected === id) + '">' + logo + '<span class="po-main"><b>' +
      esc(name) + "</b><span>" + esc(line) + "</span></span>" + (stale ? '<span class="tag t-swap">Out of date</span>' : '<span class="po-meta">' + esc(meta) + "</span>") + "</button>";
    const total = data.restaurants.reduce((n, r) => n + r.stats.items, 0);
    const as = areas();
    const lineOf = (r, withArea) => [r.id === last ? "Last used" : "", r.type, withArea ? r.area : "", guideLine(r)].filter(Boolean).join(" · ");
    const one = (r, withArea) => opt(r.id, r.name, lineOf(r, withArea), r.stats.items + " items", isStale(r), logoHtml(r.name, r.logo));
    const grouped = as.length > 1
      ? as.map((a) => '<div class="sub-h">' + esc(a) + "</div>" + chooserOrder(data.restaurants.filter((r) => r.area === a)).map((r) => one(r, false)).join("")).join("") +
        chooserOrder(data.restaurants.filter((r) => !r.area)).map((r) => opt(r.id, r.name, r.type, r.stats.items + " items", isStale(r), logoHtml(r.name, r.logo))).join("")
      : chooserOrder(data.restaurants).map((r) => one(r, true)).join("");
    // other countries (cities.json) are hand-checked lists of places rather than menus, so they switch region instead of restaurant.
    // They're listed like the restaurants: the country, with its city and what the list holds underneath.
    const intl = Object.entries(cities).map(([cid, c]) =>
      '<button type="button" class="pick-opt" data-region="' + esc(cid) + '" aria-pressed="' + (region === cid) + '">' +
      '<span class="logo-wrap flag" aria-hidden="true">' + esc(c.flag || "") + '</span><span class="po-main"><b>' + esc(c.country || c.name) + "</b><span>" + esc(c.name) +
      ": places that are all gluten free, by their own word or the coeliac society's list" +
      (c.places.some((p) => p.claim === "separate") ? ", or that say they have a separate gluten free kitchen" : "") + "</span></span>" +
      '<span class="po-meta">' + c.places.length + " places</span></button>").join("");
    const intlGroup = intl ? '<div class="sub-h">International</div>' + intl : "";
    const all = opt(ALL, "All restaurants", "Search and browse everything", total + " items", false, logoHtml("All restaurants", "icons/icon-192.png"));
    $("pickList").innerHTML = '<div class="sub-h">' + (welcomeNow ? "Choose where" : "UK") + "</div>" + all +
      (welcomeNow ? intlGroup + '<div class="sub-h">Or one UK restaurant</div>' + grouped : grouped + intlGroup) +
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
    const there = Object.keys(cities).find((id) => zoneOf(cities[id]) === zone);
    const btns = (yes) => '<p class="tz-btns"><button type="button" class="pill-btn" data-tz="yes">' + yes + '</button><button type="button" class="link-btn" data-tz="no">Not now</button></p>';
    if (region === UK && there && asked !== zone) {
      el.innerHTML = "<p><b>You're on " + esc(cities[there].name) + " time.</b> Show " + esc(cities[there].name) + " places?</p>" + btns("Show " + esc(cities[there].name));
      el.dataset.to = there;
    } else if (region !== UK && cities[region] && !there && asked === zoneOf(cities[region])) {
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
    selected = id;
    filter = { kind: "all" };
    region = UK;
    store.set(REGION_KEY, UK);
    store.set(SEL_KEY, id);
    if (id !== ALL) store.set(LAST_KEY, id);
    avoidUser = null;
    history.replaceState(null, "", id === ALL ? location.pathname : "#" + id);
    $("q").value = "";
    render();
    window.scrollTo({ top: 0 });
  }

  // ---------- UK / International switch: a city is a hand-checked list of places (cities.json), not menus ----------
  // International goes to the city last looked at (the chooser picks the country); UK goes back to the menus.
  const LAST_CITY_KEY = "gf-last-city";
  function renderRegion() {
    const inCity = region !== UK;
    $("region").hidden = !Object.keys(cities).length;
    $("region").innerHTML = '<button type="button" data-region="' + UK + '" aria-pressed="' + !inCity + '">UK</button>' +
      '<button type="button" data-region="' + INTL + '" aria-pressed="' + inCity + '">International</button>';
    $("ukView").hidden = inCity;
    $("cityView").hidden = !inCity;
    $("status").hidden = inCity;
  }
  function setRegion(id) {
    if (id === INTL) { const lastCity = store.get(LAST_CITY_KEY); id = cities[lastCity] ? lastCity : Object.keys(cities)[0] || UK; }
    region = id;
    store.set(REGION_KEY, id);
    if (id !== UK) store.set(LAST_CITY_KEY, id);
    $("q").value = "";
    cityFilter = "all";
    history.replaceState(null, "", id !== UK ? "#" + id : selected === ALL ? location.pathname : "#" + selected);
    render();
    window.scrollTo({ top: 0 });
  }
  $("region").addEventListener("click", (e) => {
    const b = e.target.closest("[data-region]");
    if (b && (b.dataset.region === UK) !== (region === UK)) setRegion(b.dataset.region);
  });

  const mapLink = (p, l) => "https://maps.apple.com/?q=" + encodeURIComponent(p.name) + "&address=" + encodeURIComponent(l.address);
  const cityStale = (c) => new Date(c.checked + "T12:00:00Z").getTime() + (c.recheckDays || 90) * 864e5 < Date.now();
  function renderCity() {
    const c = city();
    if (!c) { $("cityList").innerHTML = '<p class="empty">Loading…</p>'; return; }
    store.set(LAST_CITY_KEY, region); // where International goes next time
    syncSearching();
    $("pickName").textContent = c.name;
    $("pickBtn").setAttribute("aria-label", c.name + ". Choose where to eat");
    $("guideLine").textContent = c.places.length + " places · checked " + fmtDate(c.checked) + offlineTag();
    $("q").placeholder = "Search " + c.name;
    const chips = [["all", "All"], ["open", "Still open today"], ["fav", "★ Saved"]].concat(c.sections.filter((s) => c.places.some((p) => p.section === s)).map((s) => [s, s]));
    if (!chips.some(([v]) => v === cityFilter)) cityFilter = "all";
    const card = phrases[c.language];
    $("chips").innerHTML = '<button type="button" data-nearopen aria-pressed="' + (nearSort && cityFilter === "open") + '">Open near me</button>' +
      '<button type="button" data-near aria-pressed="' + nearSort + '">Near me</button>' +
      chips.map(([v, l]) => chipHtml(["all", "open", "fav"].includes(v) ? v : "section", ["all", "open", "fav"].includes(v) ? "" : v, l,
        v === cityFilter && !(v === "all" && nearSort))).join("") +
      (card ? '<button type="button" data-card>' + esc(card.language) + " card</button>" : "");
    const n = (claim) => c.places.filter((p) => p.claim === claim).length;
    $("cityIntroLine").innerHTML = "<b>Tags say who calls a place gluten free</b>, not the app. Tell staff you're coeliac.";
    $("cityIntro").innerHTML = "<b>Each place's tag says who calls it gluten free.</b> " +
      [n("place-all") && n("place-all") + " say so themselves", n("list-all") && n("list-all") + " are listed as all gluten free by the support groups but don't say so on their own websites",
        n("place-part") && n("place-part") + " says only part of its range is", n("separate") && n("separate") + " says it makes gluten free food in a separate kitchen"]
        .filter(Boolean).join("; ") + ". That's their claim, not the app's. They come from the list kept by " + esc(c.list.by) +
      (c.also || []).map((a) => " and " + esc(a.by)).join("") +
      ", checked against each place's own website on " + esc(fmtDate(c.checked)) + ". Nobody from this app has seen their kitchens, so tell staff you have coeliac disease.";
    $("cityStale").hidden = !cityStale(c);
    $("cityStale").innerHTML = cityStale(c) ? "<p><b>This list may be out of date.</b> It was checked on " + esc(fmtDate(c.checked)) +
      ". Places open, close and change, so check before you go.</p>" : "";
    $("cityTipsLabel").textContent = "Before you go (" + c.tips.length + ")";
    $("cityTips").innerHTML = tipsHtml(c.tips);
    const source = (a) => '<a href="' + esc(a.url) + '" target="_blank" rel="noopener" data-quote>' + esc(a.name) + "</a>, kept by " + esc(a.by);
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
  function branchToday(l, day) {
    if (!l.hours || l.hours[day] == null) return { unknown: true };
    const s = span(l.hours[day]);
    if (!s) return { closed: true };
    const kitchen = span("00:00–" + (l.kitchenCloses || "24:00"));
    return { open: s[0], close: Math.min(s[1], kitchen[1]), kitchen: !!l.kitchenCloses && kitchen[1] < s[1] };
  }
  // now: { day, min } from cityNow(c), worked out once for a whole render; ls: the place's branches, likewise
  const stillOpen = (p, now, ls) => (ls || branches(p)).some((l) => { const b = branchToday(l, now.day); return b.close > now.min; });
  function todayLine(p, now, ls) {
    const { day, min } = now;
    ls = ls || branches(p);
    const bs = ls.map((l) => ({ l, ...branchToday(l, day) }));
    if (bs.every((b) => b.unknown)) return "";
    const where = (list) => (ls.length > 1 && list.length < ls.length ? " at " + listOr([...new Set(list.map((b) => b.l.area))]) : "");
    const openNow = bs.filter((b) => b.open <= min && min < b.close);
    if (openNow.length) return "Open now" + where(openNow) + ", " + (openNow.some((b) => b.kitchen) ? "kitchen until " : "until ") + hhmm(Math.max(...openNow.map((b) => b.close)));
    const later = bs.filter((b) => b.open > min);
    if (later.length) return "Opens at " + hhmm(Math.min(...later.map((b) => b.open))) + where(later);
    if (bs.some((b) => b.open != null && b.kitchen && min < span(b.l.hours[day])[1])) return "Kitchen closed";
    if (bs.some((b) => b.open != null)) return "Closed now";
    return bs.some((b) => b.unknown) ? "" : "Closed today";
  }
  function weekText(hours) {
    const out = [];
    for (let i = 0; i < 7;) {
      let j = i;
      while (j < 6 && hours[j + 1] === hours[i]) j++;
      out.push((i === j ? DAYS[i] : DAYS[i] + "–" + DAYS[j]) + " " + (hours[i] == null ? "not known" : hours[i] || "closed"));
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
    if (p.listed) out.push("<div data-quote><b>From the coeliac support groups' list:</b> " + esc(p.listed) + "</div>");
    if (p.caution) out.push('<div class="chg-note"><b>Note from this app:</b> ' + esc(p.caution) + "</div>");
    if (p.status !== "confirmed") out.push('<div class="chg-note bad"><b>Not confirmed open.</b> ' + esc(p.statusNote || "") + "</div>");
    (p.notes || []).forEach((n) => out.push("<div>" + esc(n) + "</div>"));
    out.push('<ul class="locs">' + p.locations.map((l) => '<li><a href="' + esc(mapLink(p, l)) + '" target="_blank" rel="noopener">' + esc(l.address) + "</a>" +
      "<span>" + esc([l.area, l.note].filter(Boolean).join(" · ")) + "</span>" +
      "<span>" + (l.hours ? "<b>Hours:</b> " + esc(weekText(l.hours)) + (l.kitchenCloses ? ". Kitchen closes at " + esc(l.kitchenCloses) : "") +
        (l.hoursNote ? ". " + esc(l.hoursNote) : "") + " (from its website, " + esc(fmtDate(p.checked || c.checked)) + ")"
        : "<b>Hours not known.</b> Check its website before going.") + "</span></li>").join("") + "</ul>");
    out.push('<div class="detail-more"><button type="button" class="link-btn" data-wrong-place="' + esc(p.name) + '">Something wrong?</button></div>');
    out.push('<div class="place-links"><a href="' + esc(p.url) + '" target="_blank" rel="noopener">' + (/instagram\.com/.test(p.url) ? "Instagram" : "Website") + "</a>" +
      (p.listPage ? '<a href="' + esc(p.listPage) + '" target="_blank" rel="noopener">Support groups\' entry</a>' : "") +
      '<button type="button" class="fav-btn" data-fav="' + esc(placeFav(p)) + '" aria-pressed="' + favs.has(placeFav(p)) + '">' + (favs.has(placeFav(p)) ? "★ Saved" : "☆ Save") + "</button></div>");
    // green only when the place itself says everything is gluten free and the app has nothing to add
    // amber is for items that need a change; here it marks a place the app has a caution about, and the rest are plain
    const cls = p.claim === "place-all" && !p.caution ? "t-asis" : p.caution ? "t-swap" : "t-info";
    const label = p.claimLabel || CLAIM_TAGS[p.claim];
    const star = favs.has(placeFav(p)) ? '<span class="star" aria-label="Favourite">★</span>' : "";
    return '<details class="row" data-place="' + esc(p.name) + '"><summary><span class="nm">' + star + esc(p.name) + "<small>" + subs.join(" · ") + '</small><span class="tag ' + cls + '">' +
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
    const unknown = c.places.filter((p) => !p.locations.some((l) => l.hours)).length;
    const empty = cityFilter === "fav" ? "No saved places yet. Open a place and tap ☆ Save."
      : cityFilter === "open" ? "None of the places with known hours are open for the rest of today."
      : 'No places match "' + esc($("q").value.trim()) + '".';
    $("cityList").innerHTML = (cityFilter === "fav" ? favShareBar() : "") + (html || '<p class="empty">' + empty + "</p>" + (cityFilter === "all" ? emptyExtras($("q").value) : "")) +
      (cityFilter === "open" && unknown ? '<p class="muted">' + unknown + " places with unknown hours aren't shown.</p>" : "");
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
    html += '<p class="muted">From ' + esc(plainGuideName(r)) +
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
  function openCard(lang) {
    const p = phrases[lang];
    if (!p) return;
    $("cardTitle").textContent = p.language + " coeliac card";
    $("cardBody").innerHTML = '<div class="phrase-list" lang="' + esc(lang) + '">' + p.card.map((c) =>
      '<div class="phrase"><p class="ph-text">' + esc(c.text) + '</p><p class="ph-en" lang="en-GB">' + esc(c.en) + "</p></div>").join("") + "</div>" +
      "<h3>Words to look for</h3><dl class=\"words\">" + p.words.map(([w, en]) =>
        '<div><dt lang="' + esc(lang) + '">' + esc(w) + "</dt><dd>" + esc(en) + "</dd></div>").join("") + "</dl>" +
      '<p class="muted">Turn the screen towards staff. Phrases written by Claude and not yet checked by a native speaker.</p>';
    openDialog($("gfcard"));
    keepAwake();
  }
  $("cardLaunch").addEventListener("click", (e) => { const b = e.target.closest("[data-lang]"); if (b) openCard(b.dataset.lang); });

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
    let html = "<p>" + esc(cfg.intro || ORDER_INTRO) + "</p>" +
      '<p class="muted">Only items with no gluten ingredients can be ticked. Anything on the Avoid list is shown but can\'t be added. The card ends with ' +
      esc(possessive(r.name)) + " own cross-contact warning.</p>";
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
        const [cls, label] = tagFor(r, i);
        html += '<label class="o-row"><input type="checkbox" data-key="' + esc(k) + '"' + (keys.has(k) ? " checked" : "") + '><span class="nm">' + esc(i.name) +
          (i.order === "modify" ? "<small>" + esc(i.note) + "</small>" : i.original ? '<small lang="' + esc(r.language || "") + '">' + esc(i.original) + "</small>" : "") +
          '</span><span class="tag ' + cls + '">' + esc(label) + "</span></label>";
      }
      if (av.length) {
        html += '<details class="o-avoid"><summary>' + av.length + (av.length === 1 ? " item" : " items") + " on the Avoid list: can't be added</summary>" +
          av.map((a) => '<div class="o-row off"><span class="nm">' + esc(a.name) + '</span><span class="tag t-bad">' + esc(a.tag || a.gluten.map(cap).join(" & ")) + "</span></div>").join("") +
          "</details>";
      }
    }
    $("orderTitle").textContent = "Build an order at " + r.name;
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
  }
  function openAddMenu() {
    ["info", "picker"].forEach((id) => { if ($(id).open) $(id).close(); });
    showUploadState();
    $("upStatus").textContent = "";
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
      const commit = (await gh(await send("/git/commits", { message, tree, parents: [parent] }), "saving the upload")).sha;
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
  const favsLink = () => appUrl() + "#favs=" + toB64url(JSON.stringify({ v: 1, f: [...favs].sort() }));
  function readFavsCode(code) {
    try {
      const d = JSON.parse(fromB64url(code));
      const keys = Array.isArray(d && d.f) ? d.f : [];
      return keys.filter((k) => typeof k === "string" && k.length > 2 && k.length <= 300 && k.includes("|")).slice(0, 500);
    } catch (e) { return null; }
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
    const keys = readFavsCode(importCode);
    importCode = "";
    if (!keys) { toast("That favourites link is damaged. Ask for it to be sent again."); return; }
    importing = sortFavs(keys);
    const { add, have, skip } = importing;
    const li = (t) => "<li>" + esc(t) + "</li>";
    $("favImportBody").innerHTML =
      (add.size ? "<h3>To add (" + add.size + ")</h3><ul class=\"chg-list\">" + [...add.values()].map(li).join("") + "</ul>" : '<p class="muted">Nothing new to add.</p>') +
      (have.length ? '<p class="muted">' + have.length + (have.length === 1 ? " is" : " are") + " already saved on this phone.</p>" : "") +
      (skip.length ? "<h3>Not added (" + skip.length + ")</h3><ul class=\"chg-list\">" + skip.map((x) => li(x.label + " " + x.why + ".")).join("") + "</ul>" : "");
    $("favImportAdd").hidden = !add.size;
    $("favImportAdd").textContent = add.size === 1 ? "Add this to this phone" : "Add these " + add.size + " to this phone";
    ["picker", "info"].forEach((id) => { if ($(id).open) $(id).close(); });
    openDialog($("favImport"));
  }
  $("favImportAdd").addEventListener("click", () => {
    if (!importing) return;
    const n = importing.add.size;
    importing.add.forEach((_, k) => favs.add(k));
    store.set(FAV_KEY, JSON.stringify([...favs]));
    importing = null;
    $("favImport").close();
    if (region === UK) filter = { kind: "fav" }; else cityFilter = "fav";
    render();
    toast(n === 1 ? "Added 1 favourite" : "Added " + n + " favourites");
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
    store.set(FAV_KEY, JSON.stringify([...favs]));
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
  ["picker", "info", "gfcard", "warnings", "staff", "changes", "report", "favImport", "order"].forEach((id) => $(id).addEventListener("click", (e) => { if (e.target === $(id)) $(id).close(); }));
  ["staff", "gfcard"].forEach((id) => $(id).addEventListener("close", () => { if (!$("staff").open && !$("gfcard").open) letGo(); }));
  $("refreshBtn").addEventListener("click", () => load(true));
  $("shareBtn").addEventListener("click", () => {
    const r = region === UK && byId(selected);
    const c = city();
    const url = appUrl() + (c ? "#" + region : r ? "#" + r.id : "");
    const text = c ? "Places in " + c.name + " for coeliacs, from the coeliac support groups' list"
      : r ? "Food and drinks with no gluten ingredients at " + r.name : "Food and drinks with no gluten ingredients at restaurants and coffee shops";
    shareLink("Twoo's Treat Temple", text, url);
  });
  const hashText = () => { try { return decodeURIComponent(location.hash.slice(1)); } catch (e) { return ""; } };
  window.addEventListener("hashchange", () => {
    const raw = hashText();
    if (raw.startsWith("favs=")) { importCode = raw.slice(5); history.replaceState(null, "", location.pathname); maybeImport(); return; }
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
  if (importCode) history.replaceState(null, "", location.pathname); // added or not, a reload shouldn't ask again
  const hashId = importCode ? "" : rawHash;
  const [hashRid, hashItem] = hashId.split("/");
  const saved = store.get(DATA_KEY);
  if (saved) {
    try { data = JSON.parse(saved); } catch (e) { data = null; }
  }
  if (data) setLooked(data.restaurants, true); // the menus saved on this phone are the ones you last saw
  // a link to a restaurant opens the UK menus; any other link (#berlin) is taken as a city until cities.json says otherwise
  if (hashRid) region = data && byId(hashRid) ? UK : hashRid;
  selected = (region === UK && hashRid) || store.get(SEL_KEY) || ALL;
  render();
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
    if (data && region === UK && !hashId && !fromFavLink && !store.get(SEL_KEY)) {
      if (data.restaurants.length === 1) select(data.restaurants[0].id);
      else { renderPicker(); openDialog($("picker")); }
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if ($("staff").open || $("gfcard").open) keepAwake();
    checkForUpdate();
    load(false);
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
