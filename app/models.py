import secrets
from datetime import date, datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

from .taxonomy import region_of

db = SQLAlchemy()

URGENT_DAYS = 14


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today():
    return date.today()


# Curator workflow statuses (same as the weekly JSON data block) plus moderation states.
STATUSES = ("open", "watch", "reject", "pending", "archived")

# Detail fields stored as <name> (Lithuanian) + <name>_en (English).
DETAIL_FIELDS = ("kam_tinka", "nauda", "mokestis", "amzius", "padengiama", "nuotoliu", "registracija",
                 "studentu_nuolaida", "note")
# Single fields written in Lithuanian by the curator (organiser names, provenance) + an <name>_en version.
NAME_FIELDS = ("org", "source")
# Every <name> + <name>_en pair (detail texts and names)
SINGLE_PAIRS = DETAIL_FIELDS + NAME_FIELDS
# Short bilingual pairs stored as <name>_lt / <name>_en.
PAIR_FIELDS = ("title", "desc", "city", "country", "deadline_word")

# Display phases, computed from dates on every request so the UI is always current.
PHASES = ("due_today", "closing_soon", "open", "rolling", "upcoming", "closed", "rejected", "pending")


class Call(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(16), default="open", index=True, nullable=False)
    verified = db.Column(db.Boolean, default=False)
    kind = db.Column(db.String(24), default="other", index=True)
    star = db.Column(db.Boolean, default=False)

    title_lt = db.Column(db.String(400), default="")
    title_en = db.Column(db.String(400), default="")
    org = db.Column(db.String(400), default="")
    org_en = db.Column(db.String(400), default="")
    city_lt = db.Column(db.String(160), default="")
    city_en = db.Column(db.String(160), default="")
    country_lt = db.Column(db.String(160), default="")
    country_en = db.Column(db.String(160), default="")
    country_code = db.Column(db.String(2), default="", index=True)

    deadline = db.Column(db.Date, index=True)
    deadline_word_lt = db.Column(db.String(300), default="")
    deadline_word_en = db.Column(db.String(300), default="")
    event_start = db.Column(db.Date)
    event_end = db.Column(db.Date)
    expires = db.Column(db.Date, index=True)

    url = db.Column(db.String(1000), default="", index=True)
    desc_lt = db.Column(db.Text, default="")
    desc_en = db.Column(db.Text, default="")
    topics = db.Column(db.String(400), default="")  # sub-discipline keys, stored as ",ai,research," (portable LIKE filtering)
    fields = db.Column(db.String(200), default="", nullable=False, server_default="")  # field keys, ",music,theatre,"

    kam_tinka = db.Column(db.Text, default="")         # eligibility / who it suits
    nauda = db.Column(db.Text, default="")             # concrete benefit for students
    mokestis = db.Column(db.Text, default="")          # fee
    amzius = db.Column(db.Text, default="")            # age limits
    padengiama = db.Column(db.Text, default="")        # what is covered
    nuotoliu = db.Column(db.Text, default="")          # remote participation (conferences)
    registracija = db.Column(db.Text, default="")      # registration fee (conferences)
    studentu_nuolaida = db.Column(db.Text, default="")  # student discount (conferences)
    note = db.Column(db.Text, default="")
    # English versions of the detail fields (the curator writes them in Lithuanian; `flask translate`
    # or the refresh job fills the missing language with Claude).
    kam_tinka_en = db.Column(db.Text, default="")
    nauda_en = db.Column(db.Text, default="")
    mokestis_en = db.Column(db.Text, default="")
    amzius_en = db.Column(db.Text, default="")
    padengiama_en = db.Column(db.Text, default="")
    nuotoliu_en = db.Column(db.Text, default="")
    registracija_en = db.Column(db.Text, default="")
    studentu_nuolaida_en = db.Column(db.Text, default="")
    note_en = db.Column(db.Text, default="")

    source = db.Column(db.String(400), default="")
    source_en = db.Column(db.String(400), default="")
    source_url = db.Column(db.String(1000), default="")
    first_seen = db.Column(db.String(40), default="")
    last_verified = db.Column(db.String(40), default="")

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    # Series (the recurring source this call belongs to) and lifecycle flags
    series_id = db.Column(db.Integer, db.ForeignKey("series.id"), index=True)
    is_placeholder = db.Column(db.Boolean, default=False, nullable=False, server_default=db.false())
    announced_at = db.Column(db.DateTime)       # followers of the series were told about this call
    admin_notified_at = db.Column(db.DateTime)  # included in an admin digest e-mail

    # Automatic monitoring
    last_checked_at = db.Column(db.DateTime)
    last_http_status = db.Column(db.Integer)
    content_hash = db.Column(db.String(64))
    needs_review = db.Column(db.Boolean, default=False, index=True)
    review_reason = db.Column(db.Text, default="")

    changes = db.relationship("CallChange", backref="call", cascade="all, delete-orphan",
                              order_by="CallChange.at.desc()")
    subscriptions = db.relationship("Subscription", backref="call", cascade="all, delete-orphan")
    reminders = db.relationship("ReminderSent", cascade="all, delete-orphan")
    notifications = db.relationship("Notification", cascade="all, delete-orphan")

    # ---- helpers
    @property
    def topic_list(self):
        return [t for t in (self.topics or "").split(",") if t]

    @topic_list.setter
    def topic_list(self, values):
        vals = [v.strip() for v in values if v and v.strip()]
        self.topics = ("," + ",".join(dict.fromkeys(vals)) + ",") if vals else ""

    @property
    def field_list(self):
        return [f for f in (self.fields or "").split(",") if f]

    @field_list.setter
    def field_list(self, values):
        vals = [v.strip() for v in values if v and v.strip()]
        self.fields = ("," + ",".join(dict.fromkeys(vals)) + ",") if vals else ""

    def title(self, lang):
        return (self.title_lt if lang == "lt" else self.title_en) or self.title_en or self.title_lt or self.url

    def desc(self, lang):
        return (self.desc_lt if lang == "lt" else self.desc_en) or self.desc_en or self.desc_lt

    def city(self, lang):
        return (self.city_lt if lang == "lt" else self.city_en) or self.city_en or self.city_lt

    def country(self, lang):
        return (self.country_lt if lang == "lt" else self.country_en) or self.country_en or self.country_lt

    def deadline_word(self, lang):
        return (self.deadline_word_lt if lang == "lt" else self.deadline_word_en) or self.deadline_word_en or self.deadline_word_lt

    def detail(self, name, lang):
        """Returns (text, is_other_language) — falls back to the other language when a translation is missing."""
        lt, en = getattr(self, name) or "", getattr(self, name + "_en") or ""
        if lang == "en":
            return (en, False) if en else (lt, bool(lt))
        return (lt, False) if lt else (en, bool(en))

    def org_name(self, lang):
        return self.detail("org", lang)[0]

    def source_text(self, lang):
        return self.detail("source", lang)[0]

    def missing_translations(self):
        """Field pairs where exactly one language is filled in. System messages (⟦…⟧ tokens) are
        already bilingual and are skipped."""
        pairs = [(f + "_lt", f + "_en") for f in PAIR_FIELDS] + [(f, f + "_en") for f in SINGLE_PAIRS]
        out = []
        for a, b in pairs:
            va, vb = getattr(self, a) or "", getattr(self, b) or ""
            if bool(va) != bool(vb) and "⟦" not in va + vb:
                out.append((a, b))
        return out

    @property
    def is_active(self):
        """Published and not over (what visitors see in the lists)."""
        return self.status in ("open", "watch") and self.phase() not in ("closed",)

    @property
    def region(self):
        return region_of(self.country_code)

    @property
    def key_date(self):
        """Date that decides whether the entry is still valid (curator rule: expires, else deadline)."""
        return self.deadline or self.expires

    def days_left(self, ref=None):
        d = self.deadline or self.expires
        if not d:
            return None
        return (d - (ref or today())).days

    def phase(self, ref=None):
        if self.status == "reject":
            return "rejected"
        if self.status == "pending":
            return "pending"
        if self.status == "archived":
            return "closed"
        n = self.days_left(ref)
        if self.status == "watch":
            return "closed" if (self.expires and n is not None and n < 0) else "upcoming"
        if n is None:
            return "rolling"
        if n < 0:
            return "closed"
        if n == 0:
            return "due_today"
        if n <= URGENT_DAYS:
            return "closing_soon"
        return "open"

    @property
    def remote_possible(self):
        s = (self.nuotoliu or "").strip().lower()
        if s.startswith(("taip", "yes", "hibrid", "hybrid", "tik internetu", "online")):
            return True
        return self.country_code == "XX" and (self.city_en or "").lower() == "online"

    @property
    def is_free(self):
        s = (self.mokestis or "").lower()
        return s.startswith(("nemokam", "free", "no fee", "teikimas nemokamas", "paraiška nemokama"))

    def to_dict(self):
        """Serialise in the curator's weekly JSON schema (schema 1) + app extras."""
        return {
            "id": self.id, "status": self.status, "verified": self.verified, "kind": self.kind,
            "star": self.star, "titleLt": self.title_lt, "titleEn": self.title_en, "org": self.org,
            "cityLt": self.city_lt, "cityEn": self.city_en, "countryLt": self.country_lt,
            "countryEn": self.country_en, "countryCode": self.country_code,
            "deadline": self.deadline.isoformat() if self.deadline else "",
            "deadlineWordLt": self.deadline_word_lt, "deadlineWordEn": self.deadline_word_en,
            "eventStart": self.event_start.isoformat() if self.event_start else "",
            "eventEnd": self.event_end.isoformat() if self.event_end else "",
            "url": self.url, "descLt": self.desc_lt, "descEn": self.desc_en, "topics": self.topic_list,
            "kamTinka": self.kam_tinka, "nauda": self.nauda, "mokestis": self.mokestis,
            "amzius": self.amzius, "padengiama": self.padengiama, "nuotoliu": self.nuotoliu,
            "registracija": self.registracija, "studentuNuolaida": self.studentu_nuolaida,
            "note": self.note, **{_camel(f) + "En": getattr(self, f + "_en") for f in SINGLE_PAIRS},
            "source": self.source, "sourceUrl": self.source_url,
            "firstSeen": self.first_seen, "lastVerified": self.last_verified,
            "expires": self.expires.isoformat() if self.expires else "",
            "phase": self.phase(), "daysLeft": self.days_left(),
        }


