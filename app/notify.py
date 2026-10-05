"""E-mail notifications over SMTP (MailerSend — MailerLite's sending service — or any SMTP server,
e.g. LMTA's Microsoft 365). Run daily by `flask send-notifications` (systemd timer, 09:00).

Each person gets at most ONE e-mail per day, bundling:
  * deadline reminders for subscribed calls: first when the deadline is REMINDER_FIRST_DAYS away
    (default 30), then every REMINDER_EVERY_DAYS (7) until the deadline
  * new calls published in series they follow
  * changes to subscribed calls (e.g. a deadline extension found by the weekly check)
Admins get a separate digest of entries waiting for approval / review (only new ones since the last digest).
Without SMTP settings, e-mails are written to the log instead (development)."""
import logging
import smtplib
from collections import defaultdict
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from .i18n import tr
from .messages import render as render_msg
from .models import Call, Notification, ReminderSent, Subscription, User, db, today, utcnow

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- transport

class Mailer:
    """One SMTP connection for a whole run (or the log when SMTP is not configured)."""

    def __init__(self):
        cfg = current_app.config
        self.console = cfg["MAIL_BACKEND"] != "smtp"
        self.cfg = cfg
        self.conn = None

    def __enter__(self):
        if not self.console:
            c = self.cfg
            if c["SMTP_PORT"] == 465:
                self.conn = smtplib.SMTP_SSL(c["SMTP_HOST"], c["SMTP_PORT"], timeout=30)
            else:
                self.conn = smtplib.SMTP(c["SMTP_HOST"], c["SMTP_PORT"], timeout=30)
                if c["SMTP_STARTTLS"]:
                    self.conn.starttls()
            if c["SMTP_USERNAME"]:
                self.conn.login(c["SMTP_USERNAME"], c["SMTP_PASSWORD"])
        return self

    def __exit__(self, *exc):
        if self.conn:
            try:
                self.conn.quit()
            except smtplib.SMTPException:
                pass

    def send(self, to, subject, text, html, unsubscribe_url=None):
        m = EmailMessage()
        m["From"] = self.cfg["MAIL_FROM"]
        m["To"] = to
        m["Subject"] = subject
        m["Message-ID"] = make_msgid(domain=self.cfg["ICS_UID_DOMAIN"])
        if self.cfg["MAIL_REPLY_TO"]:
            m["Reply-To"] = self.cfg["MAIL_REPLY_TO"]
        if unsubscribe_url:
            m["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        m.set_content(text)
        m.add_alternative(html, subtype="html")
        if self.console:
            log.info("EMAIL to %s — %s\n%s", to, subject, text)
        else:
            self.conn.send_message(m)


# ---------------------------------------------------------------- links & unsubscribe

def base_url():
    return current_app.config["PUBLIC_BASE_URL"].rstrip("/")


def _signer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="email-stop")


def stop_url(user):
    return f"{base_url()}/email/stop/{_signer().dumps(user.id)}"


def user_from_stop_token(token):
    try:
        return db.session.get(User, int(_signer().loads(token)))
    except (BadSignature, ValueError, TypeError):
        return None


# ---------------------------------------------------------------- deadline reminders

def due_reminders(ref=None):
    """{user: [call, …]} — subscribed calls whose next reminder is due today."""
    cfg = current_app.config
    ref = ref or today()
    first, every = cfg["REMINDER_FIRST_DAYS"], cfg["REMINDER_EVERY_DAYS"]
    rows = (db.session.query(User, Call)
            .join(Subscription, Subscription.user_id == User.id)
            .join(Call, Call.id == Subscription.call_id)
            .filter(User.email_reminders.is_(True), Call.status.in_(["open", "watch"]),
                    Call.deadline >= ref + timedelta(days=1), Call.deadline <= ref + timedelta(days=first))
            .all())
    last = {}
    for r in ReminderSent.query.filter(ReminderSent.deadline >= ref).all():
        k = (r.user_id, r.call_id, r.deadline)
        last[k] = max(last.get(k, r.sent_at), r.sent_at)
    out = defaultdict(list)
    for user, call in rows:
        prev = last.get((user.id, call.id, call.deadline))
        if prev is None or (ref - prev.date()).days >= every:
            out[user].append(call)
    return out


