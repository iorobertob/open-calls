"""Data for the TV page (the home page): open calls, a series shown once (its next call), by field.

The page itself (templates/tv.html + static/tv.js) draws a picture for every card from the card's
type and text, so new calls get their own illustration automatically and the same call always
looks the same."""
from datetime import date

from flask import url_for

from .models import Call, RefreshRun
from .taxonomy import KINDS, tax

LIVE = ("due_today", "closing_soon", "open", "rolling")

# The illustration motifs exist for these six types; the others borrow the closest one.
# (Kept identical to the old /screen mapping, so existing calls keep their pictures.)
VISUAL_KIND = {"journal": "conference", "works": "competition", "grant": "mobility", "other": "competition"}

MONTHS_LT = ["sausio", "vasario", "kovo", "balandžio", "gegužės", "birželio", "liepos", "rugpjūčio",
             "rugsėjo", "spalio", "lapkričio", "gruodžio"]


def _primary_field(c, t):
    order = [f.key for f in t.fields]
    keys = [k for k in c.field_list if k in order]
    if keys:
        return min(keys, key=order.index)
    return order[0] if order else ""


def _item(c, t, series=None, n=1):
    kind = KINDS.get(c.kind, KINDS["other"])
    disc, fmts = t.split_topics(c.topic_list)
    item = {
        "kind": VISUAL_KIND.get(c.kind, c.kind if c.kind in KINDS else "competition"),
        "kindLt": kind["short_lt"], "kindEn": kind["short_en"],
        "field": _primary_field(c, t),
        "titleLt": c.title("lt"), "titleEn": c.title("en"),
        "cityLt": c.city("lt"), "cityEn": c.city("en"),
        "countryLt": c.country("lt"), "countryEn": c.country("en"),
        "countryCode": c.country_code or "",
        "deadline": c.deadline.isoformat() if c.deadline else "",
        "deadlineWordLt": c.deadline_word("lt"), "deadlineWordEn": c.deadline_word("en"),
        "descLt": c.desc("lt"), "descEn": c.desc("en"),
        "topics": [{"lt": t.label(k, "lt"), "en": t.label(k, "en")} for k in (disc + fmts)[:4]],
        "url": c.url or url_for("main.detail", call_id=c.id, _external=True),
        "series": None,
    }
    if series:
        item["series"] = {"lt": series.name("lt"), "en": series.name("en"), "n": n}
        # one scan shows every call of the series
        item["url"] = url_for("main.series_page", series_id=series.id, _external=True)
    return item


def tv_data():
    t = tax()
    calls = [c for c in Call.query.filter_by(status="open").all()
             if not c.is_placeholder and c.phase() in LIVE]
    by_series, items = {}, []
    for c in calls:
        s = c.series
        if s and not s.is_aggregator:
            by_series.setdefault(s.id, (s, []))[1].append(c)
        else:
            items.append(_item(c, t))
    for s, cs in by_series.values():
        lead = min(cs, key=lambda c: (c.deadline or date.max, c.id))
        items.append(_item(lead, t, series=s, n=len(cs)))

    counts = {}
    for it in items:
        counts[it["field"]] = counts.get(it["field"], 0) + 1
    fields = [{"key": f.key, "lt": f.name("lt"), "en": f.name("en"), "hue": f.hue, "n": counts.get(f.key, 0)}
              for f in t.fields]

    run = RefreshRun.query.filter(RefreshRun.finished_at.isnot(None)).order_by(RefreshRun.finished_at.desc()).first()
    d = run.finished_at.date() if run else date.today()
    return {
        "config": {
            "slideSeconds": 22, "perPage": 4, "urgentDays": 14, "today": "",
            "reloadMinutes": 60,
            "updatedLt": f"Atnaujinta {d.year} m. {MONTHS_LT[d.month - 1]} {d.day} d.",
            "updatedEn": f"Updated {d.day} {d.strftime('%B %Y')}",
            "searchUrl": url_for("main.index"),
            "searchUrlFull": url_for("main.index", _external=True),
            "siteLabel": url_for("main.tv", _external=True).split("://", 1)[-1].rstrip("/"),
            "logo": url_for("static", filename="misc-logo.png"),
        },
        "fields": fields,
        "items": items,
    }
