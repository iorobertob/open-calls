from datetime import date, timedelta

import pytest

from app import create_app
from app.models import Call, User, db
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    DEV_LOGIN = True
    ADMIN_EMAILS = ["admin@lmta.lt"]
    ANTHROPIC_API_KEY = ""
    ENABLE_SCHEDULER = False


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        from app.taxonomy import seed_defaults
        seed_defaults()
        t = date.today()
        db.session.add_all([
            Call(title_en="Soon conf", kind="conference", status="open", deadline=t + timedelta(days=3),
                 country_code="DE", topics=",ai,paper,", url="https://a.example"),
            Call(title_en="Later residency", kind="residency", status="open", deadline=t + timedelta(days=60),
                 country_code="FI", topics=",soundart,", mokestis="Nemokama", url="https://b.example"),
            Call(title_en="Past", kind="competition", status="open", deadline=t - timedelta(days=2), url="https://c.example"),
            Call(title_en="Watch me", kind="academy", status="watch", url="https://d.example"),
        ])
        db.session.commit()
        yield app


def login(client, email="admin@lmta.lt"):
    return client.post("/auth/dev-login", data={"email": email})


def test_phases(app):
    phases = {c.title_en: c.phase() for c in Call.query.all()}
    assert phases == {"Soon conf": "closing_soon", "Later residency": "open", "Past": "closed", "Watch me": "upcoming"}


def test_list_hides_closed_and_filters(app):
    c = app.test_client()
    body = c.get("/").get_data(as_text=True)
    assert "Soon conf" in body and "Watch me" in body and "Past" not in body
    assert "Later residency" not in c.get("/?kind=conference").get_data(as_text=True)
    assert "Soon conf" not in c.get("/?free=1").get_data(as_text=True)
    assert "Later residency" in c.get("/?region=BALTIC").get_data(as_text=True)
    assert "Soon conf" in c.get("/?topic=ai").get_data(as_text=True)
    assert "Soon conf" in c.get("/?q=soon").get_data(as_text=True)


def test_ics(app):
    c = app.test_client()
    r = c.get("/calendar.ics")
    assert r.mimetype == "text/calendar" and r.data.count(b"BEGIN:VEVENT") == 2
    assert b"TRIGGER:-P7D" in r.data


def test_subscribe_and_personal_feed(app):
    c = app.test_client()
    assert c.post("/call/1/subscribe").status_code == 302  # redirected to login
    login(c, "student@lmta.lt")
    c.post("/call/1/subscribe")
    token = User.query.filter_by(email="student@lmta.lt").one().calendar_token
    assert c.get(f"/feed/u/{token}.ics").data.count(b"BEGIN:VEVENT") == 1


def test_admin_only(app):
    c = app.test_client()
    login(c, "student@lmta.lt")
    assert c.get("/admin/").status_code == 403
    c.get("/auth/logout")
    login(c)
    assert c.get("/admin/").status_code == 200


def test_import_roundtrip(app):
    from app.importer import import_payload
    c = app.test_client()
    payload = c.get("/api/export.json").get_json()
    created, updated, _ = import_payload(payload)
    assert created == 0  # idempotent: same url + title are merged


def test_prefix_mount(app):
    """Behind nginx at /open-calls: links, redirects and login `next` keep the prefix."""
    c = app.test_client()
    h = {"X-Forwarded-Prefix": "/open-calls", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "misc.lmta.lt"}
    body = c.get("/", headers=h).get_data(as_text=True)
    assert 'href="/open-calls/static/style.css"' in body and 'href="/open-calls/call/1"' in body
    r = c.get("/my", headers=h)
    assert r.headers["Location"].startswith("/open-calls/auth/login?next=")
    c.post("/auth/dev-login", data={"email": "student@lmta.lt"}, headers=h)
    r = c.post("/call/1/subscribe", data={"next": "/my"}, headers=h)
    assert r.headers["Location"] == "/open-calls/my"
    r = c.post("/call/1/unsubscribe", data={"next": "https://evil.example/"}, headers=h)
    assert r.headers["Location"] == "/open-calls/call/1"
    feed = c.get("/feed.ics", headers=h).get_data(as_text=True).replace("\r\n ", "")  # unfold iCal lines
    assert "https://misc.lmta.lt/open-calls/call/" in feed


