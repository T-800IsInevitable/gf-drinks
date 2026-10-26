(() => {
  "use strict";
  const DATA_KEY = "gf-data-v2";
  const SEL_KEY = "gf-selected";
  const FAV_KEY = "gf-favourites";
  const TIP_KEY = "gf-install-tip-dismissed";
  const SEEN_KEY = "gf-changes-seen"; // "<id>@<source>" for each "what's new" banner dismissed
  const REGION_KEY = "gf-region";
  const ALL = "all";
  const UK = "uk"; // the restaurant menus; any other region is a city in cities.json
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };

  // state
  let data = null;               // { built, restaurants: [ full restaurant objects ] }
  let selected = ALL;            // restaurant id or ALL
  let filter = "all";            // "all" | "fav" | section name | "r:<id>"
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

  // ---------- what changed in the latest guide (built by tools/changes.py) ----------
  const chgCache = new WeakMap();
  function changeOf(r, i) {
    if (!r.changes) return null;
    let m = chgCache.get(r);
    if (!m) {
      m = new Map();
      for (const kind of ["added", "changed", "nowOk", "nowAvoid"]) (r.changes[kind] || []).forEach((c) => m.set(c.section + "|" + c.name, { kind, ...c }));
      chgCache.set(r, m);
    }
    return m.get(i.section + "|" + i.name) || null;
  }
  const howText = (r, h) => tagFor(r, h)[1] + (h.order === "modify" ? ": " + h.note : "");
  const CHG_LABEL = { added: "New", changed: "Order changed", nowOk: "No longer to avoid", nowAvoid: "Now contains gluten" };
  function changeNote(r, c) {
    const since = "the " + esc(r.changes.since) + " guide";
    if (c.kind === "added") return "<div class=\"chg-note\"><b>New</b> since " + since + ".</div>";
    if (c.kind === "nowOk") return "<div class=\"chg-note\"><b>No longer to avoid.</b> It was on the Avoid list in " + since + ".</div>";
    if (c.kind === "nowAvoid") return "<div class=\"chg-note bad\"><b>Now contains gluten.</b> It had no gluten ingredients in " + since + ".</div>";
    return "<div class=\"chg-note\"><b>Ordered differently since " + since + ":</b> it was " + esc(howText(r, c.was)) + ".</div>";
  }
  const chev = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  // rows that aren't things to order as they are (restaurant.json "roles"): no staff card, and they say why
  const ROLE_NOTE = {
    part: "Part of other dishes, listed on its own in the guide. It isn't something to order as it is, so there's no staff card for it.",
    ingredient: "An ingredient, listed on its own in the guide. It isn't something to order as it is, so there's no staff card for it.",
  };

  // How the app decided an item where the guide wasn't plain (the readers' notes, in plain English)
  const decidedNote = (i) => '<div class="decided"><b>How the app decided:</b> ' + esc(i.decided) + "</div>";
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
    out.push('<div class="detail-foot"><span>' + esc(pageText(i.pages)) + '</span><span class="foot-btns">' +
      (i.role ? "" : '<button type="button" class="staff-btn" data-staff="' + esc(k) + '">Show staff</button>') + '<button type="button" class="fav-btn" data-fav="' + esc(k) +
      '" aria-pressed="' + on + '">' + (on ? "★ Saved" : "☆ Save") + "</button></span></div>");
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
    return '<details class="row"><summary><span class="nm">' + star + esc(i.name) + sub + '<span class="tag ' + cls + '">' +
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
  const matches = (i, q) => {
    const ts = typeof q === "string" ? terms(q) : q;
    if (!ts.length) return true;
    // match at the start of words, so "latte" doesn't find "platter"
    // notes ("info") aren't searched: "wheat" shouldn't find dishes whose note merely mentions wheat
    const words = norm([i.name, i.sub, i.note, i.original, i.section, ...(i.ok || [])].filter(Boolean).join(" ")).split(/[^a-z0-9ßäöü]+/).map(stem);
    return ts.every((t) => words.some((w) => w.startsWith(t) || (ALIAS[t] || []).some((a) => w.startsWith(a))));
  };
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
      $("pickName").textContent = r.name;
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

  function renderChips() {
    const chips = [["all", "All"], ["fav", "★ Favourites"]];
    if (selected === ALL) {
      const as = areas();
      if (as.length > 1) as.forEach((a) => chips.push(["a:" + a, a]));
      if (data.restaurants.length > 1) data.restaurants.forEach((r) => chips.push(["r:" + r.id, r.name]));
    } else {
      const r = byId(selected);
      r.sections.filter((s) => r.items.some((i) => i.section === s) || r.avoid.some((a) => a.section === s)).forEach((s) => chips.push([s, shortSection(s)]));
    }
    if (!chips.some(([v]) => v === filter)) filter = "all";
    $("chips").innerHTML = chips.map(([v, l]) =>
      '<button type="button" data-f="' + esc(v) + '" aria-pressed="' + (v === filter) + '">' + esc(l) + "</button>").join("");
  }

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
  function renderNews() {
    const s = seen();
    const news = scope().filter((r) => r.changes && counts(r.changes).length && !s.has(r.id + "@" + r.source));
    $("news").hidden = !news.length;
    $("news").innerHTML = news.map((r) => '<div class="news-row' + (r.changes.nowAvoid.length ? " bad" : "") + '"><p><b>' + esc(r.name) +
      " has a new guide.</b> Since " + esc(r.changes.since) + ": " + esc(counts(r.changes).join(", ")) + '.</p><p class="news-btns">' +
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
    renderNews();
  });
  function openChanges(r) {
    if (!r || !r.changes) return;
    const c = r.changes;
    const list = (title, arr, fn, cls) => arr && arr.length ? "<h3" + (cls ? ' class="' + cls + '"' : "") + ">" + title + " (" + arr.length + ")</h3><ul class=\"chg-list\">" +
      arr.map((x) => "<li><b>" + esc(x.name) + "</b> <span class=\"muted\">" + esc(shortSection(x.section)) + "</span>" + (fn ? fn(x) : "") + "</li>").join("") + "</ul>" : "";
    $("changesTitle").textContent = r.name + ": what changed";
    $("changesBody").innerHTML = '<p class="muted">Compared with the ' + esc(c.since) + " guide. Noticed " + esc(fmtDate(c.date)) + ".</p>" +
      list("Now contain gluten", c.nowAvoid, (x) => x.gluten && x.gluten.length ? ": " + esc(x.gluten.map(cap).join(" & ")) : "", "bad") +
      list("Ordered differently", c.changed, (x) => ": was " + esc(howText(r, x.was)) + ", now " + esc(howText(r, x.now))) +
      list("No longer to avoid", c.nowOk) + list("New", c.added) +
      list("Gone from the guide", c.removed) +
      (c.newAvoid ? "<p class=\"muted\">Plus " + c.newAvoid + " new " + (c.newAvoid === 1 ? "item" : "items") + " on the Avoid list.</p>" : "");
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

  function renderList() {
    let q = $("q").value.trim().toLowerCase();
    const multi = selected === ALL;
    let rs = scope();
    if (filter.startsWith("r:")) rs = rs.filter((r) => r.id === filter.slice(2));
    if (filter.startsWith("a:")) rs = rs.filter((r) => r.area === filter.slice(2));
    ({ rs, q } = withNameFilter(rs, q));
    const { ts, note } = searchTerms(rs, q);
    $("searchNote").hidden = !note;
    $("searchNote").innerHTML = note;
    let html = "";
    let shown = 0;
    for (const r of rs) {
      let items = r.items.filter((i) => matches(i, ts) && visible(kindOf(i)));
      if (filter === "fav") items = items.filter((i) => favs.has(favKey(r, i)));
      else if (!multi && filter !== "all") items = items.filter((i) => i.section === filter);
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
    const glutenHits = rs.reduce((n, r) => n + r.avoid.filter((a) => matches(a, ts)).length, 0);
    if (filter === "fav") empty = favs.size ? "No saved favourites here yet" : "No favourites yet. Open an item and tap ☆ Save.";
    else if (q) empty = 'No items with no gluten ingredients match "' + esc(q) + '".' +
      (glutenHits ? " " + glutenHits + (glutenHits === 1 ? " match is" : " matches are") + " on the Avoid list" + (visible("gluten") ? " below." : ". Tap Avoid above to see " + (glutenHits === 1 ? "it." : "them.")) : "");
    if (!visible("straight") || !visible("change")) empty += " Some items are hidden by the buttons above.";
    $("list").innerHTML = html || '<p class="empty">' + empty + "</p>";

    let avoidHtml = "";
    if (filter !== "fav" && visible("gluten")) {
      for (const r of rs) {
        const av = r.avoid.filter((a) => matches(a, ts) && (multi || filter === "all" || a.section === filter));
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
          return '<details class="row"><summary><span class="nm">' + esc(a.name) +
            (subs.length ? "<small>" + subs.join(" · ") + "</small>" : "") + '<span class="tag t-bad">' +
            esc(a.tag || a.gluten.map(cap).join(" & ")) + "</span></span>" + chev + '</summary><div class="detail">' + (c ? changeNote(r, c) : "") + "<div>" +
            (a.reason ? esc(a.reason) : "Every version contains " + esc(a.gluten.join(" and ").toLowerCase()) + ".") + "</div>" +
            (a.info ? "<div>" + esc(a.info) + "</div>" : "") + (a.decided && a.decided !== a.reason ? decidedNote(a) : "") +
            "<div>" + esc(pageText(a.pages)) + "</div></div></details>";
        }).join("") + "</div>";
      }
    }
    $("avoidWrap").hidden = !avoidHtml;
    $("avoid").innerHTML = avoidHtml;
    // folded until wanted: it opens by itself while searching or when the Avoid button is chosen, and a tap on it overrides that
    const total = rs.reduce((n, r) => n + r.avoid.filter((a) => matches(a, ts) && (multi || filter === "all" || a.section === filter)).length, 0);
    $("avoidTitle").textContent = "Avoid: contains gluten or not suitable" + (total ? " (" + total + ")" : "");
    $("avoidWrap").open = avoidUser !== null ? avoidUser : !!($("q").value.trim() || pick.gluten);
    return shown;
  }

  function renderStatus() {
    let q = $("q").value.trim().toLowerCase();
    const multi = selected === ALL;
    let rs = scope();
    if (filter.startsWith("r:")) rs = rs.filter((r) => r.id === filter.slice(2));
    if (filter.startsWith("a:")) rs = rs.filter((r) => r.area === filter.slice(2));
    ({ rs, q } = withNameFilter(rs, q));
    const n = { straight: 0, change: 0, gluten: 0 };
    const { ts } = searchTerms(rs, q);
    for (const r of rs) {
      for (const i of r.items.concat(r.avoid)) {
        if (!matches(i, ts)) continue;
        if (filter === "fav" && !favs.has(favKey(r, i))) continue;
        if (!multi && !["all", "fav"].includes(filter) && i.section !== filter) continue;
        n[kindOf(i)]++;
      }
    }
    // dot and count on one line, the label under them, so the three buttons are one even row
    const b = (k, cls, label) => '<button type="button" data-k="' + k + '" aria-pressed="' + pick[k] + '"><span class="dot ' + cls + '"></span>' +
      '<span class="lbl">' + label + '</span> <span class="cnt">' + n[k] + "</span></button>";
    $("status").classList.toggle("picking", picking());
    $("status").innerHTML =b("straight", "d-ok", "No gluten ingredients") + b("change", "d-swap", "Needs a change") + b("gluten", "d-bad", "Avoid");
  }

  const THEMES = [
    ["auto", "Match phone", "linear-gradient(135deg,#f6f5f2 50%,#171412 50%)"],
    ["light", "Light", "#f6f5f2"],
    ["dark", "Dark", "#171412"],
    ["pink-light", "Pink light", "linear-gradient(135deg,#fbf3f6 50%,#c2185b 50%)"],
    ["pink-dark", "Pink dark", "linear-gradient(135deg,#1a1116 50%,#f48fb1 50%)"],
  ];
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
    $("themes").innerHTML = THEMES.map(([id, label, sw]) => '<button type="button" data-t="' + id + '" aria-pressed="' + (cur === id) +
      '"><span class="swatch" style="background:' + sw + '"></span>' + label + "</button>").join("");
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
    const whatChanged = (r) => r.changes ? ' <button type="button" class="link-btn" data-whatchanged="' + esc(r.id) + '">What changed, noticed ' +
      esc(fmtDate(r.changes.date)) + " &rsaquo;</button>" : "";
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
    // first run: say what the app is, and put Berlin next to All restaurants so it's on the first screen without scrolling
    if (!welcomeNow && !store.get(SEL_KEY) && !store.get(WELCOME_KEY)) { welcomeNow = true; store.set(WELCOME_KEY, "1"); }
    $("pickWelcome").hidden = !welcomeNow;
    const opt = (id, name, line, meta, stale) =>
      '<button type="button" class="pick-opt" data-r="' + esc(id) + '" aria-pressed="' + (region === UK && selected === id) + '"><span class="po-main"><b>' +
      esc(name) + "</b><span>" + esc(line) + "</span></span>" + (stale ? '<span class="tag t-swap">Out of date</span>' : '<span class="po-meta">' + esc(meta) + "</span>") + "</button>";
    const total = data.restaurants.reduce((n, r) => n + r.stats.items, 0);
    const as = areas();
    const lineOf = (r, withArea) => [r.id === last ? "Last used" : "", r.type, withArea ? r.area : "", guideLine(r)].filter(Boolean).join(" · ");
    const one = (r, withArea) => opt(r.id, r.name, lineOf(r, withArea), r.stats.items + " items", isStale(r));
    const grouped = as.length > 1
      ? as.map((a) => '<div class="sub-h">' + esc(a) + "</div>" + chooserOrder(data.restaurants.filter((r) => r.area === a)).map((r) => one(r, false)).join("")).join("") +
        chooserOrder(data.restaurants.filter((r) => !r.area)).map((r) => opt(r.id, r.name, r.type, r.stats.items + " items", isStale(r))).join("")
      : chooserOrder(data.restaurants).map((r) => one(r, true)).join("");
    // other cities (cities.json) are lists of places rather than menus, so they switch region instead of restaurant
    const others = Object.entries(cities).map(([cid, c]) => (welcomeNow ? "" : '<div class="sub-h">' + esc(c.name) + "</div>") +
      '<button type="button" class="pick-opt" data-region="' + esc(cid) + '" aria-pressed="' + (region === cid) + '"><span class="po-main"><b>' +
      esc(c.name) + "</b><span>Places that are all gluten free, by their own word or the coeliac support groups'" +
      (c.places.some((p) => p.claim === "separate") ? ", or that say they have a separate gluten free kitchen" : "") + "</span></span>" +
      '<span class="po-meta">' + c.places.length + " places</span></button>").join("");
    const all = opt(ALL, "All restaurants", "Search and browse everything", total + " items", false);
    $("pickList").innerHTML = '<div class="sub-h">' + (welcomeNow ? "Choose where" : "UK") + "</div>" + all +
      (welcomeNow ? others + '<div class="sub-h">Or one restaurant</div>' + grouped : grouped + others) +
      '<p class="pick-note">More restaurants can be added by the app\'s owner from each restaurant\'s allergen guide.</p>';
  }

  function render() {
    syncSearching();
    renderRegion();
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
    filter = "all";
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

  // ---------- UK / city switch: a city is a hand-checked list of places (cities.json), not menus ----------
  function renderRegion() {
    const ids = [UK, ...Object.keys(cities)];
    $("region").hidden = ids.length < 2;
    $("region").innerHTML = ids.map((id) => '<button type="button" data-region="' + esc(id) + '" aria-pressed="' + (region === id) + '">' +
      esc(id === UK ? "UK" : cities[id].name) + "</button>").join("");
    const inCity = region !== UK;
    $("ukView").hidden = inCity;
    $("cityView").hidden = !inCity;
    $("status").hidden = inCity;
  }
  function setRegion(id) {
    region = id;
    store.set(REGION_KEY, id);
    $("q").value = "";
    cityFilter = "all";
    history.replaceState(null, "", id !== UK ? "#" + id : selected === ALL ? location.pathname : "#" + selected);
    render();
    window.scrollTo({ top: 0 });
  }
  $("region").addEventListener("click", (e) => { const b = e.target.closest("[data-region]"); if (b && b.dataset.region !== region) setRegion(b.dataset.region); });

  const mapLink = (p, l) => "https://maps.apple.com/?q=" + encodeURIComponent(p.name) + "&address=" + encodeURIComponent(l.address);
  const cityStale = (c) => new Date(c.checked + "T12:00:00Z").getTime() + (c.recheckDays || 90) * 864e5 < Date.now();
  function renderCity() {
    const c = city();
    if (!c) { $("cityList").innerHTML = '<p class="empty">Loading…</p>'; return; }
    syncSearching();
    $("pickName").textContent = c.name;
    $("pickBtn").setAttribute("aria-label", c.name + ". Choose where to eat");
    $("guideLine").textContent = c.places.length + " places · checked " + fmtDate(c.checked) + offlineTag();
    $("q").placeholder = "Search " + c.name;
    const chips = [["all", "All"], ["open", "Still open today"], ["fav", "★ Saved"]].concat(c.sections.filter((s) => c.places.some((p) => p.section === s)).map((s) => [s, s]));
    if (!chips.some(([v]) => v === cityFilter)) cityFilter = "all";
    const card = phrases[c.language];
    $("chips").innerHTML = '<button type="button" data-near aria-pressed="' + nearSort + '">Near me</button>' + chips.map(([v, l]) =>
      '<button type="button" data-f="' + esc(v) + '" aria-pressed="' + (v === cityFilter) + '">' + esc(l) + "</button>").join("") +
      (card ? '<button type="button" data-card>' + esc(card.language) + " card</button>" : "");
    const n = (claim) => c.places.filter((p) => p.claim === claim).length;
    $("cityIntroLine").innerHTML = "<b>Tags say who calls a place gluten free</b>, not the app. Tell staff you're coeliac.";
    $("cityIntro").innerHTML = "<b>Each place's tag says who calls it gluten free.</b> " +
      [n("place-all") && n("place-all") + " say so themselves", n("list-all") && n("list-all") + " are listed as all gluten free by the support groups but don't say so on their own websites",
        n("place-part") && n("place-part") + " says only part of its range is", n("separate") && n("separate") + " says it makes gluten free food in a separate kitchen"]
        .filter(Boolean).join("; ") + ". That's their claim, not the app's. They come from the list kept by " + esc(c.list.by) +
      ", checked against each place's own website on " + esc(fmtDate(c.checked)) + ". Nobody from this app has seen their kitchens, so tell staff you have coeliac disease.";
    $("cityStale").hidden = !cityStale(c);
    $("cityStale").innerHTML = cityStale(c) ? "<p><b>This list may be out of date.</b> It was checked on " + esc(fmtDate(c.checked)) +
      ". Places open, close and change, so check before you go.</p>" : "";
    $("cityTipsLabel").textContent = "Before you go (" + c.tips.length + ")";
    $("cityTips").innerHTML = tipsHtml(c.tips);
    $("cityFoot").innerHTML = '<p><b>Sources:</b> <a href="' + esc(c.list.url) + '" target="_blank" rel="noopener">' + esc(c.list.name) + "</a>, kept by " +
      esc(c.list.by) + ", and each place's own website. Checked " + esc(fmtDate(c.checked)) + ".</p>" +
      "<p>That list also has places it says have some gluten free dishes. They're left out here because their kitchens also use gluten, unless they say they make gluten free food separately.</p>" +
      "<p>Unofficial guide. Not affiliated with any of these places or the DZG.</p>";
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
  const cityDay = (c) => cityNow(c).day;
  // "09:30–14:30" (perhaps with a note after it) -> [570, 870]; "" -> null
  const span = (h) => { const m = (h || "").match(/(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})/); return m ? [m[1] * 60 + +m[2], m[3] * 60 + +m[4]] : null; };
  const hhmm = (n) => String(Math.floor(n / 60)).padStart(2, "0") + ":" + String(n % 60).padStart(2, "0");
  // still open today: open now, or opening later today
  // The branches that matter: the nearest one when sorting by distance, otherwise all of them.
  // A branch's day is: a span [open, close] (close = when the kitchen stops, if earlier), "closed", or unknown (no hours, or null).
  const branches = (p) => (nearSort && here ? [p.locations.slice().sort((a, b) => kmTo(a, here) - kmTo(b, here))[0]] : p.locations);
  function branchToday(l, day) {
    if (!l.hours || l.hours[day] == null) return { unknown: true };
    const s = span(l.hours[day]);
    if (!s) return { closed: true };
    const kitchen = span("00:00–" + (l.kitchenCloses || "24:00"));
    return { open: s[0], close: Math.min(s[1], kitchen[1]), kitchen: !!l.kitchenCloses && kitchen[1] < s[1] };
  }
  const stillOpen = (c, p) => { const { day, min } = cityNow(c); return branches(p).some((l) => { const b = branchToday(l, day); return b.close > min; }); };
  function todayLine(c, p) {
    const { day, min } = cityNow(c);
    const ls = branches(p);
    const bs = ls.map((l) => ({ l, ...branchToday(l, day) }));
    if (bs.every((b) => b.unknown)) return "";
    const where = (list) => (ls.length > 1 && list.length < ls.length ? " at " + listOr([...new Set(list.map((b) => b.l.area))]) : "");
    const now = bs.filter((b) => b.open <= min && min < b.close);
    if (now.length) return "Open now" + where(now) + ", " + (now.some((b) => b.kitchen) ? "kitchen until " : "until ") + hhmm(Math.max(...now.map((b) => b.close)));
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
  function placeHtml(c, p) {
    const subs = [esc(p.type), esc([...new Set(p.locations.map((l) => l.area))].join(", "))];
    if (nearSort && here) subs.unshift(placeKm(p).toFixed(1) + " km" + (p.locations.length > 1 ? " (" + esc(branches(p)[0].area) + ")" : ""));
    const today = todayLine(c, p);
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
        (l.hoursNote ? ". " + esc(l.hoursNote) : "") + " (from its website, " + esc(fmtDate(c.checked)) + ")"
        : "<b>Hours not known.</b> Check its website before going.") + "</span></li>").join("") + "</ul>");
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
    const places = c.places.filter((p) => matches(placeText(p), ts) && (cityFilter === "all" || (cityFilter === "open" ? stillOpen(c, p)
      : cityFilter === "fav" ? favs.has(placeFav(p)) : p.section === cityFilter)));
    let html = "";
    if (nearSort && here && places.length) {
      const near = places.slice().sort((a, b) => placeKm(a) - placeKm(b));
      html = '<h2 class="group-h">Nearest first<small>' + near.length + "</small></h2>" + '<div class="card">' + near.map((p) => placeHtml(c, p)).join("") + "</div>";
    } else for (const s of c.sections) {
      const inSec = places.filter((p) => p.section === s);
      if (!inSec.length) continue;
      html += '<h2 class="group-h">' + esc(s) + "<small>" + inSec.length + "</small></h2>" + '<div class="card">' + inSec.map((p) => placeHtml(c, p)).join("") + "</div>";
    }
    const unknown = c.places.filter((p) => !p.locations.some((l) => l.hours)).length;
    const empty = cityFilter === "fav" ? "No saved places yet. Open a place and tap ☆ Save."
      : cityFilter === "open" ? "None of the places with known hours are open for the rest of today."
      : 'No places match "' + esc($("q").value.trim()) + '".';
    $("cityList").innerHTML = (html || '<p class="empty">' + empty + "</p>") +
      (cityFilter === "open" && unknown ? '<p class="muted">' + unknown + " places with unknown hours aren't shown.</p>" : "");
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
      (r.changes ? '. <button type="button" class="link-btn" data-whatchanged="' + esc(r.id) + '">What changed, noticed ' +
        esc(fmtDate(r.changes.date)) + " &rsaquo;</button>" : ".") + "</p>";
    if (groups.length) {
      html += "<h4>What " + esc(r.name) + (/s$/.test(r.name) ? "'" : "'s") + " guide says</h4>";
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
      const res = await fetch("phrases.json", { cache: "no-store" });
      if (res.ok) phrases = await res.json();
    } catch (e) { /* offline and never cached: no card */ }
    $("cardLangs").textContent = Object.values(phrases).map((p) => p.language).join(", ") || "none yet";
    if (data) renderCardLaunch();
    if (city()) renderCity();
  }
  async function loadCities() {
    try {
      const res = await fetch("cities.json", { cache: "no-store" });
      if (res.ok) cities = await res.json();
    } catch (e) { /* offline and never cached: UK menus only */ }
    if (region !== UK && !cities[region]) { // not a city (or the list couldn't load): back to the menus
      if (region === hashId) selected = region; // the link was to a restaurant after all
      region = UK;
    }
    render();
    if (data && $("picker").open) renderPicker(); // the first-visit chooser may have opened before the cities arrived
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
      '<p class="muted">Turn the screen towards staff. From ' + esc(r.name) + (/s$/.test(r.name) ? "'" : "'s") + " allergen guide" +
      (i.pages && i.pages.length ? ", " + esc(pageText(i.pages).toLowerCase()) : "") + ".</p>";
    openDialog($("staff"));
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
  $("openUpload").addEventListener("click", () => { $("info").close(); showUploadState(); $("upStatus").textContent = ""; openDialog($("upload")); });
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
      localStorage.removeItem(KEY_KEY);
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
  $("keyForget").addEventListener("click", () => { try { localStorage.removeItem(KEY_KEY); } catch (e) {} showUploadState(); toast("Key removed from this phone"); });

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
      try { localStorage.removeItem(KEY_KEY); } catch (e) { /* storage unavailable */ }
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
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(url + " " + res.status);
    return { json: await res.json(), offline: res.headers.get("X-GF-Offline") === "1" };
  }

  async function load(manual) {
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
      const changed = !prev || prev.built !== fresh.built;
      const wasOffline = offlineNow;
      offlineNow = offline;
      if (changed || wasOffline !== offlineNow) {
        if (changed) {
          if (!prev && firstVisit && !store.get(SEEN_KEY)) store.set(SEEN_KEY, JSON.stringify(fresh.restaurants.map((r) => r.id + "@" + r.source)));
          data = fresh;
          store.set(DATA_KEY, JSON.stringify(fresh));
        }
        render();
      }
      if (offline) {
        if (manual) toast("No connection. Showing the menus saved on this phone.");
      } else if (prev) {
        const news = fresh.restaurants.filter((r) => {
          const old = prev.restaurants.find((o) => o.id === r.id);
          return !old || old.source !== r.source;
        });
        if (news.length) toast("New guides: " + news.map((r) => r.name).join(", "));
        else if (manual) toast(changed ? "Menus refreshed" : "You have the latest menus");
      }
    } catch (e) {
      if (data) {
        if (!offlineNow) { offlineNow = true; render(); }
        if (manual) toast("No connection. Showing the menus saved on this phone.");
      } else {
        $("guideLine").textContent = "Couldn't load menus";
        $("list").innerHTML = '<p class="empty">Couldn\'t load the menus. Check your connection and tap ↻.</p>';
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
    const b = e.target.closest("button");
    if (!b) return;
    const f = b.dataset.f;
    if (region !== UK) {
      if (b.hasAttribute("data-near")) { toggleNear(); return; }
      if (b.hasAttribute("data-card")) { openCard(city().language); return; }
      cityFilter = f;
      renderCity();
      window.scrollTo({ top: 0 });
      return;
    }
    if (!data) return;
    if (f.startsWith("r:")) { select(f.slice(2)); return; }
    filter = f;
    renderChips();
    renderStatus();
    renderList();
    window.scrollTo({ top: 0 });
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
    b.setAttribute("aria-pressed", on);
    b.textContent = on ? "★ Saved" : "☆ Save";
    const nm = b.closest(".row").querySelector(".nm");
    const star = nm.querySelector(".star");
    if (on && !star) nm.insertAdjacentHTML("afterbegin", '<span class="star" aria-label="Favourite">★</span>');
    if (!on && star) star.remove();
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
  $("infoBtn").addEventListener("click", () => { renderLastChecked(); openDialog($("info")); });
  ["picker", "info", "gfcard", "warnings", "staff", "changes"].forEach((id) => $(id).addEventListener("click", (e) => { if (e.target === $(id)) $(id).close(); }));
  $("refreshBtn").addEventListener("click", () => load(true));
  $("shareBtn").addEventListener("click", async () => {
    const r = region === UK && byId(selected);
    const c = city();
    const url = location.origin + location.pathname.replace(/index\.html$/, "") + (c ? "#" + region : r ? "#" + r.id : "");
    const text = c ? "Places in " + c.name + " for coeliacs, from the coeliac support groups' list"
      : r ? "Food and drinks with no gluten ingredients at " + r.name : "Food and drinks with no gluten ingredients at restaurants and coffee shops";
    if (navigator.share) {
      try { await navigator.share({ title: "Twoo's Treat Temple", text, url }); } catch (e) { /* share sheet closed */ }
      return;
    }
    try { await navigator.clipboard.writeText(url); toast("Link copied"); } catch (e) { toast(url); }
  });
  window.addEventListener("hashchange", () => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (cities[id]) { if (id !== region) setRegion(id); }
    else if (data && id && byId(id) && (id !== selected || region !== UK)) select(id);
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
      const top = document.querySelector(".top");
      if (y > 160 && y > lastY + 6) top.classList.add("collapsed");
      else if (y < lastY - 6 || y < 160) top.classList.remove("collapsed");
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
  const hashId = decodeURIComponent(location.hash.slice(1));
  const saved = store.get(DATA_KEY);
  if (saved) {
    try { data = JSON.parse(saved); } catch (e) { data = null; }
  }
  // a link to a restaurant opens the UK menus; any other link (#berlin) is taken as a city until cities.json says otherwise
  if (hashId) region = data && byId(hashId) ? UK : hashId;
  selected = (region === UK && hashId) || store.get(SEL_KEY) || ALL;
  render();
  loadPhrases();
  loadCities();
  load(false).then(() => {
    // first visit: one restaurant opens directly; several, the picker opens so you start somewhere specific
    if (data && region === UK && hashId && byId(hashId)) { store.set(SEL_KEY, hashId); store.set(LAST_KEY, hashId); }
    if (data && region === UK && !hashId && !store.get(SEL_KEY)) {
      if (data.restaurants.length === 1) select(data.restaurants[0].id);
      else { renderPicker(); openDialog($("picker")); }
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    load(false);
    if (city()) renderCityList(); // open or closed may have changed while the app was in the background
  });
  // Every minute, bring each place's "Open now / Closed now" up to date without closing the one you're reading
  setInterval(() => {
    const c = city();
    if (!c || document.visibilityState !== "visible") return;
    if (cityFilter === "open" && !document.querySelector("#cityList details[open]")) { renderCityList(); return; }
    document.querySelectorAll("#cityList details[data-place]").forEach((d) => {
      const p = c.places.find((x) => x.name === d.dataset.place);
      const el = d.querySelector(".today");
      const t = p && todayLine(c, p);
      if (el && t) { el.textContent = t; el.classList.toggle("shut", /^(Closed|Kitchen closed)/.test(t)); }
    });
  }, 60000);
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
})();
