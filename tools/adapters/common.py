"""
What every reader shares: the gluten words, text tidying, picking the newest guide, and the shape of a built menu.

The cereal pattern is the union of every list the readers used to keep for themselves, so no reader is narrower
than another (CLAUDE.md: gluten = wheat, rye, barley, oats, spelt, kamut, or "gluten"/malt). CEREAL finds them
in prose, case blind, leaving "gluten free" alone; CEREAL_CAPS finds them written in capitals, which is how the
Starbucks, Five Guys and Blank Street guides mark allergens in an ingredient list.
"""
import calendar
import re
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

# each cereal with whatever is run on to it (OATMILK, RYEFLOUR, BARLEYMALT), plus wheat by its other names; malt only
# in the forms that mean the grain (malt, malts, malted, malty, malting, Maltesers), so maltodextrin, maltitol and
# maltose stay out, as before
CEREALS = "wheat|rye|barley|oat|spelt|kamut|khorasan|durum|semolina|couscous|bulgur|bulghur|bulgar|triticale|einkorn|emmer|farro|freekeh|seitan"
# "whole" can run on in front ("Wholewheat"); the cereal must start the word otherwise, so buckwheat and goat stay out
CEREAL_WORDS = rf"(?:whole)?(?:{CEREALS})\w*|malt(?:s|ed|y|ing|esers?)?|gluten(?![\s-]*free)"
CEREAL = re.compile(rf"\b({CEREAL_WORDS})\b", re.I)
CEREAL_CAPS = re.compile(rf"\b((?:WHOLE)?(?:{CEREALS.upper()})\w*|MALT(?:S|ED|Y|ING|ESERS?)?|GLUTEN(?![\s-]*FREE))\b")
MONTHS = {name: n for n, name in enumerate(calendar.month_name) if name}  # "January" -> 1
INVISIBLE = re.compile("[​-‍﻿]")  # zero-width characters some guides carry


def clean(s):
    """One space between words, no invisible characters, nothing at the ends."""
    return re.sub(r"\s+", " ", INVISIBLE.sub("", s or "")).strip()


def cereal_code(word):
    """A cereal as the app records it: 'oats', 'OATMEAL' and 'Oatly' are OAT; 'WHEATFLOUR' is WHEAT; 'malted' is MALT."""
    w = re.sub(r"^WHOLE(?=[A-Z])", "", word.upper())  # 'Wholewheat' is WHEAT
    # the codes stay the ones the app knows: wheat's other names are WHEAT, khorasan is KAMUT
    for head, code in (("OAT", "OAT"), ("WHEAT", "WHEAT"), ("MALT", "MALT"), ("RYE", "RYE"), ("BARLEY", "BARLEY"),
                       ("SPELT", "SPELT"), ("KAMUT", "KAMUT"), ("KHORASAN", "KAMUT"), ("GLUTEN", "GLUTEN"),
                       *((h, "WHEAT") for h in ("DURUM", "SEMOLINA", "COUSCOUS", "BULGUR", "BULGHUR", "BULGAR", "TRITICALE",
                                                "EINKORN", "EMMER", "FARRO", "FREEKEH", "SEITAN"))):
        if w.startswith(head):
            return code
    return w


def cereal_word(code):
    """A code back as a word for a sentence: OAT -> 'oats'."""
    return "oats" if code == "OAT" else code.lower()


def valid_until(version, config, default_days=91):
    """When a guide with no end date of its own should be looked at again: its version date plus recheckDays."""
    if not version:
        return None
    return (date.fromisoformat(version) + timedelta(days=int(config.get("recheckDays", default_days)))).isoformat()


