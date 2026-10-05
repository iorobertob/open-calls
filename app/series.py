"""Series: recurring sources of calls (journals, conferences, festivals, residency programmes).

Lifecycle of a series with yearly / twice-yearly calls:

    call 2026 (open) ──deadline──▶ closed ──▶ archived
                                     │
                                     └─▶ placeholder "next call — expected around Sept 2027" (Opens soon)
    weekly scan of the series page finds the 2027 call ──▶ new pending call ──admin approves──▶ open
                                                           (placeholder removed, followers e-mailed)
"""
import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import List
from urllib.parse import urlsplit

from flask import current_app
from pydantic import BaseModel

from .duplicates import find_duplicates, norm_title
from .messages import msg
from .models import Call, CallChange, Notification, Series, db, today, utcnow

log = logging.getLogger(__name__)

MONTHS_LT = ["sausio", "vasario", "kovo", "balandžio", "gegužės", "birželio", "liepos", "rugpjūčio",
             "rugsėjo", "spalio", "lapkričio", "gruodžio"]
MONTHS_LT_NOM = ["sausį", "vasarį", "kovą", "balandį", "gegužę", "birželį", "liepą", "rugpjūtį",
                 "rugsėjį", "spalį", "lapkritį", "gruodį"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
INTERVAL = {"yearly": 12, "twice_yearly": 6}


def host(url):
    return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _announced(call):
    """Best guess of when a call was published: first_seen (curator), else created_at."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", call.first_seen or "")
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    return call.created_at.date() if call.created_at else None


def expected_next(series, ref=None):
    """Approximate date (1st of a month) when the next call is expected, or None."""
    months = INTERVAL.get(series.recurrence)
    if not months:
        return None
    ref = ref or today()
    real = [c for c in calls_of(series) if not c.is_placeholder]
    if series.typical_month:
        cand = date(ref.year, series.typical_month, 1)
        while cand < date(ref.year, ref.month, 1):
            cand = _add_months(cand, months)
        return cand
    seen = [d for d in (_announced(c) for c in real) if d]
    if not seen:
        deadlines = [c.deadline for c in real if c.deadline]
        if not deadlines:
            return None
        seen = [max(deadlines) - timedelta(days=90)]
    cand = _add_months(max(seen), months)
    while cand < date(ref.year, ref.month, 1):
        cand = _add_months(cand, months)
    return cand


def calls_of(series):
    """Fresh query (the series.calls relationship can be stale within one run)."""
    return Call.query.filter_by(series_id=series.id).all() if series and series.id else []


def has_live_call(series, include_pending=True):
    states = ("open", "watch", "pending") if include_pending else ("open", "watch")
    return any(c.status in states and not c.is_placeholder and c.phase() != "closed" for c in calls_of(series))


def placeholder_of(series):
    return next((c for c in calls_of(series) if c.is_placeholder and c.status != "archived"), None)


def ensure_placeholder(series):
    """Create the 'expected next call' entry when a recurring series has no live call."""
    if not series.active or has_live_call(series) or placeholder_of(series):
        return None
    when = expected_next(series)
    if not when:
        return None
    last = max((c for c in calls_of(series) if not c.is_placeholder), key=lambda c: c.deadline or date.min, default=None)
    ph = Call(series_id=series.id, is_placeholder=True, status="watch", kind=series.kind or (last.kind if last else "other"),
              title_lt=f"{series.name('lt')} — kitas kvietimas", title_en=f"{series.name('en')} — next call",
              org=series.org or (last.org if last else ""), org_en=(last.org_en if last else ""),
              url=series.url, verified=False, first_seen=today().isoformat(),
              deadline_word_lt=f"Tikimasi apie {when.year} m. {MONTHS_LT_NOM[when.month - 1]}",
              deadline_word_en=f"Expected around {MONTHS_EN[when.month - 1]} {when.year}",
              expires=_add_months(when, 3) - timedelta(days=1),
              desc_lt="Kitas šios serijos kvietimas dar nepaskelbtas. Sekite seriją ir gausite pranešimą, kai jis bus paskelbtas.",
              desc_en="The next call of this series has not been published yet. Follow the series to be notified when it is.",
              source=msg("expected_next"), source_url=series.url)
    if last:
        ph.city_lt, ph.city_en, ph.country_lt, ph.country_en = last.city_lt, last.city_en, last.country_lt, last.country_en
        ph.country_code, ph.topics = last.country_code, last.topics
    db.session.add(ph)
    db.session.flush()
    db.session.add(CallChange(call_id=ph.id, origin="series", note=msg("expected_next")))
    return ph


def retire_placeholder(series):
    ph = placeholder_of(series) if series else None
    if ph:
        db.session.delete(ph)


def link_series(call):
    """Attach a new call to a series automatically when its link is on exactly one series' website."""
    if call.series_id or not call.url:
        return None
    h = host(call.url)
    matches = [s for s in Series.query.filter_by(active=True).all() if s.url and host(s.url) == h]
    if len(matches) == 1:
        call.series_id = matches[0].id
        return matches[0]
    return None


def on_publish(call):
    """Call when a call becomes visible (open / watch). Tells followers once and removes the placeholder."""
    if call.is_placeholder or call.status not in ("open", "watch") or not call.series_id:
        return 0
    series = db.session.get(Series, call.series_id)
    retire_placeholder(series)
    if call.announced_at:
        return 0
    call.announced_at = utcnow()
    n = 0
    for f in series.followers:
        if f.user.email_series:
            db.session.add(Notification(user_id=f.user_id, call_id=call.id, kind="series_new"))
            n += 1
    return n


def notify_change(call, what):
    """Queue 'this call changed' for its subscribers (e.g. a deadline moved)."""
    if call.status not in ("open", "watch") or call.is_placeholder:
        return
    for s in call.subscriptions:
        if s.user.email_reminders:
            db.session.add(Notification(user_id=s.user_id, call_id=call.id, kind="call_changed", detail=what))


# ---------------------------------------------------------------- grouping suggestions

GENERIC_HOSTS = {"docs.google.com", "drive.google.com", "forms.gle", "facebook.com", "instagram.com",
                 "eventbrite.com", "linktr.ee", "mdpi.com", "frontiersin.org", "tandfonline.com",
                 "cambridge.org", "sciencedirect.com", "springer.com", "ieee.org", "wikicfp.com",
                 "easychair.org", "openreview.net", "zenodo.org", "github.io"}


def suggest_groups():
    """Entries without a series, grouped by website — candidates for a series (2+ entries each)."""
    groups = defaultdict(list)
    for c in Call.query.filter(Call.series_id.is_(None), Call.is_placeholder.is_(False)).all():
        h = host(c.url)
        if h and h not in GENERIC_HOSTS:
            groups[h].append(c)
    return sorted(((h, cs) for h, cs in groups.items() if len(cs) >= 2), key=lambda x: -len(x[1]))


def series_name_from(call, lang):
    """'ICMC 2027 — Call for Papers' → 'ICMC' : strip years, editions and the 'call for …' part."""
    t = call.title(lang) or ""
    t = re.split(r"\s[—–-]\s|:\s", t)[0]
    t = re.sub(r"\b(19|20)\d\d(/\d\d)?\b", "", t)
    t = re.sub(r"\b\d+(st|nd|rd|th|\.)?\s*(edition|leidimas)?\b", "", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip(" ,.-—–") or call.title(lang)


# ---------------------------------------------------------------- weekly scan of a series page

def scan_series(series, page):
    """Ask Claude which calls on the series page are not in our list yet; create them as pending entries.
    Returns the new Call objects."""
    from pydantic import create_model

    from .extract import SYSTEM_PROMPT, extraction_model, parse_with_fallback, taxonomy_brief
    Scan = create_model("Scan", new_calls=(List[extraction_model()], ...))

    known = [{"title": c.title_en or c.title_lt, "deadline": c.deadline.isoformat() if c.deadline else "",
              "url": c.url} for c in calls_of(series) if not c.is_placeholder]
    prompt = (f"Today is {today().isoformat()}. This is the page of a recurring series: {series.name('en')} "
              f"({series.url}).\nCalls already in our database for this series:\n{known}\n\n"
              "List ONLY calls on this page that are NOT already in our database and are currently open or "
              "announced with a future deadline or opening date (new editions, new themes / special issues, "
              "new tracks). Return an empty list if there is nothing new. For each, fill every field; use the "
              "most specific URL for that call (the page URL if there is no better one).\n\n"
              f"{taxonomy_brief()}\n\nPage title: {page.title}\nPage text:\n{page.text}")
    resp = parse_with_fallback(model=current_app.config["CLAUDE_MODEL"], max_tokens=16000, system=SYSTEM_PROMPT,
                               output_config={"effort": current_app.config["CLAUDE_EFFORT"]}, output_format=Scan,
                               messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "refusal" or not resp.parsed_output:
        return []
    from .importer import apply_record
    from .views import to_record
    created = []
    for ex in resp.parsed_output.new_calls:
        if not ex.is_call or ex.status in ("closed",):
            continue
        data = ex.model_dump()
        data["url"] = data.get("url") or series.url
        if find_duplicates(data["url"], [ex.title_en, ex.title_lt]):
            # same link or similar title already known: only a new deadline makes it new
            if any(c.deadline and c.deadline.isoformat() == ex.deadline for c in calls_of(series)) or not ex.deadline:
                continue
        c = Call(series_id=series.id, first_seen=today().isoformat(), source=msg("found_in_series",
                 name=series.name("en")), source_url=series.url, needs_review=True)
        apply_record(c, to_record(data))
        c.status, c.verified = "pending", True
        c.review_reason = msg("found_in_series", name=series.name("en"))
        db.session.add(c)
        db.session.flush()
        db.session.add(CallChange(call_id=c.id, origin="series", note=msg("found_in_series", name=series.name("en"))))
        created.append(c)
    if created:
        series.last_found_at = utcnow()
    return created


def same_title(a, b, threshold=0.6):
    from difflib import SequenceMatcher
    a, b = norm_title(a), norm_title(b)
    return bool(a and b) and SequenceMatcher(None, a, b).ratio() >= threshold
