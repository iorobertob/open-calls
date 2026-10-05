"""Import the curator's weekly data (JSON block `misc-duomenys`, schema 1) into the DB.

Works with either the bare JSON file or the weekly `MISC-sarasas-<date>.html` list, so the
existing weekly Claude routine can keep producing its file and the app ingests it as-is.
Upsert key: url + English/Lithuanian title (several calls can share one url)."""
import json
import re
from datetime import date

from .models import SINGLE_PAIRS, Call, CallChange, db

FIELD_MAP = {  # JSON key -> model attribute
    "status": "status", "verified": "verified", "kind": "kind", "star": "star",
    "titleLt": "title_lt", "titleEn": "title_en", "org": "org",
    "cityLt": "city_lt", "cityEn": "city_en", "countryLt": "country_lt", "countryEn": "country_en",
    "countryCode": "country_code", "deadlineWordLt": "deadline_word_lt", "deadlineWordEn": "deadline_word_en",
    "url": "url", "descLt": "desc_lt", "descEn": "desc_en", "kamTinka": "kam_tinka", "nauda": "nauda",
    "mokestis": "mokestis", "amzius": "amzius", "padengiama": "padengiama", "nuotoliu": "nuotoliu",
    "registracija": "registracija", "studentuNuolaida": "studentu_nuolaida", "note": "note",
    "source": "source", "sourceUrl": "source_url", "firstSeen": "first_seen", "lastVerified": "last_verified",
}
FIELD_MAP.update({  # English detail fields (exported by this app; absent in the curator's weekly file)
    "kamTinkaEn": "kam_tinka_en", "naudaEn": "nauda_en", "mokestisEn": "mokestis_en", "amziusEn": "amzius_en",
    "padengiamaEn": "padengiama_en", "nuotoliuEn": "nuotoliu_en", "registracijaEn": "registracija_en",
    "studentuNuolaidaEn": "studentu_nuolaida_en", "noteEn": "note_en", "orgEn": "org_en", "sourceEn": "source_en",
})
DATE_FIELDS = {"deadline": "deadline", "expires": "expires", "eventStart": "event_start", "eventEnd": "event_end"}

JOURNAL_RE = re.compile(r"journal|special issue|research topic|magazin|open submissions|žurnal", re.I)
WORKS_RE = re.compile(r"call for (scores|works|sound artists)", re.I)


def parse_date(s):
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(s).strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def load_payload(text):
    """Accept raw JSON or an HTML page containing <script id="misc-duomenys">."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    m = re.search(r'<script type="application/json" id="misc-duomenys">(.*?)</script>', text, re.S)
    if not m:
        raise ValueError("No misc-duomenys data block found")
    return json.loads(m.group(1).replace("<\\/", "</"))


def refine_kind(rec):
    """The weekly data has 6 kinds; the app adds journal / works. Reclassify obvious cases."""
    kind = rec.get("kind") or "other"
    title = f"{rec.get('titleEn', '')} {rec.get('titleLt', '')}"
    if kind == "conference" and JOURNAL_RE.search(title):
        return "journal"
    if kind in ("competition", "festival") and WORKS_RE.search(title):
        return "works"
    return kind


def find_existing(rec):
    url = (rec.get("url") or "").strip()
    q = Call.query.filter(Call.url == url) if url else None
    if q is None:
        return None
    for c in q.all():
        if (rec.get("titleEn") and c.title_en == rec["titleEn"]) or (rec.get("titleLt") and c.title_lt == rec["titleLt"]):
            return c
    return None


def apply_record(call, rec, origin="import", overwrite=True):
    changed = []
    for key, attr in FIELD_MAP.items():
        if key not in rec:
            continue
        val = rec[key]
        if key == "countryCode":
            val = (val or "").upper()[:2]
        if key == "kind":
            val = refine_kind(rec)
        old = getattr(call, attr)
        if old != val and (overwrite or not old):
            setattr(call, attr, val)
            changed.append((attr, old, val))
    for key, attr in DATE_FIELDS.items():
        if key in rec:
            val = parse_date(rec[key])
            old = getattr(call, attr)
            if old != val and (overwrite or not old):
                setattr(call, attr, val)
                changed.append((attr, old, val))
    # A changed Lithuanian detail without a new English version → clear the stale translation
    # so the refresh job / `flask translate` fills it again.
    for attr, _, _ in list(changed):
        en = attr + "_en"
        if attr in SINGLE_PAIRS and hasattr(call, en) and not any(a == en for a, _, _ in changed) and getattr(call, en):
            changed.append((en, getattr(call, en), ""))
            setattr(call, en, "")
    if "topics" in rec:
        old = call.topic_list
        if old != list(rec["topics"] or []):
            call.topic_list = rec["topics"] or []
            changed.append(("topics", ",".join(old), ",".join(call.topic_list)))
    if call.id:
        for attr, old, new in changed:
            db.session.add(CallChange(call_id=call.id, origin=origin, field=attr,
                                      old="" if old is None else str(old), new="" if new is None else str(new)))
    return changed


def import_payload(payload, drop_expired=False):
    """Upsert every record; returns (created, updated, skipped)."""
    created = updated = skipped = 0
    new = []
    today = date.today()
    for rec in payload.get("calls", []):
        key = parse_date(rec.get("expires")) or parse_date(rec.get("deadline"))
        if drop_expired and key and key < today:
            skipped += 1
            continue
        existing = find_existing(rec)
        if existing:
            if apply_record(existing, rec):
                updated += 1
        else:
            c = Call()
            apply_record(c, rec)
            db.session.add(c)
            new.append(c)
            created += 1
    db.session.flush()
    if new:
        from .series import link_series, on_publish
        for c in new:
            if link_series(c):          # same website as a known series → attach, tell its followers
                on_publish(c)
    db.session.commit()
    return created, updated, skipped