def test_english_mode_has_no_lithuanian_ui(app):
    import re
    from app.models import Call
    c = app.test_client()
    login(c)
    c.get("/lang/en")
    call = Call.query.first()
    call.kam_tinka, call.kam_tinka_en = "Studentams", ""
    db.session.commit()
    lt_chars = re.compile(r"[ąčęėįšųūž]")
    from app.models import Series
    s = Series(name_en="Soundworks Journal", name_lt="Soundworks Journal", recurrence="yearly", url="https://sw.example")
    db.session.add(s)
    db.session.flush()
    call.series_id = s.id
    db.session.add(Call(title_en="Other", url="https://a.example/2", status="open"))   # → a suggested series group
    db.session.commit()
    for url in ["/", "/call/1", "/map", "/about", "/my", "/suggest", "/admin/", "/admin/call/1/edit", "/admin/users", "/nope",
                f"/series/{s.id}", "/admin/series", f"/admin/series/{s.id}", "/admin/series/suggestions", "/admin/series/new",
                "/admin/emails", "/admin/emails/test", "/?field=music&cat=compute"]:
        html = c.get(url).get_data(as_text=True)
        html = re.sub(r"<(script|textarea|input|option)[^>]*>.*?</\1>|<input[^>]*>", "", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        found = [w for w in text.split() if lt_chars.search(w)]
        # the only Lithuanian allowed is untranslated *content*, which is tagged LT
        assert found in ([], ["Studentams"]), (url, found[:10])


def _capture(monkeypatch):
    """Collect e-mails instead of sending them."""
    from app import notify
    sent = []
    monkeypatch.setattr(notify.Mailer, "send", lambda self, to, subject, text, html, unsubscribe_url=None, **kw:
                        sent.append({"to": to, "subject": subject, "text": text, "html": html}))
    return sent


def test_deadline_reminders_monthly_then_weekly(app, monkeypatch):
    from app.models import ReminderSent, Subscription
    from app.notify import send_notifications
    sent = _capture(monkeypatch)
    student = User(email="s@lmta.lt", name="Sam S", lang="en")
    db.session.add(student)
    db.session.flush()
    later = db.session.get(Call, 2)               # deadline in 60 days
    db.session.add(Subscription(user_id=student.id, call_id=2))
    db.session.commit()
    t0 = later.deadline - timedelta(days=31)
    assert send_notifications(ref=t0) == (0, 0, 0)                        # 31 days before: nothing yet
    assert send_notifications(ref=t0 + timedelta(days=1))[0] == 1          # 30 days before: first reminder
    assert "Deadline reminder: Later residency" in sent[-1]["subject"] and "30 days left" in sent[-1]["text"]
    for d in range(2, 8):
        assert send_notifications(ref=t0 + timedelta(days=d))[0] == 0      # not again within the week
    assert send_notifications(ref=t0 + timedelta(days=8))[0] == 1          # a week later: 23 days left
    assert "23 days left" in sent[-1]["text"]
    assert ReminderSent.query.count() == 2
    student.email_reminders = False
    db.session.commit()
    assert send_notifications(ref=t0 + timedelta(days=15))[0] == 0         # switched off


def test_one_bundled_email_and_admin_digest(app, monkeypatch):
    from app.models import Notification, Series, SeriesFollow, Subscription
    from app.notify import send_notifications
    from app.series import notify_change, on_publish
    sent = _capture(monkeypatch)
    s = Series(name_en="Soundworks Journal", name_lt="Soundworks žurnalas", recurrence="yearly")
    student = User(email="s@lmta.lt", lang="en")
    db.session.add_all([s, student])
    db.session.flush()
    db.session.add_all([SeriesFollow(user_id=student.id, series_id=s.id), Subscription(user_id=student.id, call_id=1)])
    new_call = db.session.get(Call, 2)
    new_call.series_id = s.id
    db.session.flush()
    assert on_publish(new_call) == 1 and on_publish(new_call) == 0       # followers told once
    notify_change(db.session.get(Call, 1), "deadline: 2026-12-01")
    pending = Call(title_en="Suggested thing", status="pending", url="https://p.example")
    db.session.add(pending)
    db.session.commit()
    users, admins, failed = send_notifications()
    assert (users, failed) == (1, 0) and admins == 1                     # admin@lmta.lt from ADMIN_EMAILS
    mine = [m for m in sent if m["to"] == "s@lmta.lt"]
    assert len(mine) == 1                                                # one e-mail, three sections
    assert "updates for you" in mine[0]["subject"]
    for part in ("Upcoming deadlines", "New calls in series you follow", "Soundworks Journal", "Changes to calls you follow",
                 "deadline: 2026-12-01", "/email/stop/"):
        assert part in mine[0]["text"], part
    digest = [m for m in sent if m["to"] == "admin@lmta.lt"][0]
    assert "Suggested thing" in digest["text"] and "/admin/call/" in digest["text"]
    assert Notification.query.filter(Notification.sent_at.is_(None)).count() == 0
    sent.clear()
    assert send_notifications() == (0, 0, 0) and sent == []              # nothing new → no e-mails


def test_stop_link_turns_emails_off(app):
    from app.notify import stop_url
    student = User(email="s@lmta.lt")
    db.session.add(student)
    db.session.commit()
    path = stop_url(student).split("/email/")[1]
    c = app.test_client()
    assert c.get("/email/" + path).status_code == 200
    c.post("/email/" + path)
    db.session.refresh(student)
    assert not (student.email_reminders or student.email_series or student.email_admin)
    assert c.get("/email/stop/forged-token").status_code == 404


def test_series_placeholder_and_publish(app):
    from app.models import Series
    from app.series import ensure_placeholder, expected_next, on_publish, placeholder_of
    s = Series(name_en="Soundworks Journal", name_lt="Soundworks žurnalas", recurrence="yearly", url="https://sw.example/cfp")
    db.session.add(s)
    db.session.flush()
    past = db.session.get(Call, 3)                      # closed call of this series
    past.series_id, past.first_seen = s.id, "2026-02-10"
    db.session.commit()
    assert expected_next(s, ref=date(2026, 10, 1)) == date(2027, 2, 1)
    ph = ensure_placeholder(s)
    assert ph and ph.is_placeholder and ph.status == "watch" and ph.phase() == "upcoming"
    assert "Expected around February 2027" == ph.deadline_word_en and "2027 m. vasarį" in ph.deadline_word_lt
    assert ensure_placeholder(s) is None                  # only one
    new = Call(title_en="Soundworks 2027 call", status="open", series_id=s.id, deadline=date.today() + timedelta(days=90))
    db.session.add(new)
    db.session.flush()
    on_publish(new)
    db.session.commit()
    assert placeholder_of(s) is None                      # replaced by the real call


def test_recheck_never_overwrites_with_a_new_edition(app, monkeypatch):
    from app import refresh
    from app.extract import Page
    call = db.session.get(Call, 2)
    call.content_hash = "old"
    old_deadline = call.deadline
    db.session.commit()
    page = Page(url=call.url, status=200, text="Call for residencies 2028 — deadline next year")
    monkeypatch.setattr(refresh, "fetch", lambda url: page)
    monkeypatch.setattr(refresh, "llm_available", lambda: True)
    fake = {f: "" for f in __import__("app.extract", fromlist=["Extraction"]).Extraction.model_fields}
    fake.update(is_call=True, status="open", kind="residency", title_en="Later residency 2028", fields=[],
                deadline=(old_deadline + timedelta(days=365)).isoformat(), topics=[], star=False, confidence="high")
    from app.extract import Extraction
    monkeypatch.setattr(refresh, "extract_with_claude", lambda p, previous=None: Extraction(**fake))
    changes = refresh.check_call(call)
    db.session.commit()
    assert "new entry" in changes[0]
    assert db.session.get(Call, 2).deadline == old_deadline          # untouched
    new = Call.query.filter_by(status="pending").one()
    assert new.title_en == "Later residency 2028" and db.session.get(Call, 2).needs_review


def test_series_scan_creates_pending_entries(app, monkeypatch):
    from app import series as series_mod
    from app.extract import Extraction, Page
    from app.models import Series
    s = Series(name_en="Soundworks Journal", recurrence="yearly", url="https://sw.example/cfp")
    db.session.add(s)
    db.session.commit()
    base = {f: "" for f in Extraction.model_fields} | {"is_call": True, "status": "open", "kind": "journal",
                                                        "topics": [], "fields": [], "star": False, "confidence": "high"}
    found = [Extraction(**base | {"title_en": "Soundworks Vol. 9: Listening", "deadline": "2027-03-01",
                                   "url": "https://sw.example/cfp/vol9"}),
             Extraction(**base | {"title_en": "Soon conf", "deadline": "", "url": "https://a.example"})]  # already known

    class Resp:
        stop_reason = "end_turn"
        parsed_output = type("Scan", (), {"new_calls": found})()
    monkeypatch.setattr("app.extract.parse_with_fallback", lambda **kw: Resp())
    created = series_mod.scan_series(s, Page(url=s.url, status=200, text="..."))
    db.session.commit()
    assert [c.title_en for c in created] == ["Soundworks Vol. 9: Listening"]
    assert created[0].status == "pending" and created[0].series_id == s.id and created[0].needs_review


def test_smtp_message_format(app, monkeypatch):
    import smtplib
    from app import notify
    boxes = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): boxes.append({"host": host, "port": port})
        def starttls(self): boxes[-1]["tls"] = True
        def login(self, u, p): boxes[-1]["login"] = u
        def send_message(self, m): boxes[-1]["msg"] = m
        def quit(self): pass
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    app.config.update(MAIL_BACKEND="smtp", SMTP_HOST="smtp.mailersend.net", SMTP_PORT=587,
                      SMTP_USERNAME="MS_user", SMTP_PASSWORD="x", MAIL_FROM="MISC Open Calls <noreply@misc.lmta.lt>")
    with notify.Mailer() as m:
        m.send("s@lmta.lt", "Subject ąčę", "text body", "<p>html body</p>", "https://x/email/stop/t")
    box = boxes[0]
    assert box["host"] == "smtp.mailersend.net" and box["tls"] and box["login"] == "MS_user"
    msg = box["msg"]
    assert msg["From"] == "MISC Open Calls <noreply@misc.lmta.lt>" and msg["List-Unsubscribe"] == "<https://x/email/stop/t>"
    assert msg.get_content_type() == "multipart/alternative" and msg["Subject"] == "Subject ąčę"

