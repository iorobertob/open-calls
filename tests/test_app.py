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
