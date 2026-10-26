// What changed between two copies of one restaurant's menu: a line-for-line port of compare() in tools/changes.py,
// so the phone can compare the menu it last showed you with the newest one, however many guides came out in between.
// tests/test_changes_js.py runs both on a real pair of guides and on made-up older versions of every menu and requires
// the same answer, so change the two together.
(function (root) {
  "use strict";

  // " ".join((s or "").lower().split()): split on exactly the characters Python's str.split() treats as spaces
  const SPACE = /[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/;
  const norm = (s) => String(s || "").toLowerCase().split(SPACE).filter(Boolean).join(" ");
  // Python's "if i.get(k)": an empty list or string counts as missing
  const present = (v) => (Array.isArray(v) ? v.length > 0 : !!v);

  // the parts of an item that affect how it's ordered
  function how(i) {
    const out = {};
    for (const k of ["order", "ok", "not", "note"]) if (present(i[k])) out[k] = i[k];
    return out;
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b); // keys always in the order how() writes them

  function brief(i, extra) {
    return Object.assign({ name: i.name, section: i.section }, extra || {});
  }

  function index(items) {
    const byKey = new Map();
    const byName = new Map();
    for (const i of items) {
      byKey.set(i.section + "\u0000" + norm(i.name), i); // the last of two identical keys wins, as in a Python dict
      const n = norm(i.name);
      if (!byName.has(n)) byName.set(n, []);
      byName.get(n).push(i);
    }
    return { byKey, byName };
  }

  // by section and name, then by name alone when only one item has it (sections are sometimes renamed)
  function find(i, ix) {
    const hit = ix.byKey.get(i.section + "\u0000" + norm(i.name));
    if (hit) return hit;
    const named = ix.byName.get(norm(i.name)) || [];
    return named.length === 1 ? named[0] : null;
  }

  function guideLabel(d) {
    const g = d.guide || {};
    return g.title || (g.version ? "guide of " + g.version : d.source);
  }

  function localDate() {
    const d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  // Changes from prev (the older copy) to next (the newer). null if there's nothing to compare with.
  function compare(prev, next, today) {
    if (!prev) return null;
    if (prev.source === next.source) return prev.changes === undefined ? null : prev.changes;
    const oldOk = index(prev.items || []), oldAvoid = index(prev.avoid || []);
    const newOk = index(next.items || []), newAvoid = index(next.avoid || []);
    const out = { since: guideLabel(prev), sinceSource: prev.source, date: today || localDate(),
      nowAvoid: [], nowOk: [], changed: [], added: [], removed: [], newAvoid: 0 };
    for (const i of next.items || []) {
      const was = find(i, oldOk);
      if (was) {
        if (!same(how(was), how(i))) out.changed.push(brief(i, { was: how(was), now: how(i) }));
      } else if (find(i, oldAvoid)) {
        out.nowOk.push(brief(i));
      } else {
        out.added.push(brief(i));
      }
    }
    for (const a of next.avoid || []) {
      if (find(a, oldOk)) out.nowAvoid.push(brief(a, { gluten: "gluten" in a ? a.gluten : [] }));
      else if (!find(a, oldAvoid)) out.newAvoid += 1;
    }
    for (const i of prev.items || []) {
      if (!find(i, newOk) && !find(i, newAvoid)) out.removed.push(brief(i));
    }
    return out;
  }

  root.gfCompare = compare;
  if (typeof module !== "undefined" && module.exports) module.exports = compare;
})(typeof self !== "undefined" ? self : globalThis);
