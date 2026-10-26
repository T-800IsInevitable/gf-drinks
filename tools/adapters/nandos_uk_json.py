#!/usr/bin/env python3
"""
Reader for Nando's UK allergen information, from the snapshot tools/fetch_nandos.py saves in guides/
(nandos-allergens-<date>.json): each dish's table of the 14 allergens (Contains, May Contain, Nando's own notes),
its category on the site, and its ingredients.

For each dish:
  * gluten under Contains: Avoid, with Nando's note ("Pitta bread contains gluten from wheat")
  * gluten under May Contain: Avoid, as may contain gluten
  * no gluten marked, but the ingredients name wheat, rye, barley, oats, spelt, kamut or malt: Avoid, because the
    two disagree
  * otherwise: no gluten ingredients
Nando's sets no end date; the app asks for a new snapshot after recheckDays.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

CEREAL = re.compile(r"\b(wheat\w*|rye|barley|oats?|oatmeal|spelt|kamut|malt(?:ed)?)\b", re.I)
MIN_DISHES = 80
# words that make a title part a label about where or when a dish is sold, not its name
LABEL = re.compile(r"select restaurants|gatwick|airport|updated|new recipe|availab|avalible|halal", re.I)


def quoted(text, lead="Nando's says"):
    """'Nando's says: "A." It also says: "B."' (every sentence its own attribution)."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip()) if p.strip()]
    return " ".join((f'{lead}: "{p}"' if n == 0 else f'It also says: "{p}"') for n, p in enumerate(parts))


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("&", "")).strip("-")


def dish_name(d):
    """A dish page's title has two parts, and either can be the name: "Grilled Chicken Pitta" / "Single & double",
    "Only in Gatwick" / "Orange Juice", "BERO" / "Kingston Golden Pils". The page's address names the dish, so it
    decides. Returns the name and the other part (a label or a note), or None."""
    first, second = d.get("name") or "", d.get("variant") or ""
    slug = d.get("slug") or ""
    if not second or slug == slugify(first) or slug.startswith(slugify(first) + "-") and not slugify(second) in slug:
        return first, second or None
    if slug == slugify(first + " " + second):
        return first + " " + second, None
    if slugify(second) and (slug == slugify(second) or slug.startswith(slugify(second)) or slugify(second) in slug
                            or slugify(second).startswith(slug)):
        return second, first
    if LABEL.search(first):  # "Avalible in select restaurants" / "Pink Berry & Tropical Crush" (address: crushes)
        return second, first
    return first, second


def newest_pdf(folder):
    """The newest snapshot (named newest_pdf like the other readers, so the guide watch can ask it)."""
    found = sorted(Path(folder).glob("nandos-allergens-*.json"))
    if not found:
        raise SystemExit(f"ERROR: no Nando's allergen snapshot in {folder}. Run tools/fetch_nandos.py.")
    for p in found:
        print(f"  found {p.name}")
    return found[-1]


def build(folder, config):
    path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {path.name}")
    snap = json.loads(path.read_text(encoding="utf-8"))
    dishes = snap["dishes"]
    if len(dishes) < MIN_DISHES:
        raise SystemExit(f"ERROR: {path.name} has only {len(dishes)} dishes. Menu not updated.")
    warnings, ok, avoid, seen = [], [], [], set()
    for d in dishes:
        if not d.get("name"):
            raise SystemExit(f"ERROR: {d.get('slug')}: no name. Menu not updated.")
        section = d.get("category") or "More"
        name, other = dish_name(d)
        key = (section, name.lower())
        if key in seen:
            raise SystemExit(f"ERROR: {name} is listed twice in {section}. Check the snapshot. Menu not updated.")
        seen.add(key)
        item = {"name": name, "section": section, "sub": None, "pages": []}
        info = [f"Nando's says: \"{other}\"" if other else None]
        note = (d.get("notes") or {}).get("gluten")
        cereals = sorted({c.lower() for c in CEREAL.findall(d.get("ingredients") or "")})
        # the table and the line above it ("Contains gluten, sesame.") are two sources: either one is enough
        said = bool(re.search(r"^Contains\b[^.]*\bgluten\b", d.get("summary") or "", re.I))
        if said != ("gluten" in d["contains"]) and d.get("fullTable"):
            warnings.append(f"{d['name']}: the allergen table and the line above it disagree about gluten; treated as containing gluten")
        if "gluten" in d["contains"] or said:
            reason = quoted(note) if note else "Nando's lists gluten."
            avoid.append({**item, "gluten": [c.upper() for c in cereals] or ["GLUTEN"], "reason": reason,
                          **({"info": " ".join(x for x in info if x)} if any(info) else {})})
        elif "gluten" in d["mayContain"]:
            reason = quoted(note, "Nando's says it may contain gluten") if note else "Nando's says it may contain gluten."
            avoid.append({**item, "gluten": ["GLUTEN"], "reason": reason, "tag": "May contain gluten",
                          **({"info": " ".join(x for x in info if x)} if any(info) else {})})
        elif cereals:
            warnings.append(f"{d['name']}: no gluten marked but the ingredients name {cereals}; treated as containing gluten")
            avoid.append({**item, "gluten": [c.upper() for c in cereals], "reason": "The ingredients name " + " and ".join(cereals) + ".",
                          "decided": "Nando's allergen table marks no gluten but the ingredients name a gluten cereal, so the app treats it "
                                     "as containing gluten."})
        else:
            out = {**item, "order": "asis"}
            extra = [x for x in info if x] + ([quoted(note)] if note else [])
            if extra:
                out["info"] = " ".join(extra)
            ok.append(out)
    fetched = snap["fetched"]
    guide = {"title": "Allergen guide", "runs": None, "version": fetched,
             "validUntil": (date.fromisoformat(fetched) + timedelta(days=int(config.get("recheckDays", 61)))).isoformat()}
    notices = [{"kind": "cross-contact", "label": "Cross-contact", "text": t, "pages": [], "pagesTotal": 0}
               for t in snap.get("notices", []) + [snap.get("important")] if t]
    return {
        "notices": notices,
        "source": path.name,
        "guide": guide,
        "rule": "Nando's: excludes dishes Nando's marks as containing or maybe containing gluten, and any whose ingredients name a "
                "gluten cereal.",
        "sections": list(dict.fromkeys(i["section"] for i in ok + avoid)),
        "items": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(dishes), "items": len(ok), "avoid": len(avoid)},
    }
