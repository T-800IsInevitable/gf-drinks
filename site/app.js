(() => {
  "use strict";
  const STORE_KEY = "gf-menu-v1";
  const TIP_KEY = "gf-install-tip-dismissed";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };

  let menu = null;
  let section = "All";

  // Shorter chip labels for the guide's long section names.
  function shortSection(s) {
    const map = {
      "Iced Teas & Starbucks Refresha® Drink": "Iced Teas & Refreshas",
      "Frappuccino® Blended Beverage": "Frappuccino",
      "Syrups, Drizzles & Cream Cold Foams": "Syrups & toppings",
      "Protein Beverages": "Protein",
    };
    return map[s] || s.replace(/®/g, "");
  }
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
    return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  function listMilks(arr) {
    if (arr.length < 2) return arr.join("");
    return arr.slice(0, -1).join(", ") + " or " + arr[arr.length - 1];
  }
  function tagFor(d) {
    switch (d.order) {
      case "asis": return ["t-asis", "As listed"];
      case "any": return ["t-any", "Any milk"];
      case "swap": return ["t-swap", "Swap milk"];
      default: return ["t-any", "Any milk except " + d.notMilks.join(", ")];
    }
  }
  const pageText = (p) => (p.length > 1 ? "Guide pages " : "Guide page ") + p.join(", ");
  const chev = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function detailFor(d) {
    const parts = [];
    if (d.order === "asis") {
      parts.push("<div>Gluten free as listed. No changes needed.</div>");
    } else {
      if (d.order === "swap") {
        parts.push(d.standardFrom === "guide"
          ? "<div><b>Comes with oat drink as standard.</b> Ask for " + esc(listMilks(d.okMilks)) + ".</div>"
          : "<div><b>Usually made with oat drink</b> (going by its name). Ask for " + esc(listMilks(d.okMilks)) + ".</div>");
      }
      parts.push('<div class="milks">' + d.okMilks.map((m) => '<span class="milk">' + esc(m) + "</span>").join("") +
        d.notMilks.map((m) => '<span class="milk no" aria-label="not ' + esc(m) + '">' + esc(m) + "</span>").join("") + "</div>");
    }
    parts.push("<div>" + pageText(d.pages) + "</div>");
    return parts.join("");
  }

  function matches(d, q) {
    return !q || (d.name + " " + (d.sub || "")).toLowerCase().includes(q);
  }

  function renderChips() {
    const secs = ["All", ...menu.sections.filter((s) => menu.drinks.some((d) => d.section === s))];
    if (!secs.includes(section)) section = "All";
    $("chips").innerHTML = secs.map((s) =>
      '<button type="button" data-s="' + esc(s) + '" aria-pressed="' + (s === section) + '">' + esc(s === "All" ? "All" : shortSection(s)) + "</button>").join("");
  }

  function renderList() {
    const q = $("q").value.trim().toLowerCase();
    let html = "";
    let shown = 0;
    for (const s of menu.sections) {
      if (section !== "All" && section !== s) continue;
      const items = menu.drinks.filter((d) => d.section === s && matches(d, q));
      if (!items.length) continue;
      shown += items.length;
      html += '<h2 class="group-h">' + esc(shortSection(s)) + "<small>" + items.length + "</small></h2>";
      // One card per sub-heading (e.g. Reserve: Cold coffee / Hot coffee)
      let i = 0;
      while (i < items.length) {
        const sub = items[i].sub || "";
        let card = "";
        while (i < items.length && (items[i].sub || "") === sub) {
          const d = items[i++];
          const [cls, label] = tagFor(d);
          card += '<details class="row"><summary><span class="nm">' + esc(d.name) + '</span><span class="tag ' + cls + '">' +
            esc(label) + "</span>" + chev + '</summary><div class="detail">' + detailFor(d) + "</div></details>";
        }
        if (sub) html += '<div class="sub-h">' + esc(sub.toLowerCase().replace(/^\w/, (c) => c.toUpperCase())) + "</div>";
        html += '<div class="card">' + card + "</div>";
      }
    }
    $("list").innerHTML = html || '<p class="empty">No gluten free drink matches "' + esc(q) + '". Check the list below.</p>';

    const avoid = menu.avoid.filter((d) => (section === "All" || d.section === section) && matches(d, q));
    $("avoidWrap").hidden = !avoid.length;
    $("avoid").innerHTML = avoid.length ? '<div class="card">' + avoid.map((d) =>
      '<details class="row"><summary><span class="nm">' + esc(d.name) + '</span><span class="tag t-bad">' +
      esc(d.gluten.map((g) => g.charAt(0) + g.slice(1).toLowerCase()).join(" & ")) + "</span>" + chev +
      '</summary><div class="detail"><div>Every version contains ' + esc(d.gluten.join(" and ").toLowerCase()) +
      ".</div><div>" + pageText(d.pages) + "</div></div></details>").join("") + "</div>" : "";
    return shown;
  }

  function renderMeta() {
    const g = menu.guide || {};
    const season = (g.title || "").replace(/\s*Beverages$/, "");
    const runs = (g.runs || "").replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*/g, "$1");
    $("guideLine").textContent = [season ? season + " menu" : "Current menu", runs].filter(Boolean).join(" · ");
    const src = "Built from Starbucks UK allergen guide " + (menu.source || "") +
      (g.version ? " (version " + fmtDate(g.version) + ")" : "") + " on " + fmtDate(menu.built) + ".";
    $("sourceLine").textContent = src;
    $("infoSource").textContent = src + " " + menu.stats.drinks + " gluten free drinks and add-ons, " + menu.stats.avoid + " to avoid.";
    $("ruleLine").textContent = menu.rule + " Both the allergen column and the ingredient list are checked; if they disagree, the drink is left out.";
    $("notesWrap").hidden = !(menu.warnings && menu.warnings.length);
    $("notes").innerHTML = (menu.warnings || []).map((w) => "<li>" + esc(w) + "</li>").join("");
  }

  function render() {
    renderMeta();
    renderChips();
    renderList();
  }

  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
  }

  async function load(manual) {
    const btn = $("refreshBtn");
    btn.classList.add("spin");
    try {
      const res = await fetch("data/menu.json", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const offline = res.headers.get("X-GF-Offline") === "1";
      const fresh = await res.json();
      const prev = menu;
      const changed = !prev || prev.built !== fresh.built;
      if (changed) {
        menu = fresh;
        store.set(STORE_KEY, JSON.stringify(fresh));
        render();
      }
      if (offline) {
        if (manual) toast("No connection. Showing the menu saved on this phone.");
      } else if (prev && prev.source !== fresh.source) {
        toast("New menu loaded: " + ((fresh.guide && fresh.guide.title) || fresh.source));
      } else if (manual) {
        toast(changed ? "Menu refreshed" : "You have the latest menu");
      }
    } catch (e) {
      if (menu) {
        if (manual) toast("No connection. Showing the menu saved on this phone.");
      } else {
        $("guideLine").textContent = "Couldn't load the menu";
        $("list").innerHTML = '<p class="empty">Couldn\'t load the menu. Check your connection and tap ↻.</p>';
      }
    } finally {
      btn.classList.remove("spin");
    }
  }

  // Events
  $("q").addEventListener("input", () => menu && renderList());
  $("chips").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || !menu) return;
    section = b.dataset.s;
    renderChips();
    renderList();
    window.scrollTo({ top: 0 });
  });
  $("refreshBtn").addEventListener("click", () => load(true));
  $("infoBtn").addEventListener("click", () => {
    const dlg = $("info");
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  });
  $("info").addEventListener("click", (e) => { if (e.target === $("info")) $("info").close(); });
  $("shareBtn").addEventListener("click", async () => {
    const url = location.href.split("#")[0].replace(/index\.html$/, "");
    const data = { title: "GF Drinks", text: "Gluten free drinks from the current Starbucks UK allergen guide", url };
    if (navigator.share) {
      try { await navigator.share(data); } catch (e) { /* share sheet closed */ }
      return;
    }
    try { await navigator.clipboard.writeText(url); toast("Link copied"); } catch (e) { toast(url); }
  });

  // Install tip: iPhone/iPad in Safari, not yet on the Home Screen.
  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
  if (isIOS && !standalone && store.get(TIP_KEY) !== "1") $("installTip").hidden = false;
  $("installClose").addEventListener("click", () => { $("installTip").hidden = true; store.set(TIP_KEY, "1"); });

  // Start: show the saved menu instantly, then check for a newer one.
  const saved = store.get(STORE_KEY);
  if (saved) {
    try { menu = JSON.parse(saved); render(); } catch (e) { menu = null; }
  }
  load(false);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(false); });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
})();