def test_blocked_page_detection():
    from app.extract import Page
    assert Page(url="x", status=403, title="Just a moment...", text="Just a moment...").blocked
    assert Page(url="x", status=200, title="", text="Please verify you are human").blocked
    assert not Page(url="x", status=200, title="Call for papers", text="Deadline 1 March 2027").blocked


def test_add_by_link_with_pasted_text(app):
    c = app.test_client()
    login(c)
    c.get("/lang/en")
    r = c.post("/admin/import-url", data={"url": "https://example.org/cfp",
                                          "page_text": "Call for papers. Deadline: 1 March 2027."})
    html = r.get_data(as_text=True)
    assert 'name="deadline" value="2027-03-01"' in html
    assert "ANTHROPIC_API_KEY is not set" in html   # tells the admin exactly why AI was not used


def test_extraction_keeps_both_languages(app):
    from app.importer import apply_record
    from app.models import SINGLE_PAIRS
    from app.views import to_record
    data = {f: f"LT {f}" for f in SINGLE_PAIRS} | {f + "_en": f"EN {f}" for f in SINGLE_PAIRS}
    c = Call()
    apply_record(c, to_record(data))
    assert all(getattr(c, f) and getattr(c, f + "_en") for f in SINGLE_PAIRS)


def test_duplicate_detection(app):
    from app.duplicates import find_duplicates, norm_url
    assert norm_url("http://www.Example.org/cfp/?utm_source=x#top") == norm_url("https://example.org/cfp")
    assert [r for _, r in find_duplicates("https://www.a.example/")] == ["link"]
    assert [r for _, r in find_duplicates("https://other.example", ["Soon conf."])] == ["title"]
    assert find_duplicates("https://other.example", ["Something unrelated"]) == []


