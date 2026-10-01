"""Periodic maintenance.

Status labels (open / closing soon / due today / closed) are computed from dates on every page
view, so they are always current without any job. This module does the slower work:

* archive entries whose deadline passed more than ARCHIVE_AFTER_DAYS ago
* re-fetch organiser pages (oldest-checked first, REFRESH_BATCH per run), record broken links
* when the page text changed, ask Claude to re-read it and update deadline / dates / status
  (every automatic change is logged in CallChange and flagged for curator review)
"""
import logging
from datetime import timedelta

from flask import current_app

from .extract import extract_with_claude, fetch, llm_available
from .importer import parse_date
from .messages import msg
from .models import Call, CallChange, RefreshRun, db, today, utcnow

log = logging.getLogger(__name__)

AUTO_FIELDS = {  # Extraction field -> model attribute (fields the refresher may update)
    "deadline": "deadline", "event_start": "event_start", "event_end": "event_end",
    "deadline_word_en": "deadline_word_en", "deadline_word_lt": "deadline_word_lt",
}


def flag(call, reason):
    call.needs_review = True
    call.review_reason = ((call.review_reason + "\n") if call.review_reason else "") + f"[{today()}] {reason}"


def archive_expired():
    cutoff = today() - timedelta(days=current_app.config["ARCHIVE_AFTER_DAYS"])
    n = 0
    for c in Call.query.filter(Call.status.in_(["open", "watch", "reject"])).all():
        d = c.deadline or c.expires
        if d and d < cutoff:
            db.session.add(CallChange(call_id=c.id, origin="refresh", field="status", old=c.status,
                                      new="archived", note=msg("deadline_passed", date=str(d))))
            c.status = "archived"
            n += 1
    db.session.commit()
    return n


def _set(call, attr, new, note):
    old = getattr(call, attr)
    if old == new:
        return False
    setattr(call, attr, new)
    db.session.add(CallChange(call_id=call.id, origin="refresh", field=attr,
                              old="" if old is None else str(old), new="" if new is None else str(new), note=note))
    return True


def check_call(call, use_llm=True):
    """Re-check one entry. Returns list of human-readable change descriptions."""
    page = fetch(call.url)
    call.last_checked_at = utcnow()
    call.last_http_status = page.status or None
    changes = []
    if page.error or page.status >= 400:
        flag(call, msg("link_broken", status=str(page.status or page.error)))
        return ["broken link"]
    new_hash = page.content_hash
    changed_page = bool(call.content_hash) and new_hash != call.content_hash
    first_check = not call.content_hash
    call.content_hash = new_hash
    if not (use_llm and llm_available()) or not (changed_page or (first_check and call.status == "watch")):
        return changes

    ex = extract_with_claude(page, previous=call.to_dict())
    if not ex:
        return changes
    note = msg("auto_check")
    for f, attr in AUTO_FIELDS.items():
        val = getattr(ex, f)
        new = parse_date(val) if attr in ("deadline", "event_start", "event_end") else val
        # Don't wipe a known date because the page no longer mentions it.
        if attr in ("deadline", "event_start", "event_end") and new is None:
            continue
        if _set(call, attr, new, note):
            changes.append(f"{attr}: {new}")
    if call.status == "watch" and ex.status == "open":
        _set(call, "status", "open", msg("call_opened"))
        changes.append("watch → open")
    elif call.status == "open" and ex.status == "closed" and (call.deadline is None or call.deadline >= today()):
        flag(call, msg("page_closed"))
    if changes:
        call.last_verified = today().isoformat()
        flag(call, msg("auto_updated", changes="; ".join(changes)))
    return changes


def run_refresh(limit=None, use_llm=True):
    cfg = current_app.config
    limit = limit or cfg["REFRESH_BATCH"]
    run = RefreshRun()
    db.session.add(run)
    db.session.commit()
    lines = [f"archived: {archive_expired()}"]
    if use_llm and llm_available():
        from .translate import translate_missing
        lines.append(f"translated fields: {translate_missing(limit=cfg['TRANSLATE_BATCH'])}")
    stale = utcnow() - timedelta(days=cfg["REFRESH_MIN_AGE_DAYS"])
    q = (Call.query.filter(Call.status.in_(["open", "watch"]), Call.url != "")
         .filter((Call.last_checked_at.is_(None)) | (Call.last_checked_at < stale))
         .order_by(Call.last_checked_at.is_(None).desc(), Call.last_checked_at.asc()).limit(limit))
    for call in q.all():
        if call.phase() == "closed":
            continue
        run.checked += 1
        try:
            ch = check_call(call, use_llm=use_llm)
            if ch:
                run.changed += 1
                lines.append(f"#{call.id} {call.title_en[:60]}: {', '.join(ch)}")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            run.errors += 1
            lines.append(f"#{call.id} ERROR {e}")
            log.exception("refresh failed for %s", call.id)
    run.finished_at = utcnow()
    run.log = "\n".join(lines)
    db.session.commit()
    return run
