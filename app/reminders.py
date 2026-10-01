"""Deadline reminders: email every subscribed user about calls whose deadline is
REMINDER_DAYS_BEFORE days away (default 7). Run daily (`flask send-reminders`, systemd timer).

A call is included once per user and deadline: if a deadline moves, a new reminder is sent for
the new date. Missed runs are caught up — any deadline within the window that has not been
reminded yet is included. All due calls for one user go into one email."""
import logging
from collections import defaultdict
from datetime import timedelta

from flask import current_app

from .i18n import tr
from .mailer import MailError, backend
from .models import Call, ReminderSent, Subscription, User, db, today

log = logging.getLogger(__name__)
KIND = "deadline"


def due(ref=None):
    ref = ref or today()
    days = current_app.config["REMINDER_DAYS_BEFORE"]
    rows = (db.session.query(User, Call)
            .join(Subscription, Subscription.user_id == User.id)
            .join(Call, Call.id == Subscription.call_id)
            .filter(User.email_reminders.is_(True), Call.status.in_(["open", "watch"]),
                    Call.deadline >= ref + timedelta(days=1), Call.deadline <= ref + timedelta(days=days))
            .all())
    sent = {(r.user_id, r.call_id, r.deadline) for r in
            ReminderSent.query.filter(ReminderSent.kind == KIND, ReminderSent.deadline >= ref).all()}
    out = defaultdict(list)
    for user, call in rows:
        if (user.id, call.id, call.deadline) not in sent:
            out[user].append(call)
    return out


def compose(user, calls, ref):
    lang = user.lang or "lt"
    base = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    calls = sorted(calls, key=lambda c: c.deadline)
    lines = []
    for c in calls:
        when = tr("Deadline {date} ({days} days left)", lang).format(date=c.deadline.isoformat(),
                                                                    days=(c.deadline - ref).days)
        lines.append(f"• {c.title(lang)} — {when}\n  {base}/call/{c.id}")
    subject = f"{tr('Deadline reminder', lang)}: " + (calls[0].title(lang) if len(calls) == 1 else
                                                       tr("Upcoming deadlines of the calls you follow", lang))
    return subject, "\n".join(lines), f"{base}/my"


def send_reminders(dry_run=False, ref=None):
    ref = ref or today()
    todo = due(ref)
    if not todo:
        return 0, 0
    mail = None if dry_run else backend()
    sent = failed = 0
    for user, calls in todo.items():
        subject, text, url = compose(user, calls, ref)
        if dry_run:
            log.info("[dry-run] %s: %s\n%s", user.email, subject, text)
            sent += 1
            continue
        try:
            mail.send_reminder(user, subject, text, len(calls), url)
        except (MailError, OSError) as e:
            failed += 1
            log.error("reminder to %s failed: %s", user.email, e)
            continue
        for c in calls:
            db.session.add(ReminderSent(user_id=user.id, call_id=c.id, kind=KIND, deadline=c.deadline))
        db.session.commit()
        sent += 1
    return sent, failed