def test_admin_new_warns_about_duplicates(app):
    c = app.test_client()
    login(c)
    form = {"title_en": "Soon conf", "url": "https://a.example", "status": "open", "kind": "conference"}
    r = c.post("/admin/new", data=form)
    assert r.status_code == 200 and "Soon conf" in r.get_data(as_text=True)   # form shown again, not saved
    assert Call.query.count() == 4
    r = c.post("/admin/new", data=form | {"not_duplicate": "on"})
    assert r.status_code == 302 and Call.query.count() == 5


def test_editing_one_language_clears_stale_translation(app):
    c = app.test_client()
    login(c)
    call = db.session.get(Call, 2)
    call.nauda, call.nauda_en = "Sena nauda", "Old benefit"
    db.session.commit()
    form = {f: getattr(call, f) or "" for f in ("title_en", "url", "status", "kind")} | {
        "nauda": "Nauja nauda", "nauda_en": "Old benefit"}
    c.post("/admin/call/2/edit", data=form)
    db.session.refresh(call)
    assert call.nauda == "Nauja nauda" and call.nauda_en == ""   # cleared → re-translated (needs the API key)


def test_organiser_language_fallback(app):
    call = Call(org="Oldenburgo universitetas", org_en="")
    assert call.org_name("en") == "Oldenburgo universitetas"
    call.org_en = "University of Oldenburg"
    assert call.org_name("en") == "University of Oldenburg" and call.org_name("lt") == "Oldenburgo universitetas"
    assert ("org", "org_en") not in call.missing_translations()


