(() => {
  "use strict";
  const DATA_KEY = "gf-data-v2";
  const SEL_KEY = "gf-selected";
  const FAV_KEY = "gf-favourites";
  const TIP_KEY = "gf-install-tip-dismissed";
  const ALL = "all";
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
  const SHOW_KEY = "gf-show";
  const THEME_KEY = "gf-theme";
  let show = Object.assign({ straight: true, change: true, gluten: true }, JSON.parse(store.get(SHOW_KEY) || "{}"));
  // "straight" = no gluten ingredients as served: asis/any/except (fine as served, or with any milk but the ones named); change = swap/modify
  const kindOf = (i) => (!i.order ? "gluten" : (i.order === "swap" || i.order === "modify") ? "change" : "straight");

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
  const shortRuns = (s) => (s || "").replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*/g, "$1");
  function listOr(arr) {
    return arr.length < 2 ? arr.join("") : arr.slice(0, -1).join(", ") + " or " + arr[arr.length - 1];
  }
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  function guideLine(r) {
    const g = r.guide || {};
    const season = (g.title || "").replace(/\s*Beverages$/, "");
    return [season && season !== "Allergen guide" ? season + " menu" : "", shortRuns(g.runs) || (g.version ? "Guide " + fmtDate(g.version) : "")]
      .filter(Boolean).join(" · ");
  }
  function tagFor(r, i) {
    const label = r.optionLabel || "option";
    switch (i.order) {
      case "asis": return ["t-asis", "No gluten ingredients"];
      case "any": return ["t-any", "Any " + label];
      case "swap": return ["t-swap", "Swap " + label];
      case "modify": return ["t-swap", "Ask"];
      default: return ["t-any", "Any " + label + " except " + i.not.join(", ")];
    }
  }
  const pageText = (p) => (!p || !p.length ? "" : (p.length > 1 ? "Guide pages " : "Guide page ") + p.join(", "));
  const chev = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function detailFor(r, i) {
    const out = [];
    if (i.original) {
      out.push('<div>On the menu as <b lang="' + esc(r.language || "") + '">' + esc(i.original) + "</b>" +
        (i.sectionOriginal ? ' under <span lang="' + esc(r.language || "") + '">' + esc(i.sectionOriginal) + "</span>" : "") + "</div>");
    }
    if (i.info) out.push("<div>" + esc(i.info) + "</div>");
    if (i.order === "asis") out.push("<div>No gluten ingredients as listed. No changes needed.</div>");
    if (i.order === "modify") out.push("<div><b>Ask for:</b> " + esc(i.note) + "</div>");
    if (i.order === "swap") {
      const std = i.standard || "";
      out.push(i.standardFrom === "guide"
        ? "<div><b>Comes with " + esc(std) + " as standard.</b> Ask for " + esc(listOr(i.ok)) + ".</div>"
        : "<div><b>Usually made with " + esc(std) + "</b> (going by its name). Ask for " + esc(listOr(i.ok)) + ".</div>");
    }
    if (i.ok) {
      out.push('<div class="milks">' + i.ok.map((m) => '<span class="milk">' + esc(m) + "</span>").join("") +
        (i.not || []).map((m) => '<span class="milk no" aria-label="not ' + esc(m) + '">' + esc(m) + "</span>").join("") + "</div>");
    }
    const k = favKey(r, i);
    const on = favs.has(k);
    out.push('<div class="detail-foot"><span>' + esc(pageText(i.pages)) + '</span><button type="button" class="fav-btn" data-fav="' + esc(k) +
      '" aria-pressed="' + on + '">' + (on ? "★ Saved" : "☆ Save") + "</button></div>");
    return out.join("");
  }

  function rowHtml(r, i, showRestaurant) {
    const [cls, label] = tagFor(r, i);
    const star = favs.has(favKey(r, i)) ? '<span class="star" aria-label="Favourite">★</span>' : "";
    const subs = [];
    if (i.order === "modify") subs.push(esc(i.note));
    if (i.original) subs.push('<span lang="' + esc(r.language || "") + '">' + esc(i.original) + "</span>");
    if (showRestaurant) subs.push(esc(r.name));
    const sub = subs.length ? "<small>" + subs.join(" · ") + "</small>" : "";
    return '<details class="row"><summary><span class="nm">' + star + esc(i.name) + sub + '</span><span class="tag ' + cls + '">' +
      esc(label) + "</span>" + chev + '</summary><div class="detail">' + detailFor(r, i) + "</div></details>";
  }

  // Search: every word must match (in English or the original language). Words like "gluten free" / "gf" are
  // ignored because everything listed is already sorted by gluten; plurals match singulars ("toasties" -> "toastie").
  const STOP = new Set(["gluten", "free", "gf", "glutenfree", "gluten-free", "no", "without", "and", "with"]);
  const stem = (w) => w.replace(/ies$/, "ie").replace(/(ches|shes|xes)$/, (m) => m.slice(0, -2)).replace(/([^s])s$/, "$1");
  const norm = (t) => t.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  function terms(q) { return norm(q).split(/[^a-z0-9ßäöü]+/).filter((w) => w && !STOP.has(w)).map(stem); }
  const matches = (i, q) => {
    const ts = typeof q === "string" ? terms(q) : q;
    if (!ts.length) return true;
    // match at the start of words, so "latte" doesn't find "platter"
    const words = norm([i.name, i.sub, i.note, i.original, i.info, i.section].filter(Boolean).join(" ")).split(/[^a-z0-9ßäöü]+/).map(stem);
    return ts.every((t) => words.some((w) => w.startsWith(t)));
  };
  const areas = () => [...new Set(data.restaurants.map((r) => r.area).filter(Boolean))];
  const scope = () => (selected === ALL ? data.restaurants : [byId(selected)].filter(Boolean));

  // ---------- rendering ----------
  function renderHeader() {
    const r = byId(selected);
    if (r) {
      $("pickName").textContent = r.name;
      $("guideLine").textContent = guideLine(r) || r.covers;
      $("q").placeholder = "Search " + r.name;
    } else {
      $("pickName").textContent = "All restaurants";
      const n = data.restaurants.length;
      $("guideLine").textContent = n + (n === 1 ? " restaurant" : " restaurants") + " · tap to choose";
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
    $("stale").innerHTML = stale.map((r) =>
      "<p><b>" + esc(r.name) + " guide may be out of date.</b> It covered up to " + esc(fmtDate(r.guide.validUntil)) +
      ". Check in store before ordering" + (r.officialUrl ? ', or see <a href="' + esc(r.officialUrl) + '" target="_blank" rel="noopener">their allergen info</a>' : "") + ".</p>").join("");
    renderCardLaunch();
    const r = byId(selected);
    $("tips").hidden = !(r && r.tips && r.tips.length);
    $("tips").innerHTML = r && r.tips ? r.tips.map((t) => {
      const m = t.match(/^([^:.]+[:.])\s+(.+)$/);
      return "<div>" + (m ? "<b>" + esc(m[1]) + "</b> " + esc(m[2]) : esc(t)) + "</div>";
    }).join("") : "";
  }

  function renderList() {
    const q = $("q").value.trim().toLowerCase();
    const multi = selected === ALL;
    let rs = scope();
    if (filter.startsWith("r:")) rs = rs.filter((r) => r.id === filter.slice(2));
    if (filter.startsWith("a:")) rs = rs.filter((r) => r.area === filter.slice(2));
    let html = "";
    let shown = 0;
    for (const r of rs) {
      let items = r.items.filter((i) => matches(i, q) && show[kindOf(i)]);
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
    const glutenHits = rs.reduce((n, r) => n + r.avoid.filter((a) => matches(a, q)).length, 0);
    if (filter === "fav") empty = favs.size ? "No saved favourites here yet" : "No favourites yet. Open an item and tap ☆ Save.";
    else if (q) empty = 'No items with no gluten ingredients match "' + esc(q) + '".' +
      (glutenHits ? " " + glutenHits + (glutenHits === 1 ? " match is" : " matches are") + " on the Avoid list" + (show.gluten ? " below." : ". Tap Avoid above to see " + (glutenHits === 1 ? "it." : "them.")) : "");
    if (!show.straight || !show.change) empty += " Some items are hidden by the buttons above.";
    $("list").innerHTML = html || '<p class="empty">' + empty + "</p>";

    let avoidHtml = "";
    if (filter !== "fav" && show.gluten) {
      for (const r of rs) {
        const av = r.avoid.filter((a) => matches(a, q) && (multi || filter === "all" || a.section === filter));
        if (!av.length) continue;
        if (multi) avoidHtml += '<div class="sub-h">' + esc(r.name) + "</div>";
        avoidHtml += '<div class="card">' + av.map((a) =>
          '<details class="row"><summary><span class="nm">' + esc(a.name) +
          (a.original ? '<small lang="' + esc(r.language || "") + '">' + esc(a.original) + "</small>" : "") + '</span><span class="tag t-bad">' +
          esc(a.tag || a.gluten.map(cap).join(" & ")) + "</span>" + chev + '</summary><div class="detail"><div>' +
          (a.reason ? esc(a.reason) : "Every version contains " + esc(a.gluten.join(" and ").toLowerCase()) + ".") + "</div>" +
          (a.info ? "<div>" + esc(a.info) + "</div>" : "") + "<div>" + esc(pageText(a.pages)) + "</div></div></details>").join("") + "</div>";
      }
    }
    $("avoidWrap").hidden = !avoidHtml;
    $("avoid").innerHTML = avoidHtml;
    return shown;
  }

  function renderStatus() {
    const q = $("q").value.trim().toLowerCase();
    const multi = selected === ALL;
    let rs = scope();
    if (filter.startsWith("r:")) rs = rs.filter((r) => r.id === filter.slice(2));
    if (filter.startsWith("a:")) rs = rs.filter((r) => r.area === filter.slice(2));
    const n = { straight: 0, change: 0, gluten: 0 };
    for (const r of rs) {
      for (const i of r.items.concat(r.avoid)) {
        if (!matches(i, q)) continue;
        if (filter === "fav" && !favs.has(favKey(r, i))) continue;
        if (!multi && !["all", "fav"].includes(filter) && i.section !== filter) continue;
        n[kindOf(i)]++;
      }
    }
    const b = (k, cls, label) => '<button type="button" data-k="' + k + '" aria-pressed="' + show[k] + '"><span class="dot ' + cls + '"></span>' +
      label + " <small>" + n[k] + "</small></button>";
    $("status").innerHTML = b("straight", "d-ok", "No gluten ingredients") + b("change", "d-swap", "Needs a change") + b("gluten", "d-bad", "Avoid");
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
    show[b.dataset.k] = !show[b.dataset.k];
    store.set(SHOW_KEY, JSON.stringify(show));
    renderStatus();
    renderList();
  });

  function renderSources() {
    const line = (r) => {
      const g = r.guide || {};
      return "<p><b>" + esc(r.name) + ":</b> " + esc(r.covers ? r.covers + ". " : "") + "From " + esc(r.source) +
        (g.version ? " (version " + esc(fmtDate(g.version)) + ")" : "") + ". " + esc(r.stats.items) + " with no gluten ingredients, " + esc(r.stats.avoid) +
        " to avoid." + (r.officialUrl ? ' <a href="' + esc(r.officialUrl) + '" target="_blank" rel="noopener">Official site</a>' : "") + "</p>";
    };
    $("sources").innerHTML = scope().map(line).join("");
    $("infoSources").innerHTML = data.restaurants.map(line).join("") + "<p>Rules: " + esc([...new Set(data.restaurants.map((r) => r.rule))].join(" ")) +
      " If the allergen column and ingredients disagree, the item is left out.</p><p>Last built " + esc(fmtDate(data.built)) + ".</p>";
    const notes = data.restaurants.flatMap((r) => (r.warnings || []).map((w) => r.name + ": " + w));
    $("notesWrap").hidden = !notes.length;
    $("notes").innerHTML = notes.map((w) => "<li>" + esc(w) + "</li>").join("");
  }

  function renderPicker() {
    const opt = (id, name, line, meta, stale) =>
      '<button type="button" class="pick-opt" data-r="' + esc(id) + '" aria-pressed="' + (selected === id) + '"><span class="po-main"><b>' +
      esc(name) + "</b><span>" + esc(line) + "</span></span>" + (stale ? '<span class="tag t-swap">Out of date</span>' : '<span class="po-meta">' + esc(meta) + "</span>") + "</button>";
    const total = data.restaurants.reduce((n, r) => n + r.stats.items, 0);
    const as = areas();
    const grouped = as.length > 1
      ? as.map((a) => '<div class="sub-h">' + esc(a) + "</div>" + data.restaurants.filter((r) => r.area === a)
          .map((r) => opt(r.id, r.name, [r.type, guideLine(r)].filter(Boolean).join(" · "), r.stats.items + " items", isStale(r))).join("")).join("") +
        data.restaurants.filter((r) => !r.area).map((r) => opt(r.id, r.name, r.type, r.stats.items + " items", isStale(r))).join("")
      : data.restaurants.map((r) => opt(r.id, r.name, [r.type, r.area, guideLine(r)].filter(Boolean).join(" · "), r.stats.items + " items", isStale(r))).join("");
    $("pickList").innerHTML = opt(ALL, "All restaurants", "Search and browse everything", total + " items", false) + grouped +
      '<p class="pick-note">More restaurants can be added by the app\'s owner from each restaurant\'s allergen guide.</p>';
  }

  function render() {
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
    store.set(SEL_KEY, id);
    history.replaceState(null, "", id === ALL ? location.pathname : "#" + id);
    $("q").value = "";
    render();
    window.scrollTo({ top: 0 });
  }

  // ---------- warnings page ----------
  function warningsFor(r) {
    const groups = {};
    (r.notices || []).forEach((n) => { (groups[n.label] = groups[n.label] || []).push(n); });
    let html = "";
    if (selected === ALL) html += '<h3 class="w-rest">' + esc(r.name) + "</h3>";
    html += '<p class="muted">From ' + esc(r.source) + (r.guide && r.guide.version ? ", version " + esc(fmtDate(r.guide.version)) : "") + ".</p>";
    const labels = Object.keys(groups);
    if (labels.length) {
      html += "<h4>What " + esc(r.name) + (/s$/.test(r.name) ? "'" : "'s") + " guide says</h4>";
      for (const l of labels) {
        html += '<div class="w-group"><div class="w-label">' + esc(l) + "</div>" + groups[l].map((n) =>
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
    if (r.warnings && r.warnings.length) {
      html += "<h4>Notes from reading the guide</h4><ul class=\"notes\">" + r.warnings.map((w) => "<li>" + esc(w) + "</li>").join("") + "</ul>";
    }
    if (isStale(r)) html += '<p class="w-stale">This guide covered up to ' + esc(fmtDate(r.guide.validUntil)) + ". A newer one may be out.</p>";
    return html;
  }
  function openWarnings() {
    if (!data) return;
    const r = byId(selected);
    $("warnTitle").textContent = r ? r.name + ": warnings" : "Warnings";
    $("warnBody").innerHTML =
      '<div class="w-intro"><p><b>"No gluten ingredients" means the restaurant\'s guide lists no gluten cereal for that item.</b> ' +
      "It isn't a gluten free claim: none of these guides use the words \"gluten free\", and none claim to test for gluten or promise " +
      "there's been no contact with it. If you have coeliac disease, ask staff about shared equipment such as toasters, fryers and tongs.</p></div>" +
      scope().map(warningsFor).join('<hr class="w-sep">');
    if ($("info").open) $("info").close();
    openDialog($("warnings"));
  }
  function renderWarnCount() {
    const n = scope().reduce((t, r) => t + (r.notices || []).length + (r.gaps || []).length, 0);
    $("warnCount").textContent = n ? "(" + n + ")" : "";
  }
  $("openWarnings").addEventListener("click", openWarnings);
  $("openWarnings2").addEventListener("click", openWarnings);

  // ---------- coeliac card (phrases for staff) ----------
  let phrases = {};
  async function loadPhrases() {
    try {
      const res = await fetch("phrases.json", { cache: "no-store" });
      if (res.ok) phrases = await res.json();
    } catch (e) { /* offline and never cached: no card */ }
    $("cardLangs").textContent = Object.values(phrases).map((p) => p.language).join(", ") || "none yet";
    if (data) renderCardLaunch();
  }
  function renderCardLaunch() {
    const r = byId(selected);
    let langs = Object.keys(phrases);
    if (r) langs = langs.filter((l) => l === r.language);
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

  // ---------- add a menu (owner only, uploads to inbox/ on GitHub) ----------
  const KEY_KEY = "gf-github-key";
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
      const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = url; });
      const scale = Math.min(1, 2400 / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * scale);
      c.height = Math.round(img.naturalHeight * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      return await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.88));
    } finally { URL.revokeObjectURL(url); }
  }
  async function putFile(path, b64, message) {
    const res = await api("/contents/" + path.split("/").map(encodeURIComponent).join("/"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, content: b64 }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message || "HTTP " + res.status);
  }
  $("uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("upName").value.trim();
    const area = $("upArea").value.trim();
    const files = [...$("upFiles").files];
    const status = $("upStatus");
    if (!name || !area || !files.length) { status.textContent = "Add the restaurant, the city or country, and at least one file."; return; }
    const btn = $("upSend");
    btn.disabled = true;
    const now = new Date();
    const stamp = now.toISOString().slice(0, 16).replace(/:/g, "");
    const folder = "inbox/" + stamp + "-" + slug(name) + "-" + slug(area);
    try {
      let n = 0;
      for (const f of files) {
        n++;
        status.textContent = "Uploading " + n + " of " + files.length + "…";
        const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
        const blob = isPdf ? f : await toJpeg(f);
        const fname = isPdf ? (files.length > 1 ? "menu-" + n + ".pdf" : "menu.pdf") : "page-" + n + ".jpg";
        await putFile(folder + "/" + fname, await toB64(blob), "Upload " + name + " menu (" + fname + ")");
      }
      const meta = { restaurant: name, area, notes: $("upNotes").value.trim(), files: files.length, uploadedAt: now.toISOString(), uploadedFrom: "GF Menus app" };
      await putFile(folder + "/upload.json", btoa(unescape(encodeURIComponent(JSON.stringify(meta, null, 2)))), "Upload " + name + " menu details");
      status.textContent = "Uploaded. It'll be scanned within a day and sent to GitHub for you to approve.";
      $("uploadForm").reset();
      toast("Menu uploaded");
    } catch (err) {
      status.textContent = "Upload failed: " + err.message + ". Nothing was lost; try again with signal.";
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
    btn.classList.add("spin");
    try {
      const idx = await getJSON("data/restaurants.json");
      const full = await Promise.all(idx.json.restaurants.map((r) => getJSON(r.file)));
      const offline = idx.offline || full.some((f) => f.offline);
      const fresh = { built: idx.json.built, restaurants: full.map((f) => f.json) };
      const prev = data;
      const changed = !prev || prev.built !== fresh.built;
      if (changed) {
        data = fresh;
        store.set(DATA_KEY, JSON.stringify(fresh));
        render();
      }
      if (offline) {
        if (manual) toast("No connection. Showing the menus saved on this phone.");
      } else if (prev) {
        const news = fresh.restaurants.filter((r) => {
          const old = prev.restaurants.find((o) => o.id === r.id);
          return !old || old.source !== r.source;
        });
        if (news.length) toast("New: " + news.map((r) => r.name + (r.guide && r.guide.title ? " (" + r.guide.title + ")" : "")).join(", "));
        else if (manual) toast(changed ? "Menus refreshed" : "You have the latest menus");
      }
    } catch (e) {
      if (data) {
        if (manual) toast("No connection. Showing the menus saved on this phone.");
      } else {
        $("guideLine").textContent = "Couldn't load menus";
        $("list").innerHTML = '<p class="empty">Couldn\'t load the menus. Check your connection and tap ↻.</p>';
      }
    } finally {
      btn.classList.remove("spin");
    }
  }

  // ---------- events ----------
  $("q").addEventListener("input", () => { if (data) { renderStatus(); renderList(); } });
  $("chips").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || !data) return;
    const f = b.dataset.f;
    if (f.startsWith("r:")) { select(f.slice(2)); return; }
    filter = f;
    renderChips();
    renderStatus();
    renderList();
    window.scrollTo({ top: 0 });
  });
  $("list").addEventListener("click", onFav);
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
    select(b.dataset.r);
  });
  $("infoBtn").addEventListener("click", () => openDialog($("info")));
  ["picker", "info", "gfcard", "warnings"].forEach((id) => $(id).addEventListener("click", (e) => { if (e.target === $(id)) $(id).close(); }));
  $("refreshBtn").addEventListener("click", () => load(true));
  $("shareBtn").addEventListener("click", async () => {
    const r = byId(selected);
    const url = location.origin + location.pathname.replace(/index\.html$/, "") + (r ? "#" + r.id : "");
    const text = r ? "Food and drinks with no gluten ingredients at " + r.name : "Food and drinks with no gluten ingredients at restaurants and coffee shops";
    if (navigator.share) {
      try { await navigator.share({ title: "Twoo's Treat Temple", text, url }); } catch (e) { /* share sheet closed */ }
      return;
    }
    try { await navigator.clipboard.writeText(url); toast("Link copied"); } catch (e) { toast(url); }
  });
  window.addEventListener("hashchange", () => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (data && id && byId(id) && id !== selected) select(id);
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
  $("installClose").addEventListener("click", () => { $("installTip").hidden = true; store.set(TIP_KEY, "1"); });

  // ---------- start ----------
  const hashId = decodeURIComponent(location.hash.slice(1));
  selected = hashId || store.get(SEL_KEY) || ALL;
  const saved = store.get(DATA_KEY);
  if (saved) {
    try { data = JSON.parse(saved); render(); } catch (e) { data = null; }
  }
  loadPhrases();
  load(false).then(() => {
    // first visit: one restaurant opens directly; several, the picker opens so you start somewhere specific
    if (data && !hashId && !store.get(SEL_KEY)) {
      if (data.restaurants.length === 1) select(data.restaurants[0].id);
      else { renderPicker(); openDialog($("picker")); }
    }
  });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(false); });
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
})();
