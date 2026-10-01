"""Email delivery backends for deadline reminders.

MailerLite is a marketing platform without a one-to-one (transactional) send API, so reminders use
MailerLite's recommended pattern:

  1. upsert the subscriber (POST /api/subscribers) with custom fields holding the reminder content
  2. remove them from the reminder group, then add them again
  3. a MailerLite automation "When subscriber joins group <reminder group>" sends the email,
     using the custom fields as merge tags ({$misc_reminder_subject}, {$misc_reminder_list}, …).
     In the automation settings, tick "Allow subscribers to re-enter automation"
     (MailerLite allows re-entry at most once per 24 h — one bundled email per user per day).

`flask mailerlite-setup` creates the fields and the group. MAIL_BACKEND=console only logs
(development)."""
import logging

import requests
from flask import current_app

log = logging.getLogger(__name__)
API = "https://connect.mailerlite.com/api"

# MailerLite custom fields used by the automation email (name → type)
FIELDS = {
    "misc_reminder_subject": "text",
    "misc_reminder_list": "text",     # plain-text list of calls (one per line)
    "misc_reminder_count": "number",
    "misc_reminder_url": "text",      # link to the user's subscriptions page
    "misc_language": "text",          # lt | en — use a condition block in the email for two languages
}
TEXT_LIMIT = 1000  # keep custom text fields short; the email links to the full list


class MailError(RuntimeError):
    pass


class MailerLite:
    def __init__(self, api_key, group_id, timeout=20):
        if not api_key or not group_id:
            raise MailError("MAILERLITE_API_KEY and MAILERLITE_REMINDER_GROUP_ID must be set")
        self.group_id = str(group_id)
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                               "Accept": "application/json"})

    def _req(self, method, path, **kw):
        r = self.s.request(method, API + path, timeout=self.timeout, **kw)
        if r.status_code >= 400 and not (method == "DELETE" and r.status_code == 404):
            raise MailError(f"MailerLite {method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def upsert(self, email, name, fields):
        body = {"email": email, "fields": {"name": name, **fields}}
        return self._req("POST", "/subscribers", json=body)["data"]["id"]

    def send_reminder(self, user, subject, text_list, count, url):
        fields = {"misc_reminder_subject": subject[:255], "misc_reminder_list": text_list[:TEXT_LIMIT],
                  "misc_reminder_count": count, "misc_reminder_url": url, "misc_language": user.lang or "lt"}
        sid = self.upsert(user.email, user.name or "", fields)
        # Re-joining the group is what triggers the automation email.
        self._req("DELETE", f"/subscribers/{sid}/groups/{self.group_id}")
        self._req("POST", f"/subscribers/{sid}/groups/{self.group_id}")

    # ---- one-time setup
    def ensure_fields(self):
        existing = {f["key"] for f in self._req("GET", "/fields", params={"limit": 100}).get("data", [])}
        created = []
        for key, typ in FIELDS.items():
            if key not in existing:
                self._req("POST", "/fields", json={"name": key, "type": typ})
                created.append(key)
        return created


def create_group(api_key, name):
    s = requests.post(f"{API}/groups", json={"name": name}, timeout=20,
                      headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    if s.status_code >= 400:
        raise MailError(f"MailerLite group: {s.status_code} {s.text[:300]}")
    return s.json()["data"]["id"]


class Console:
    def send_reminder(self, user, subject, text_list, count, url):
        log.info("REMINDER to %s — %s\n%s\n%s", user.email, subject, text_list, url)


def backend():
    cfg = current_app.config
    if cfg["MAIL_BACKEND"] == "mailerlite":
        return MailerLite(cfg["MAILERLITE_API_KEY"], cfg["MAILERLITE_REMINDER_GROUP_ID"])
    return Console()
