"""Fill missing LT/EN translations of entry content with Claude.

The curator writes the detail fields (who it suits, benefit, fee, …) in Lithuanian only; admins may
enter English only. This finds every field pair where one language is missing and translates it,
in batches, without touching text that already exists in both languages."""
import json
import logging
from typing import List

from flask import current_app
from pydantic import BaseModel

from .extract import llm_available, parse_with_fallback
from .messages import msg
from .models import Call, CallChange, db

log = logging.getLogger(__name__)
BATCH = 8

SYSTEM = """You translate content for the open-calls website of the Music Innovation Studies Centre
(MISC) of the Lithuanian Academy of Music and Theatre. Translate between Lithuanian and English.
Keep names of organisations, festivals, conferences, programmes, currencies and dates unchanged.
Use natural, concise academic/arts-administration language. Do not add or drop information.
Organisation names: keep proper names, translate generic parts (e.g. "Oldenburgo universitetas" →
"University of Oldenburg"). If a text is already in the target language or is only a name, URL or
code, return it unchanged.
Return one item per requested field: `id` of the entry, the target `field` name and the translated `text`."""


class Item(BaseModel):
    id: int
    field: str
    text: str


class Result(BaseModel):
    items: List[Item]


def pending(limit=None):
    out = []
    for c in Call.query.filter(Call.status != "archived").order_by(Call.id).all():
        if c.missing_translations():
            out.append(c)
            if limit and len(out) >= limit:
                break
    return out


def translate_batch(calls):
    tasks, allowed = [], set()
    for c in calls:
        for a, b in c.missing_translations():
            src, dst = (a, b) if getattr(c, a) else (b, a)
            lang = "English" if dst.endswith("_en") else "Lithuanian"
            tasks.append({"id": c.id, "field": dst, "to": lang, "source": getattr(c, src)})
            allowed.add((c.id, dst))
    if not tasks:
        return 0
    resp = parse_with_fallback(
        model=current_app.config["CLAUDE_MODEL"], max_tokens=16000, system=SYSTEM,
        output_config={"effort": "low"}, output_format=Result,
        messages=[{"role": "user", "content": "Translate these fields:\n" + json.dumps(tasks, ensure_ascii=False)}])
    if resp.stop_reason != "end_turn" or not resp.parsed_output:
        log.warning("translation batch stopped: %s", resp.stop_reason)
        return 0
    by_id = {c.id: c for c in calls}
    n = 0
    for it in resp.parsed_output.items:
        c = by_id.get(it.id)
        if not c or (it.id, it.field) not in allowed or getattr(c, it.field) or not it.text.strip():
            continue
        setattr(c, it.field, it.text.strip())
        db.session.add(CallChange(call_id=c.id, origin="translate", field=it.field, new=it.text.strip(),
                                  note=msg("auto_translated")))
        n += 1
    db.session.commit()
    return n


def translate_call(call):
    """Fill the missing language of one saved entry (called after every save). Never raises."""
    if not llm_available() or not call.id or not call.missing_translations():
        return 0
    try:
        return translate_batch([call])
    except Exception:
        db.session.rollback()
        log.exception("translation of #%s failed", call.id)
        return 0


def translate_missing(limit=None, progress=None):
    """Returns number of fields translated. `limit` = max entries to process."""
    if not llm_available():
        return 0
    calls = pending(limit)
    total = 0
    for i in range(0, len(calls), BATCH):
        try:
            total += translate_batch(calls[i:i + BATCH])
        except Exception:
            db.session.rollback()
            log.exception("translation batch failed")
        if progress:
            progress(min(i + BATCH, len(calls)), len(calls), total)
    return total
