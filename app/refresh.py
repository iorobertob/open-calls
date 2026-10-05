"""Weekly maintenance (systemd timer, Monday night). Status labels (open / closing soon / closed) are
computed from dates on every page view, so they are always current without this job.

1. archive entries whose deadline passed more than ARCHIVE_AFTER_DAYS ago
2. translate missing LT/EN texts
3. re-check the pages of open / upcoming calls — Claude only when the page text changed:
   deadline extensions, dates, "opens soon → open". If the page now shows a *different* call
   (new edition / theme), a new entry is created for review instead of overwriting this one.
4. scan series pages for new calls → new pending entries for review
5. keep an "expected next call" placeholder for recurring series that have no live call

How "the page changed" is detected: the page's main text (without scripts, menus, headers,
footers and cookie banners, whitespace normalised) is hashed with SHA-256; the hash is stored
and compared with last week's. Same hash → no Claude call, no cost.
"""
import logging
from datetime import timedelta

from flask import current_app

from .extract import extract_with_claude, fetch, llm_available
from .importer import parse_date
from .messages import msg
from .models import Call, CallChange, RefreshRun, Series, db, today, utcnow
from .series import calls_of, ensure_placeholder, has_live_call, notify_change, same_title, scan_series

log = logging.getLogger(__name__)

AUTO_FIELDS = {  # Extraction field -> model attribute (fields the refresher may update)
    "deadline": "deadline", "event_start": "event_start", "event_end": "event_end",
    "deadline_word_en": "deadline_word_en", "deadline_word_lt": "deadline_word_lt",
}
NEW_EDITION_SHIFT_DAYS = 75   # a deadline moving further than this is a new edition, not an extension


def flag(call, reason):
    call.needs_review = True
    call.admin_notified_at = None   # include it in the next admin digest
    call.review_reason = ((call.review_reason + "\n") if call.review_reason else "") + f"[{today()}] {reason}"


def archive_expired():
    cutoff = today() - timedelta(days=current_app.config["ARCHIVE_AFTER_DAYS"])
    n = 0
    for c in Call.query.filter(Call.status.in_(["open", "watch", "reject"])).all():
        d = c.deadline or c.expires
        if c.is_placeholder:
            if c.expires and c.expires < today():   # the expected call did not appear in time
                if c.series_id:
                    real = [x for x in calls_of(c.series) if not x.is_placeholder]
                    if real:
                        flag(real[0], msg("expected_missing", date=str(c.expires)))
                c.status = "archived"
                n += 1
            continue
        if d and d < cutoff:
            db.session.add(CallChange(call_id=c.id, origin="refresh", field="status", old=c.status,
                                      new="archived", note=msg("deadline_passed", date=str(d))))
            c.status = "archived"
            n += 1
    db.session.commit()
    return n


def purge_old_logs(days=365):
    from .models import EmailLog, Notification
    cutoff = utcnow() - timedelta(days=days)
    n = EmailLog.query.filter(EmailLog.at < cutoff).delete()
    Notification.query.filter(Notification.sent_at < cutoff).delete()
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


def _is_new_edition(call, ex):
    """The page shows another call than this entry: other theme/title, or a deadline months away."""
    new_deadline = parse_date(ex.deadline)
    if call.deadline and new_deadline and abs((new_deadline - call.deadline).days) > NEW_EDITION_SHIFT_DAYS:
        return True
    old_title = call.title_en or call.title_lt
    return bool(old_title and ex.title_en and not same_title(old_title, ex.title_en))


def _create_edition(call, ex):
    from .importer import apply_record
    from .views import to_record
    data = ex.model_dump()
    data["url"] = data.get("url") or call.url
    new = Call(series_id=call.series_id, first_seen=today().isoformat(), source=msg("auto_check"),
               source_url=call.url, needs_review=True)
    apply_record(new, to_record(data))
    new.status, new.verified = "pending", True
    db.session.add(new)
    db.session.flush()
    new.review_reason = msg("new_edition", id=str(call.id))
    db.session.add(CallChange(call_id=new.id, origin="refresh", note=msg("auto_check")))
    flag(call, msg("new_edition", id=str(new.id)))
    return new


