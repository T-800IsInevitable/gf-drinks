"""
Pull a guide's own warnings out of its text, word for word, with page numbers.

Used by the PDF readers so the app's Warnings page always reflects the guide
it was built from: cross-contact statements, allergen updates, recipe and
availability caveats, delivery notes and nutrition advice.
"""
import re
from difflib import SequenceMatcher

KINDS = [
    # a guide's own gluten free claim (e.g. Coeliac UK accreditation); the app shows it word for word
    ("accreditation", r"coeliac uk|accredited|20 ?ppm|parts per million"),
    ("update", r"allergen update|now contains"),
    ("delivery", r"deliver|courier"),
    ("diet", r"vegan|not suitable for those"),
    ("cross-contact", r"cross[- ]contact|cross[- ]contamination|shared equipment|cannot guarantee|can.t guarantee|"
                      r"allergen-free|free from any allergen|traces|may contain|handled by|"
                      r"not suitable for this allergen|preparation methods|cooking methods|human error|not free from"),
    ("recipes", r"recipe|formulation|variations may occur|differ shop to shop|ingredient label|working on our"),
    ("coverage", r"branded products|not be available|only covers|do not see a product|not see a product|not all ingredients|"
                 r"participating locations|not available in|halal"),
    ("nutrition", r"kcal|calorie"),
]
LABELS = {
    "accreditation": "Accreditation",
    "update": "Allergen updates",
    "cross-contact": "Cross-contact",
    "recipes": "Recipes and ingredients",
    "coverage": "What the guide covers",
    "delivery": "Delivery",
    "diet": "Vegan and dietary labels",
    "nutrition": "Nutrition",
}


def _clean(s):
    s = re.sub(r"[​-‍﻿]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace(" .help", " help").replace(" ,", ",")


def _sentences(text):
    text = re.sub(r"(kcal a day)\s*\n", r"\1.\n", text or "")  # footer line with no full stop
    text = _clean(text)
    text = re.sub(r"^(Introduction|Cross-Contact)\s+", "", text)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", text)]
    out = []
    for p in parts:
        p = re.sub(r"^(Introduction|Cross-Contact)\s+", "", p)
        if "•" in p or len(p) < 25:
            continue
        # keep follow-on sentences ("In these sites…", "This…") with the sentence they refer to
        if out and re.match(r"(In these|These) sites\b", p):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def _kind(sentence):
    low = sentence.lower()
    for kind, pat in KINDS:
        if re.search(pat, low):
            return kind
    return None


def collect(pdf, pages, columns_for=(), regions=None):
    """pages: 1-based page numbers to read. columns_for: pages laid out in two columns.
    regions: {page: [bbox, …]} to read only parts of a page (e.g. a table page's header and footer)."""
    found = []
    regions = regions or {}
    for pno in sorted(set(pages) | set(regions)):
        page = pdf.pages[pno - 1]
        if pno in regions:
            texts = [page.crop(b).extract_text() or "" for b in regions[pno]]
        elif pno in columns_for:
            w = page.width
            texts = [page.crop((0, 0, w / 2, page.height)).extract_text() or "",
                     page.crop((w / 2, 0, w, page.height)).extract_text() or ""]
        else:
            texts = [page.extract_text() or ""]
        for t in texts:
            for s in _sentences(t):
                k = _kind(s)
                if k:
                    found.append({"kind": k, "text": s, "page": pno})
    # drop near-duplicates (the same disclaimer repeated on every page), keep the first page it appears on
    out = []
    for n in found:
        dup = next((o for o in out if SequenceMatcher(None, o["text"].lower(), n["text"].lower()).ratio() > 0.85), None)
        if dup:
            if n["page"] not in dup["pages"]:
                dup["pages"].append(n["page"])
            continue
        out.append({"kind": n["kind"], "label": LABELS[n["kind"]], "text": n["text"], "pages": [n["page"]]})
    for o in out:  # a disclaimer repeated on every page: keep the first few page numbers
        o["pagesTotal"] = len(o["pages"])
        o["pages"] = o["pages"][:3]
    order = [k for k, _ in KINDS]
    out.sort(key=lambda n: (order.index(n["kind"]), n["pages"][0]))
    return out
