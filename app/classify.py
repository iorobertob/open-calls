"""Assign fields (Music and Sound, Theatre, Cinema, Dance and Performance) to existing entries with
Claude — `flask classify-fields`. Only adds fields; never removes one set by the curator or an admin."""
import json
import logging
from typing import List, Literal

from flask import current_app
from pydantic import BaseModel, create_model

from .extract import parse_with_fallback
from .models import Call, CallChange, db
from .taxonomy import tax

log = logging.getLogger(__name__)
BATCH = 25

SYSTEM = """You classify open calls (competitions, conferences, journals, residencies, academies…) listed by the
Music Innovation Studies Centre of the Lithuanian Academy of Music and Theatre into artistic fields.
For each entry return every field it is genuinely meant for. An entry can belong to several fields
(e.g. a film-music competition → music and cinema; an opera studies conference → music and theatre).
Be conservative: only add a field when the call explicitly targets that discipline, not because of a
passing mention or a venue name."""


def classify_all(dry_run=False, limit=None, progress=None):
    t = tax()
    keys = tuple(f.key for f in t.fields)
    Item = create_model("Item", id=(int, ...), fields=(List[Literal[keys]], ...))
    Result = create_model("Result", items=(List[Item], ...))
    fields_txt = "\n".join(f"{f.key}: {f.name_en}" for f in t.fields)
    calls = Call.query.filter(Call.status != "archived", Call.is_placeholder.is_(False)).order_by(Call.id).all()
    calls = calls[:limit] if limit else calls
    changes = []
    for i in range(0, len(calls), BATCH):
        batch = calls[i:i + BATCH]
        payload = [{"id": c.id, "title": c.title_en or c.title_lt, "description": c.desc_en or c.desc_lt,
                    "organiser": c.org_en or c.org, "sub_disciplines": c.topic_list, "current_fields": c.field_list}
                   for c in batch]
        try:
            resp = parse_with_fallback(
                model=current_app.config["CLAUDE_MODEL"], max_tokens=8000, system=SYSTEM,
                output_config={"effort": "low"}, output_format=Result,
                messages=[{"role": "user", "content": f"Fields:\n{fields_txt}\n\nEntries:\n"
                           + json.dumps(payload, ensure_ascii=False)}])
        except Exception:
            log.exception("classification batch failed")
            continue
        if resp.stop_reason != "end_turn" or not resp.parsed_output:
            continue
        by_id = {c.id: c for c in batch}
        for item in resp.parsed_output.items:
            c = by_id.get(item.id)
            if not c:
                continue
            added = [f for f in item.fields if f not in c.field_list]
            if added:
                changes.append((c.id, c.title_en or c.title_lt, added))
                if not dry_run:
                    old = ",".join(c.field_list)
                    c.field_list = c.field_list + added
                    db.session.add(CallChange(call_id=c.id, origin="classify", field="fields", old=old,
                                              new=",".join(c.field_list)))
        if not dry_run:
            db.session.commit()
        if progress:
            progress(min(i + BATCH, len(calls)), len(calls))
    return changes