# ---------------------------------------------------------------- composing

def _line(call, lang, ref, extra=""):
    when = ""
    if call.deadline:
        days = (call.deadline - ref).days
        when = tr("Deadline {date} ({days} days left)", lang).format(date=call.deadline.isoformat(), days=days)
    elif call.deadline_word(lang):
        when = call.deadline_word(lang)
    return {"title": call.title(lang), "when": when, "url": f"{base_url()}/call/{call.id}",
            "org": call.org_name(lang), "extra": extra}


def _render(lang, greeting, sections, footer_url, stop):
    """sections: [(heading, [line dict])] → (text, html)"""
    text = [greeting, ""]
    html = [f'<div style="font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#16181d;max-width:640px">'
            f"<p>{escape(greeting)}</p>"]
    for heading, items in sections:
        if not items:
            continue
        text += [heading, "-" * len(heading)]
        html.append(f'<h3 style="font-size:16px;margin:22px 0 8px">{escape(heading)}</h3><ul style="padding-left:18px">')
        for it in items:
            text.append(f"• {it['title']}" + (f" — {it['when']}" if it["when"] else ""))
            if it["extra"]:
                text.append(f"  {it['extra']}")
            text.append(f"  {it['url']}")
            html.append(f'<li style="margin:0 0 10px"><a href="{escape(it["url"])}" style="color:#2c5fd0;font-weight:600">'
                        f'{escape(it["title"])}</a>' + (f'<br><span style="color:#5c6472">{escape(it["org"])}</span>' if it["org"] else "")
                        + (f"<br><b>{escape(it['when'])}</b>" if it["when"] else "")
                        + (f'<br><span style="color:#5c6472">{escape(it["extra"])}</span>' if it["extra"] else "") + "</li>")
        text.append("")
        html.append("</ul>")
    text += [tr("Manage your subscriptions", lang) + ": " + footer_url,
             tr("Stop all e-mails from MISC open calls", lang) + ": " + stop]
    html.append(f'<p style="margin-top:26px;font-size:13px;color:#5c6472">'
                f'<a href="{escape(footer_url)}" style="color:#5c6472">{escape(tr("Manage your subscriptions", lang))}</a> · '
                f'<a href="{escape(stop)}" style="color:#5c6472">{escape(tr("Stop all e-mails from MISC open calls", lang))}</a><br>'
                f'{escape(tr("Music Innovation Studies Centre", lang))} · LMTA</p></div>')
    return "\n".join(text), "".join(html)


# ---------------------------------------------------------------- daily run

