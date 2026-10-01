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
    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
    CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")

    # Periodic refresh
    REFRESH_BATCH = int(os.environ.get("REFRESH_BATCH", 40))            # pages re-checked per run
    REFRESH_MIN_AGE_DAYS = int(os.environ.get("REFRESH_MIN_AGE_DAYS", 7))  # don't re-check more often than this
    ARCHIVE_AFTER_DAYS = int(os.environ.get("ARCHIVE_AFTER_DAYS", 14))  # move expired entries to archive
    TRANSLATE_BATCH = int(os.environ.get("TRANSLATE_BATCH", 40))       # entries translated per refresh run
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "0") == "1"   # in-process scheduler (single worker only)

    # Email reminders (MailerLite)
    MAILERLITE_API_KEY = os.environ.get("MAILERLITE_API_KEY", "")
    MAILERLITE_REMINDER_GROUP_ID = os.environ.get("MAILERLITE_REMINDER_GROUP_ID", "")
    # mailerlite once the key and group are set, otherwise console (reminders only written to the log)
    MAIL_BACKEND = os.environ.get("MAIL_BACKEND") or (
        "mailerlite" if MAILERLITE_API_KEY and MAILERLITE_REMINDER_GROUP_ID else "console")
    REMINDER_DAYS_BEFORE = int(os.environ.get("REMINDER_DAYS_BEFORE", 7))
    # Public address of the app, used for links in emails sent from cron jobs (no request context)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5055")

    ICS_UID_DOMAIN = os.environ.get("ICS_UID_DOMAIN", "misc.lmta.lt")
