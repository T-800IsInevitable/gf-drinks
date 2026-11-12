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
# as malt or malted, so maltodextrin and maltitol stay out, as before
CEREALS = "wheat|rye|barley|oat|spelt|kamut|khorasan|durum|semolina|couscous|bulgur|bulghur|triticale|einkorn|emmer|farro|freekeh|seitan"
CEREAL_WORDS = rf"(?:{CEREALS})\w*|malt(?:ed)?|gluten(?![\s-]*free)"
CEREAL = re.compile(rf"\b({CEREAL_WORDS})\b", re.I)
CEREAL_CAPS = re.compile(rf"\b((?:{CEREALS.upper()})\w*|MALT(?:ED)?|GLUTEN(?![\s-]*FREE))\b")
MONTHS = {name: n for n, name in enumerate(calendar.month_name) if name}  # "January" -> 1
INVISIBLE = re.compile("[​-‍﻿]")  # zero-width characters some guides carry


def clean(s):
    """One space between words, no invisible characters, nothing at the ends."""
    return re.sub(r"\s+", " ", INVISIBLE.sub("", s or "")).strip()


def cereal_code(word):
    """A cereal as the app records it: 'oats', 'OATMEAL' and 'Oatly' are OAT; 'WHEATFLOUR' is WHEAT; 'malted' is MALT."""
    w = word.upper()
    # the codes stay the ones the app knows: wheat's other names are WHEAT, khorasan is KAMUT
    for head, code in (("OAT", "OAT"), ("WHEAT", "WHEAT"), ("MALT", "MALT"), ("RYE", "RYE"), ("BARLEY", "BARLEY"),
                       ("SPELT", "SPELT"), ("KAMUT", "KAMUT"), ("KHORASAN", "KAMUT"), ("GLUTEN", "GLUTEN"),
                       *((h, "WHEAT") for h in ("DURUM", "SEMOLINA", "COUSCOUS", "BULGUR", "BULGHUR", "TRITICALE",
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
    """The guide in folder to build from: the newest by the version its own text gives (version_of(pdf, path)),
    then by file time. keep(pdf) can rule a file out (another guide that shares the folder)."""
    dated = []
    for p in sorted(Path(folder).glob(pattern)):
        with pdfplumber.open(p) as pdf:
            if keep is not None and not keep(pdf):
                continue
            v = version_of(pdf, p) or "0000-00-00"
        dated.append((v, p.stat().st_mtime, p))
    if not dated:
        raise SystemExit(f"ERROR: no guide PDF found in {folder}")
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} ({what} {v})")
    return dated[-1][2]


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