def send_notifications(dry_run=False, ref=None):
    """Returns (users_emailed, admins_emailed, failures)."""
    ref = ref or today()
    reminders = due_reminders(ref)
    outbox = defaultdict(list)
    for n in Notification.query.filter(Notification.sent_at.is_(None)).all():
        if n.call and n.call.status in ("open", "watch"):
            outbox[n.user].append(n)
        else:
            n.sent_at = utcnow()   # call gone / unpublished in the meantime: drop silently
    users = set(reminders) | set(outbox)
    sent = failed = 0
    with (Mailer() if not dry_run else _DryRun()) as mail:
        for user in users:
            lang = user.lang or "lt"
            rem = sorted(reminders.get(user, []), key=lambda c: c.deadline)
            news = [n for n in outbox.get(user, []) if n.kind == "series_new" and user.email_series]
            changed = [n for n in outbox.get(user, []) if n.kind == "call_changed" and user.email_reminders]
            sections = [
                (tr("Upcoming deadlines of the calls you follow", lang), [_line(c, lang, ref) for c in rem]),
                (tr("New calls in series you follow", lang),
                 [_line(n.call, lang, ref, n.call.series.name(lang) if n.call.series else "") for n in news]),
                (tr("Changes to calls you follow", lang), [_line(n.call, lang, ref, n.detail) for n in changed]),
            ]
            count = len(rem) + len(news) + len(changed)
            if count:
                if count == 1:
                    only = (rem or [n.call for n in news + changed])[0]
                    kind = tr("Deadline reminder", lang) if rem else (
                        tr("New call", lang) if news else tr("Call updated", lang))
                    subject = f"{kind}: {only.title(lang)}"
                else:
                    subject = tr("MISC open calls: {0} updates for you", lang).format(count)
                greeting = tr("Hello", lang) + (f" {user.name.split()[0]}" if user.name else "") + ","
                text, html = _render(lang, greeting, sections, f"{base_url()}/my", stop_url(user))
                try:
                    mail.send(user.email, subject, text, html, stop_url(user))
                except (smtplib.SMTPException, OSError) as e:
                    failed += 1
                    log.error("e-mail to %s failed: %s", user.email, e)
                    continue
                sent += 1
            if not dry_run:
                stamp = datetime.combine(ref, utcnow().time())   # the run's date (= today in production)
                for c in rem:
                    db.session.add(ReminderSent(user_id=user.id, call_id=c.id, kind="deadline", deadline=c.deadline,
                                                sent_at=stamp))
                for n in outbox.get(user, []):
                    n.sent_at = utcnow()
                db.session.commit()
        admins = 0 if dry_run else send_admin_digest(mail)
    if not dry_run:
        db.session.commit()
    return sent, admins, failed


class _DryRun:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def send(self, to, subject, text, html, unsubscribe_url=None):
        log.info("[dry-run] %s — %s\n%s", to, subject, text)


def admin_recipients():
    emails = {u.email for u in User.query.filter_by(is_admin=True, email_admin=True).all()}
    opted_out = {u.email for u in User.query.filter_by(email_admin=False).all()}
    emails |= {e for e in current_app.config["ADMIN_EMAILS"] if e not in opted_out}
    return sorted(emails)


def send_admin_digest(mail):
    """New pending / needs-review entries since the last digest → one e-mail per admin."""
    new = Call.query.filter(Call.admin_notified_at.is_(None),
                            (Call.status == "pending") | (Call.needs_review.is_(True))).all()
    if not new:
        return 0
    n = 0
    for email in admin_recipients():
        user = User.query.filter_by(email=email).first()
        lang = (user.lang if user else None) or "lt"
        pending = [c for c in new if c.status == "pending"]
        review = [c for c in new if c.status != "pending"]
        def line(c):
            reason = render_msg((c.review_reason or "").strip().splitlines()[-1] if c.review_reason else "", lang)
            return {"title": c.title(lang), "when": "", "org": c.org_name(lang), "extra": reason,
                    "url": f"{base_url()}/admin/call/{c.id}/edit"}
        sections = [(tr("Waiting for approval", lang), [line(c) for c in pending]),
                    (tr("Automatic changes to review", lang), [line(c) for c in review])]
        subject = tr("MISC open calls — {0} entries to review", lang).format(len(new))
        text, html = _render(lang, tr("New entries in the admin queue:", lang), sections, f"{base_url()}/admin/",
                             stop_url(user) if user else f"{base_url()}/my")
        try:
            mail.send(email, subject, text, html)
            n += 1
        except (smtplib.SMTPException, OSError) as e:
            log.error("admin digest to %s failed: %s", email, e)
    for c in new:
        c.admin_notified_at = utcnow()
    return n


def send_test(to):
    with Mailer() as mail:
        mail.send(to, "MISC open calls — test e-mail",
                  "If you can read this, e-mail sending works.", "<p>If you can read this, e-mail sending works.</p>")