def _page_state(obj, page):
    """Record the fetch result on a Call or Series. Returns 'blocked' | 'broken' | 'changed' | 'same' | 'first'."""
    obj.last_checked_at = utcnow()
    obj.last_http_status = page.status or None
    if page.blocked:
        obj.last_http_status = None   # bot protection, not a broken link: can't be checked automatically
        return "blocked"
    if page.error or page.status >= 400:
        return "broken"
    new_hash = page.content_hash
    state = "first" if not obj.content_hash else ("same" if new_hash == obj.content_hash else "changed")
    obj.content_hash = new_hash
    return state


def check_call(call, use_llm=True):
    """Re-check one entry. Returns list of human-readable change descriptions."""
    page = fetch(call.url)
    state = _page_state(call, page)
    if state == "blocked":
        return ["site blocks automatic checks"]
    if state == "broken":
        flag(call, msg("link_broken", status=str(page.status or page.error)))
        return ["broken link"]
    if not (use_llm and llm_available()) or not (state == "changed" or (state == "first" and call.status == "watch")):
        return []

    ex = extract_with_claude(page, previous=call.to_dict())
    if not ex:
        return []
    if ex.is_call and _is_new_edition(call, ex):
        new = _create_edition(call, ex)
        return [f"different call on the page → new entry #{new.id} for review"]
    changes = []
    note = msg("auto_check")
    for f, attr in AUTO_FIELDS.items():
        val = getattr(ex, f)
        new = parse_date(val) if attr in ("deadline", "event_start", "event_end") else val
        if attr in ("deadline", "event_start", "event_end") and new is None:
            continue   # don't wipe a known date because the page no longer mentions it
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
        notify_change(call, "; ".join(changes))
    return changes


def check_series(series, use_llm=True):
    """Weekly scan of a series page. Returns the new pending Call entries."""
    page = fetch(series.url)
    state = _page_state(series, page)
    if state in ("blocked", "broken") or not (use_llm and llm_available()):
        return []
    # First check: only spend a Claude call if the series has nothing live (something new may be there).
    if state == "same" or (state == "first" and has_live_call(series)):
        return []
    return scan_series(series, page)


def run_refresh(limit=None, use_llm=True):
    cfg = current_app.config
    limit = limit or cfg["REFRESH_BATCH"] or None     # 0 = everything due
    run = RefreshRun()
    db.session.add(run)
    db.session.commit()
    lines = [f"archived: {archive_expired()}", f"old e-mail log entries removed: {purge_old_logs()}"]
    if use_llm and llm_available():
        from .translate import translate_missing
        lines.append(f"translated fields: {translate_missing(limit=cfg['TRANSLATE_BATCH'])}")

    stale = utcnow() - timedelta(days=cfg["REFRESH_MIN_AGE_DAYS"])
    q = (Call.query.filter(Call.status.in_(["open", "watch"]), Call.url != "", Call.is_placeholder.is_(False))
         .filter((Call.last_checked_at.is_(None)) | (Call.last_checked_at < stale))
         .order_by(Call.last_checked_at.is_(None).desc(), Call.last_checked_at.asc()))
    for call in q.all():
        if call.phase() == "closed":
            continue                     # over: archived later, not worth a page fetch
        if limit and run.checked >= limit:
            break
        run.checked += 1
        try:
            ch = check_call(call, use_llm=use_llm)
            if ch:
                run.changed += 1
                lines.append(f"#{call.id} {(call.title_en or call.title_lt)[:60]}: {', '.join(ch)}")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            run.errors += 1
            lines.append(f"#{call.id} ERROR {e}")
            log.exception("refresh failed for %s", call.id)

    for series in Series.query.filter(Series.active.is_(True), Series.url != "").all():
        if series.last_checked_at and series.last_checked_at >= stale:
            continue
        run.checked += 1
        try:
            found = check_series(series, use_llm=use_llm)
            if found:
                run.changed += 1
                lines.append(f"series '{series.name('en')}': {len(found)} new call(s) → review "
                             + ", ".join(f"#{c.id}" for c in found))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            run.errors += 1
            lines.append(f"series #{series.id} ERROR {e}")
            log.exception("series scan failed for %s", series.id)

    made = 0
    for series in Series.query.filter_by(active=True).all():
        if ensure_placeholder(series):
            made += 1
    db.session.commit()
    lines.append(f"expected-next placeholders created: {made}")

    run.finished_at = utcnow()
    run.log = "\n".join(lines)
    db.session.commit()
    return run