def test_admin_can_archive_and_delete(app):
    from app.models import CallChange, ReminderSent, Subscription
    c = app.test_client()
    login(c)
    c.get("/lang/en")
    admin = User.query.filter_by(email="admin@lmta.lt").one()
    db.session.add_all([Subscription(user_id=admin.id, call_id=2),
                        ReminderSent(user_id=admin.id, call_id=2, deadline=date.today()),
                        CallChange(call_id=2, field="note", new="x")])
    db.session.commit()
    page = c.get("/admin/call/2/edit").get_data(as_text=True)
    assert "Delete permanently" in page and "Archive" in page and "Users subscribed to it: 1" in page
    c.post("/admin/call/2/action", data={"action": "archive"})
    assert db.session.get(Call, 2).status == "archived"
    r = c.post("/admin/call/2/action", data={"action": "delete", "next": "/"})
    assert r.headers["Location"] == "/"
    assert db.session.get(Call, 2) is None
    assert Subscription.query.count() == ReminderSent.query.count() == CallChange.query.filter_by(call_id=2).count() == 0
    # students can't delete
    c.get("/auth/logout"); login(c, "student@lmta.lt")
    assert c.post("/admin/call/1/action", data={"action": "delete"}).status_code == 403
    assert db.session.get(Call, 1) is not None



# ---------------------------------------------------------------- fields → categories → sub-disciplines

def test_fields_follow_sub_disciplines(app):
    c = Call(title_en="Film score lab", status="open", topics=",filmmusic,research,")
    db.session.add(c)
    db.session.commit()
    assert c.field_list == ["cinema"]                       # implied by its sub-discipline
    bare = Call(title_en="Something", status="open", topics=",research,")   # only a shared one
    db.session.add(bare)
    db.session.commit()
    assert bare.field_list == ["music"]                      # never without a field
    assert db.session.get(Call, 1).field_list == ["music"]  # "ai, paper" → music


def test_explorer_filters_and_counts(app):
    db.session.add(Call(title_en="Opera lab", status="open", topics=",opera,", url="https://o.example",
                        deadline=date.today() + timedelta(days=20)))
    db.session.commit()
    c = app.test_client()
    c.get("/lang/en")
    home = c.get("/").get_data(as_text=True)
    assert "Music and Sound" in home and "Theatre" in home and "Cinema" in home and "Dance and Performance" in home
    theatre = c.get("/?field=theatre").get_data(as_text=True)
    assert "Opera lab" in theatre and "Soon conf" not in theatre
    assert "Music theatre &amp; opera" in theatre                # its categories appear
    cat = c.get("/?field=music&cat=compute").get_data(as_text=True)
    assert "Soon conf" in cat and "Later residency" not in cat and "generative AI" in cat   # sub-disciplines appear
    both = c.get("/?cat=compute&topic=ai&topic=algorithmic").get_data(as_text=True)
    assert "Soon conf" in both                                # several sub-disciplines = any of them
    old = c.get("/?family=compute").get_data(as_text=True)     # old links still work
    assert "Soon conf" in old and "Later residency" not in old


