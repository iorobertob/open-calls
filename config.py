import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")


def _list(name):
    return [x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()]


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{BASE / 'instance' / 'opencalls.db'}")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_SAMESITE = "Lax"
    # Own cookie name + path so the app never clashes with WordPress cookies on the same domain
    SESSION_COOKIE_NAME = "misc_opencalls"
    SESSION_COOKIE_PATH = os.environ.get("APP_PREFIX", "") or "/"
    REMEMBER_COOKIE_NAME = "misc_opencalls_remember"
    REMEMBER_COOKIE_PATH = SESSION_COOKIE_PATH
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "http")
    SERVER_NAME = os.environ.get("SERVER_NAME") or None

    # Microsoft Entra ID (LMTA tenant)
    MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
    MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
    MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "organizations")
    ALLOWED_EMAIL_DOMAINS = _list("ALLOWED_EMAIL_DOMAINS")   # e.g. lmta.lt,stud.lmta.lt
    ADMIN_EMAILS = _list("ADMIN_EMAILS")
    DEV_LOGIN = os.environ.get("DEV_LOGIN", "0") == "1"

    # Claude (link extraction + periodic re-checks)
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_WORKSPACE_ID = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")   # only for keys not scoped to a workspace
    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
    CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")

    # Periodic refresh
    # Weekly check (Monday night). 0 = check every page that is due in one run.
    REFRESH_BATCH = int(os.environ.get("REFRESH_BATCH", 0))
    REFRESH_MIN_AGE_DAYS = int(os.environ.get("REFRESH_MIN_AGE_DAYS", 6))  # a page is "due" after 6 days
    ARCHIVE_AFTER_DAYS = int(os.environ.get("ARCHIVE_AFTER_DAYS", 14))  # move expired entries to archive
    TRANSLATE_BATCH = int(os.environ.get("TRANSLATE_BATCH", 40))       # entries translated per refresh run
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "0") == "1"   # in-process scheduler (single worker only)

    # E-mail over SMTP — MailerSend (MailerLite's sending service): smtp.mailersend.net:587,
    # or LMTA Microsoft 365: smtp.office365.com:587. Without SMTP_HOST e-mails only go to the log.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "MISC Open Calls <noreply@misc.lmta.lt>")
    MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")
    MAIL_BACKEND = os.environ.get("MAIL_BACKEND") or ("smtp" if SMTP_HOST else "console")
    # Deadline reminders: first this many days before the deadline, then every N days until it
    REMINDER_FIRST_DAYS = int(os.environ.get("REMINDER_FIRST_DAYS", 30))
    REMINDER_EVERY_DAYS = int(os.environ.get("REMINDER_EVERY_DAYS", 7))
    # Public address of the app, used for links in emails sent from cron jobs (no request context)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5055")

    ICS_UID_DOMAIN = os.environ.get("ICS_UID_DOMAIN", "misc.lmta.lt")
