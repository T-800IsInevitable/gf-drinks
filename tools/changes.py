"""
Work out what changed between the menu that is live now and the one just built.

The publish workflow downloads the live data (tools/fetch_previous.py) before
building. When a restaurant's guide has changed, build.py stores the result of
compare() in that restaurant's data as "changes"; when the guide is the same,
the live "changes" are carried forward, so they stay visible until the next
guide arrives.

Items are matched by section and name, then by name alone (sections are
sometimes renamed between editions).
"""
from datetime import date


def _norm(s):
    return " ".join((s or "").lower().split())


def _how(i):
    """The parts of an item that affect how it's ordered."""
    return {k: i.get(k) for k in ("order", "ok", "not", "note") if i.get(k)}


def _brief(i, **extra):
    return {"name": i["name"], "section": i["section"], **extra}


def _index(items):
    by_key, by_name = {}, {}
    for i in items:
        by_key[(i["section"], _norm(i["name"]))] = i
        by_name.setdefault(_norm(i["name"]), []).append(i)
    return by_key, by_name


def _find(i, index):
    by_key, by_name = index
    hit = by_key.get((i["section"], _norm(i["name"])))
    if hit:
        return hit
    same = by_name.get(_norm(i["name"]), [])
    return same[0] if len(same) == 1 else None


def guide_label(d):
    g = d.get("guide") or {}
    return g.get("title") or (f"guide of {g['version']}" if g.get("version") else d.get("source"))


def compare(prev, new, today=None):
    """Changes from prev (the live data) to new (just built). None if there's nothing to compare with."""
    if not prev:
        return None
    if prev.get("source") == new.get("source"):
        return prev.get("changes")
    old_ok, old_avoid = _index(prev.get("items", [])), _index(prev.get("avoid", []))
    new_ok, new_avoid = _index(new.get("items", [])), _index(new.get("avoid", []))
    out = {"since": guide_label(prev), "sinceSource": prev.get("source"), "date": (today or date.today()).isoformat(),
           "nowAvoid": [], "nowOk": [], "changed": [], "added": [], "removed": [], "newAvoid": 0}
    for i in new.get("items", []):
        was = _find(i, old_ok)
        if was:
            if _how(was) != _how(i):
                out["changed"].append(_brief(i, was=_how(was), now=_how(i)))
        elif _find(i, old_avoid):
            out["nowOk"].append(_brief(i))
        else:
            out["added"].append(_brief(i))
    for a in new.get("avoid", []):
        if _find(a, old_ok):
            out["nowAvoid"].append(_brief(a, gluten=a.get("gluten", [])))
        elif not _find(a, old_avoid):
            out["newAvoid"] += 1
    for i in prev.get("items", []):
        if not _find(i, new_ok) and not _find(i, new_avoid):
            out["removed"].append(_brief(i))
    return out


def summary(c):
    if not c:
        return "no earlier version to compare with"
    parts = [f"{len(c[k])} {label}" for k, label in (("nowAvoid", "now to avoid"), ("nowOk", "no longer to avoid"),
                                                       ("changed", "ordered differently"), ("added", "new"),
                                                       ("removed", "gone")) if c[k]]
    return f"since {c['since']}: " + (", ".join(parts) if parts else "no changes to the items")