def test_admin_edits_taxonomy(app):
    from app.models import Category, Discipline, Field
    c = app.test_client()
    login(c)
    post = lambda **d: c.post("/admin/taxonomy", data=d)
    post(action="field_save", key="Bad Key!", name_en="X")
    assert not Field.query.filter_by(name_en="X").first()             # invalid key refused
    post(action="field_save", key="design", name_lt="Dizainas", name_en="Design", hue="30", position="9")
    f = Field.query.filter_by(key="design").one()
    post(action="cat_save", key="graphic", field_id=str(f.id), name_en="Graphic design", hue="40")
    cat = Category.query.filter_by(key="graphic").one()
    post(action="disc_save", key="typography", category_id=str(cat.id), name_lt="tipografija", name_en="typography")
    d = Discipline.query.filter_by(key="typography").one()
    post(action="disc_save", id=str(d.id), category_id=str(cat.id), name_lt="šriftai", name_en="type design")
    assert db.session.get(Discipline, d.id).name_en == "type design"     # renamed, key kept
    entry = db.session.get(Call, 2)
    entry.topic_list = ["soundart", "typography"]
    db.session.commit()
    assert "design" in entry.field_list
    # delete the sub-discipline, replacing it with another → entries updated
    post(action="disc_delete", id=str(d.id), replace_with="mediaart")
    db.session.refresh(entry)
    assert entry.topic_list == ["soundart", "mediaart"] and not Discipline.query.filter_by(key="typography").first()
    # delete the field: its categories become shared, entries lose the field
    post(action="field_delete", id=str(f.id), move_to="")
    db.session.refresh(entry)
    assert "design" not in entry.field_list and Category.query.filter_by(key="graphic").one().field_id is None
    # a category with sub-disciplines can't be deleted without a target
    spatial = Category.query.filter_by(key="spatial").one()
    post(action="cat_delete", id=str(spatial.id))
    assert db.session.get(Category, spatial.id) is not None
    c.get("/lang/en")
    page = c.get("/admin/taxonomy").get_data(as_text=True)
    assert "Music and Sound" in page and "Shared by all fields" in page


# ---------------------------------------------------------------- e-mail log & test e-mails

def test_email_log_records_every_attempt(app):
    from app.models import EmailLog, Subscription
    from app.notify import send_notifications
    student = User(email="s@lmta.lt", lang="en")
    db.session.add(student)
    db.session.flush()
    db.session.add(Subscription(user_id=student.id, call_id=1))       # deadline in 3 days → reminder due
    db.session.commit()
    send_notifications()
    row = EmailLog.query.filter_by(to="s@lmta.lt").one()
    assert row.status == "logged" and row.kind == "notifications" and "Soon conf" in row.body


def test_smtp_failures_are_logged(app, monkeypatch):
    import smtplib
    from app import notify
    from app.models import EmailLog

    class Refuses:
        def __init__(self, *a, **k): pass
        def starttls(self): pass
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        def quit(self): pass
    monkeypatch.setattr(smtplib, "SMTP", Refuses)
    app.config.update(MAIL_BACKEND="smtp", SMTP_HOST="smtp.mailersend.net", SMTP_USERNAME="u", SMTP_PASSWORD="bad")
    c = app.test_client()
    login(c)
    c.get("/lang/en")
    r = c.post("/admin/emails/test", data={"to": "me@lmta.lt", "kind": "simple"}, follow_redirects=True)
    assert "Sending failed: 535 Authentication failed" in r.get_data(as_text=True)
    row = EmailLog.query.filter_by(status="failed").one()
    assert "535" in row.error and "smtp.mailersend.net" in row.to
    log_page = c.get("/admin/emails?status=failed").get_data(as_text=True)
    assert "535 Authentication failed" in log_page


def test_test_email_previews_do_not_change_state(app):
    from app.models import EmailLog, ReminderSent, Subscription
    student = User(email="s@lmta.lt", lang="en")
    db.session.add(student)
    db.session.flush()
    db.session.add(Subscription(user_id=student.id, call_id=1))
    db.session.commit()
    c = app.test_client()
    login(c)
    c.get("/lang/en")
    c.post("/admin/emails/test", data={"to": "me@lmta.lt", "kind": "user", "user_id": str(student.id)})
    c.post("/admin/emails/test", data={"to": "me@lmta.lt", "kind": "admin"})
    subjects = [e.subject for e in EmailLog.query.order_by(EmailLog.id).all()]
    assert subjects[0].startswith("[TEST] Deadline reminder: Soon conf") and subjects[1].startswith("[TEST] MISC open calls")
    assert ReminderSent.query.count() == 0                     # nothing marked as sent
    assert "Send a test e-mail" in c.get("/admin/emails/test").get_data(as_text=True)


def test_classify_adds_fields_only(app, monkeypatch):
    from app import classify
    call = db.session.get(Call, 2)

    class Resp:
        stop_reason = "end_turn"
    def fake(**kw):
        Result = kw["output_format"]
        r = Resp()
        r.parsed_output = Result(items=[{"id": 2, "fields": ["dance"]}, {"id": 1, "fields": ["music"]}])
        return r
    monkeypatch.setattr(classify, "parse_with_fallback", fake)
    changes = classify.classify_all()
    db.session.refresh(call)
    assert changes == [(2, "Later residency", ["dance"])] and call.field_list == ["music", "dance"]