def _camel(name):
    head, *rest = name.split("_")
    return head + "".join(w.title() for w in rest)


class CallChange(db.Model):
    """Audit trail: every automatic or manual change to a call."""
    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, db.ForeignKey("call.id"), index=True, nullable=False)
    at = db.Column(db.DateTime, default=utcnow)
    origin = db.Column(db.String(24), default="admin")  # admin | refresh | import | suggestion
    field = db.Column(db.String(60), default="")
    old = db.Column(db.Text, default="")
    new = db.Column(db.Text, default="")
    note = db.Column(db.Text, default="")
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(320), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), default="")
    ms_oid = db.Column(db.String(64), unique=True)
    ms_tid = db.Column(db.String(64))
    is_admin = db.Column(db.Boolean, default=False)
    lang = db.Column(db.String(2), default="lt")
    email_reminders = db.Column(db.Boolean, default=True, nullable=False, server_default=db.true())  # deadlines + changes
    email_series = db.Column(db.Boolean, default=True, nullable=False, server_default=db.true())     # new calls in followed series
    email_admin = db.Column(db.Boolean, default=True, nullable=False, server_default=db.true())      # admin digest (admins only)
    calendar_token = db.Column(db.String(64), unique=True, default=lambda: secrets.token_urlsafe(24))
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login_at = db.Column(db.DateTime)

    subscriptions = db.relationship("Subscription", backref="user", cascade="all, delete-orphan")
    follows = db.relationship("SeriesFollow", backref="user", cascade="all, delete-orphan")

    def is_subscribed(self, call):
        return any(s.call_id == call.id for s in self.subscriptions)

    def is_following(self, series):
        return series is not None and any(f.series_id == series.id for f in self.follows)


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    call_id = db.Column(db.Integer, db.ForeignKey("call.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "call_id"),)


class ReminderSent(db.Model):
    """Log of deadline reminders: decides when the next one is due (first ~1 month before, then weekly)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    call_id = db.Column(db.Integer, db.ForeignKey("call.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(24), default="deadline_7d")
    deadline = db.Column(db.Date)  # if the deadline moves, a new reminder is due
    sent_at = db.Column(db.DateTime, default=utcnow)


class Series(db.Model):
    """A recurring source of calls — a journal, a conference, a festival, a residency programme.
    Its page is watched weekly; each edition / theme is a separate Call linked to it."""
    id = db.Column(db.Integer, primary_key=True)
    name_lt = db.Column(db.String(300), default="")
    name_en = db.Column(db.String(300), default="")
    kind = db.Column(db.String(24), default="other")
    org = db.Column(db.String(400), default="")
    url = db.Column(db.String(1000), default="")          # the page where new calls appear
    recurrence = db.Column(db.String(16), default="yearly")  # yearly | twice_yearly | rolling | irregular
    typical_month = db.Column(db.Integer)                 # month a new call usually appears (1–12), optional
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_checked_at = db.Column(db.DateTime)
    last_http_status = db.Column(db.Integer)
    content_hash = db.Column(db.String(64))
    last_found_at = db.Column(db.DateTime)                # a new call was detected on the page

    calls = db.relationship("Call", backref="series", order_by="Call.deadline.desc()")
    followers = db.relationship("SeriesFollow", backref="series", cascade="all, delete-orphan")

    def name(self, lang):
        return (self.name_lt if lang == "lt" else self.name_en) or self.name_en or self.name_lt


class SeriesFollow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    series_id = db.Column(db.Integer, db.ForeignKey("series.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "series_id"),)


class Notification(db.Model):
    """Outbox: events waiting to be e-mailed (bundled into one daily e-mail per user).
    kind: series_new (a followed series published a call) | call_changed (a subscribed call changed)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    call_id = db.Column(db.Integer, db.ForeignKey("call.id"), index=True)
    kind = db.Column(db.String(24), nullable=False)
    detail = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow)
    sent_at = db.Column(db.DateTime, index=True)
    user = db.relationship("User")
    call = db.relationship("Call", overlaps="notifications")


class Field(db.Model):
    """Top level of the taxonomy: Music and Sound, Theatre, Cinema, Dance and Performance."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    name_lt = db.Column(db.String(120), default="")
    name_en = db.Column(db.String(120), default="")
    hue = db.Column(db.Integer, default=212)
    position = db.Column(db.Integer, default=0)
    categories = db.relationship("Category", backref="field", order_by="Category.position")

    def name(self, lang):
        return (self.name_lt if lang == "lt" else self.name_en) or self.name_en or self.name_lt


class Category(db.Model):
    """Second level. field_id NULL = shared by all fields (e.g. research, workshops, formats)."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey("field.id"), index=True)
    name_lt = db.Column(db.String(120), default="")
    name_en = db.Column(db.String(120), default="")
    hue = db.Column(db.Integer)                 # chip colour; empty = neutral outline
    position = db.Column(db.Integer, default=0)
    disciplines = db.relationship("Discipline", backref="category", order_by="Discipline.position")

    def name(self, lang):
        return (self.name_lt if lang == "lt" else self.name_en) or self.name_en or self.name_lt


class Discipline(db.Model):
    """Third level (sub-discipline). Its key is what Call.topics stores."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False, index=True)
    name_lt = db.Column(db.String(120), default="")
    name_en = db.Column(db.String(120), default="")
    position = db.Column(db.Integer, default=0)

    def name(self, lang):
        return (self.name_lt if lang == "lt" else self.name_en) or self.name_en or self.name_lt


class EmailLog(db.Model):
    """Every e-mail the app sent or tried to send (Admin → E-mails)."""
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=utcnow, index=True)
    to = db.Column(db.String(320), default="", index=True)
    subject = db.Column(db.String(400), default="")
    kind = db.Column(db.String(24), default="other")    # notifications | admin_digest | test | other
    status = db.Column(db.String(12), default="sent")   # sent | failed | logged (no SMTP configured)
    error = db.Column(db.Text, default="")
    body = db.Column(db.Text, default="")
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))


class RefreshRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=utcnow)
    finished_at = db.Column(db.DateTime)
    checked = db.Column(db.Integer, default=0)
    changed = db.Column(db.Integer, default=0)
    errors = db.Column(db.Integer, default=0)
    log = db.Column(db.Text, default="")
