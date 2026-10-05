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
    for url in ["/", "/call/1", "/map", "/about", "/my", "/suggest", "/admin/", "/admin/call/1/edit", "/admin/users", "/nope"]:
        html = c.get(url).get_data(as_text=True)
        html = re.sub(r"<(script|textarea|input|option)[^>]*>.*?</\1>|<input[^>]*>", "", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        found = [w for w in text.split() if lt_chars.search(w)]
        # the only Lithuanian allowed is untranslated *content*, which is tagged LT
        assert found in ([], ["Studentams"]), (url, found[:10])


def test_reminders(app):
    from app.models import ReminderSent, Subscription
    from app.reminders import send_reminders
    student = User(email="s@lmta.lt", name="S", lang="en")
    db.session.add(student)
    db.session.flush()
    db.session.add(Subscription(user_id=student.id, call_id=1))   # deadline in 3 days → due
    db.session.add(Subscription(user_id=student.id, call_id=2))   # deadline in 60 days → not yet
    db.session.commit()
    assert send_reminders() == (1, 0)          # console backend
    assert ReminderSent.query.count() == 1
    assert send_reminders() == (0, 0)          # never twice
    db.session.get(Call, 1).deadline += timedelta(days=1)  # deadline moved → new reminder
    db.session.commit()
    assert send_reminders() == (1, 0)


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