def newest_by(folder, version_of, keep=None, what="version", pattern="*.pdf"):
    """The guide in folder to build from: the newest by the version its own text gives (version_of(pdf, path)).
    keep(pdf) can rule a file out (another guide that shares the folder). Never decided by file time or by guessing:
    with more than one guide to choose from, the build stops when one has no readable version (it would silently lose
    to an older guide) or when two share the newest version."""
    dated = []
    for p in sorted(Path(folder).glob(pattern)):
        with pdfplumber.open(p) as pdf:
            if keep is not None and not keep(pdf):
                continue
            v = version_of(pdf, p) or "0000-00-00"
        dated.append((v, p.name, p))
    if not dated:
        raise SystemExit(f"ERROR: no guide PDF found in {folder}")
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} ({what} {v})")
    if len(dated) > 1:
        unread = [name for v, name, _ in dated if v == "0000-00-00"]
        if unread:
            raise SystemExit(f"ERROR: {', '.join(unread)}: couldn't read its date, so the newest guide in {folder} can't be "
                             "told. Remove the old guide or fix the reader. Menu not updated.")
        if dated[-1][0] == dated[-2][0]:
            raise SystemExit(f"ERROR: {dated[-2][1]} and {dated[-1][1]} both read as {what} {dated[-1][0]}, so the newest "
                             f"guide in {folder} can't be told. Remove the older one. Menu not updated.")
    return dated[-1][2]


ORDER_FIELDS = ("order", "ok", "not", "standard", "standardFrom", "note")


def one_of_each(ok, avoid, warnings):
    """The same item twice in a section (name in any case): keep one copy. A copy with no gluten never hides one that
    names it, and two listed copies that say to order it differently go on the Avoid list to check in store: no merge
    of two sets of instructions is safe (one copy's fine milk can be the other's gluten one)."""
    key = lambda i: (i["section"], i["name"].lower())
    says = lambda i: [sorted(v) if isinstance(v, list) else v for v in (i.get(f) for f in ORDER_FIELDS)]
    gluten = {key(a) for a in avoid}
    seen, listed, unsure = {}, [], {}
    for i in ok:
        k = key(i)
        if k in gluten:
            warnings.append(f"{i['name']}: listed twice in {i['section']}, once naming gluten; put on the Avoid list")
        elif k in unsure:
            pass
        elif k not in seen:
            seen[k] = i
            listed.append(i)
        elif says(i) != says(seen[k]):
            warnings.append(f"{i['name']}: listed twice in {i['section']}, ordered differently; put on the Avoid list")
            listed.remove(seen[k])
            unsure[k] = {**{f: v for f, v in seen[k].items() if f not in ORDER_FIELDS + ("decided", "info", "role")},
                         "gluten": [], "tag": "Check in store",
                         "reason": "Note from this app: the guide lists this twice with different ways to order it, so check in store."}
        else:
            warnings.append(f"{i['name']}: listed twice in {i['section']}; kept the first")
    seen, kept = {}, []
    for a in avoid + list(unsure.values()):
        k = key(a)
        if k not in seen:
            seen[k] = dict(a)
            kept.append(seen[k])
            continue
        # the copy kept names every cereal either copy names, says both reasons, and drops a tag they disagree on
        warnings.append(f"{a['name']}: listed twice in {a['section']}; Avoid copies merged")
        s = seen[k]
        # a copy with no reason says what the app would show for it (avoidWhy), so the other's can't stand alone
        why = lambda x: x.get("reason") or ("Every version contains " + " and ".join(x["gluten"]).lower() + "."
                                            if x.get("gluten") else "The guide lists gluten.")
        if why(a) != why(s):
            s["reason"] = why(s) + " " + why(a)
        s["gluten"] = sorted(set(s.get("gluten") or []) | set(a.get("gluten") or []))
        if s.get("tag") != a.get("tag"):
            s.pop("tag", None)
    return listed, kept


def result(source, guide, rule, items, avoid, warnings, notices=(), rows=None, sections=None):
    """A built menu, as build.py expects it from every reader."""
    return {
        "notices": list(notices),
        "source": source,
        "guide": guide,
        "rule": rule,
        "sections": sections if sections is not None else list(dict.fromkeys(i["section"] for i in items + avoid)),
        "items": items,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": rows if rows is not None else len(items) + len(avoid), "items": len(items), "avoid": len(avoid)},
    }
