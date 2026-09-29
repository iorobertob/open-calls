import json
import re
from datetime import date
from pathlib import Path

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required
from werkzeug.datastructures import MultiDict

from .extract import extract_url
from .i18n import get_lang, tr
from .ics import ics_response
from .importer import apply_record
from .models import Call, CallChange, Subscription, User, db, today
from .search import Filters, run_search, sort_calls
from .taxonomy import COUNTRIES, KINDS, TOPICS

bp = Blueprint("main", __name__)


def _public_call(call_id):
    c = db.get_or_404(Call, call_id)
    if c.status == "pending" and not (current_user.is_authenticated and
                                      (current_user.is_admin or c.submitted_by_id == current_user.id)):
        abort(404)
    return c


@bp.route("/")
def index():
    lang = get_lang()
    f = Filters(request.args, current_user)
    calls, kind_counts = run_search(f, lang)
    countries = sorted({c.country_code for c in Call.query.with_entities(Call.country_code).distinct() if c.country_code},
                       key=lambda code: COUNTRIES.get(code, (0, 0, 0, code, code))[3 if lang == "lt" else 4])
    urgent = sum(1 for c in calls if c.phase() in ("due_today", "closing_soon"))
    return render_template("index.html", calls=calls, f=f, kind_counts=kind_counts, countries=countries,
                           urgent=urgent, query_string=request.query_string.decode())


@bp.route("/call/<int:call_id>")
def detail(call_id):
    c = _public_call(call_id)
    return render_template("detail.html", c=c)


@bp.route("/call/<int:call_id>.ics")
def call_ics(call_id):
    c = _public_call(call_id)
    return ics_response([c], f"misc-call-{c.id}.ics", get_lang(), name=c.title(get_lang()))


@bp.route("/calendar.ics")
def calendar_download():
    """The current filtered list as a one-off .ics download."""
    lang = get_lang()
    calls, _ = run_search(Filters(request.args, current_user), lang)
    return ics_response(calls, f"misc-calls-{today().isoformat()}.ics", lang)


@bp.route("/feed.ics")
def calendar_feed():
    """Same list as a subscribable feed (no account needed) — calendar apps poll it, so it stays current."""
    lang = request.args.get("lang") if request.args.get("lang") in ("lt", "en") else "lt"
    args = MultiDict(request.args)
    args.pop("mine", None)
    calls, _ = run_search(Filters(args, None), lang)
    return ics_response(calls, "misc-calls.ics", lang, attachment=False)


@bp.route("/feed/u/<token>.ics")
def user_feed(token):
    user = User.query.filter_by(calendar_token=token).first_or_404()
    calls = [s.call for s in user.subscriptions if s.call.status != "pending"]
    return ics_response(sort_calls(calls, "deadline"), "misc-my-calls.ics", user.lang or "lt",
                        name=f"MISC — {user.name or user.email}", attachment=False)


@bp.route("/call/<int:call_id>/subscribe", methods=["POST"])
@login_required
def subscribe(call_id):
    c = _public_call(call_id)
    if not current_user.is_subscribed(c):
        db.session.add(Subscription(user_id=current_user.id, call_id=c.id))
        db.session.commit()
    return redirect(request.form.get("next") or url_for(".detail", call_id=c.id))


@bp.route("/call/<int:call_id>/unsubscribe", methods=["POST"])
@login_required
def unsubscribe(call_id):
    Subscription.query.filter_by(user_id=current_user.id, call_id=call_id).delete()
    db.session.commit()
    return redirect(request.form.get("next") or url_for(".detail", call_id=call_id))


@bp.route("/my")
@login_required
def my():
    calls = sort_calls([s.call for s in current_user.subscriptions], "deadline", get_lang())
    feed = url_for(".user_feed", token=current_user.calendar_token, _external=True)
    return render_template("my.html", calls=calls, feed=feed, webcal=re.sub(r"^https?://", "webcal://", feed))


@bp.route("/my/reset-feed", methods=["POST"])
@login_required
def reset_feed():
    import secrets
    current_user.calendar_token = secrets.token_urlsafe(24)
    db.session.commit()
    return redirect(url_for(".my"))


@bp.route("/suggest", methods=["GET", "POST"])
@login_required
def suggest():
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        if not re.match(r"^https?://", url):
            flash("URL must start with http:// or https://", "error")
            return redirect(url_for(".suggest"))
        data, _page, _ = extract_url(url)
        c = Call(submitted_by_id=current_user.id, first_seen=today().isoformat(),
                 source=f"Pasiūlė {current_user.email}", url=url)
        apply_record(c, to_record(data))
        c.status = "pending"
        db.session.add(c)
        db.session.flush()
        comment = (request.form.get("comment") or "").strip()
        c.needs_review = True
        c.review_reason = f"Naudotojo pasiūlymas ({current_user.email})" + (f": {comment}" if comment else "")
        db.session.add(CallChange(call_id=c.id, origin="suggestion", user_id=current_user.id, note=comment))
        db.session.commit()
        flash(tr("Thank you — the suggestion was sent for review."), "ok")
        return redirect(url_for(".index"))
    return render_template("suggest.html")


def to_record(data):
    """Map Extraction field names to the curator JSON schema used by importer.apply_record."""
    m = {"title_en": "titleEn", "title_lt": "titleLt", "city_en": "cityEn", "city_lt": "cityLt",
         "country_en": "countryEn", "country_lt": "countryLt", "country_code": "countryCode",
         "deadline_word_en": "deadlineWordEn", "deadline_word_lt": "deadlineWordLt", "desc_en": "descEn",
         "desc_lt": "descLt", "kam_tinka": "kamTinka", "studentu_nuolaida": "studentuNuolaida",
         "event_start": "eventStart", "event_end": "eventEnd"}
    rec = {m.get(k, k): v for k, v in data.items() if k not in ("is_call", "confidence")}
    if rec.get("status") == "closed":
        rec["status"] = "reject"
    return rec


@bp.route("/map")
def map_view():
    lang = get_lang()
    calls, _ = run_search(Filters(request.args, current_user), lang)
    points = {}
    online = []
    for c in calls:
        info = COUNTRIES.get(c.country_code or "")
        item = {"id": c.id, "t": c.title(lang), "k": c.kind, "d": c.deadline.isoformat() if c.deadline else "",
                "p": c.phase(), "city": c.city(lang)}
        if not info or info[1] is None:
            online.append(item)
            continue
        p = points.setdefault(c.country_code, {"code": c.country_code, "lat": info[1], "lon": info[2],
                                               "name": info[3] if lang == "lt" else info[4], "items": []})
        p["items"].append(item)
    return render_template("map.html", points=list(points.values()), online=online, total=len(calls))


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/lang/<code>")
def set_lang(code):
    if code in ("lt", "en"):
        session["lang"] = code
        if current_user.is_authenticated:
            current_user.lang = code
            db.session.commit()
    return redirect(request.referrer or url_for(".index"))


# ---------------------------------------------------------------- JSON API

@bp.route("/api/calls")
def api_calls():
    lang = get_lang()
    calls, counts = run_search(Filters(request.args, current_user), lang)
    return jsonify({"generated": date.today().isoformat(), "count": len(calls), "kinds": counts,
                    "calls": [c.to_dict() for c in calls]})


@bp.route("/api/export.json")
def api_export():
    """All current open / watch / reject entries in the curator's weekly schema (schema 1)."""
    calls = Call.query.filter(Call.status.in_(["open", "watch", "reject"])).all()
    calls = [c for c in calls if c.phase() != "closed"]
    body = {"schema": 1, "generated": date.today().isoformat(),
            "rules": "status: open|watch|reject. Eksportuota iš MISC atvirų kvietimų programos.",
            "calls": [c.to_dict() for c in sort_calls(calls, "deadline")]}
    return Response(json.dumps(body, ensure_ascii=False, indent=1), mimetype="application/json")


# ---------------------------------------------------------------- TV screen

SCREEN_KIND = {"journal": "conference", "works": "competition", "grant": "mobility", "other": "competition"}
SCREEN_TOPICS = set(TOPICS) - {"musicology", "pedagogy", "theatre"}


@bp.route("/screen")
def screen():
    """The MISC TV-screen template, filled live from the database (open entries, by deadline)."""
    tpl = (Path(current_app.root_path) / "screen_template.html").read_text(encoding="utf-8")
    calls = [c for c in Call.query.filter_by(status="open").all()
             if c.phase() in ("due_today", "closing_soon", "open", "rolling")]
    data = []
    for c in sort_calls(calls, "deadline"):
        topics = [t for t in c.topic_list if t in SCREEN_TOPICS][:4] or ["research", "workshop"]
        data.append({"kind": SCREEN_KIND.get(c.kind, c.kind), "titleLt": c.title_lt or c.title_en,
                     "titleEn": c.title_en or c.title_lt, "cityLt": c.city_lt, "cityEn": c.city_en,
                     "countryLt": c.country_lt, "countryEn": c.country_en, "countryCode": c.country_code or "XX",
                     "deadline": c.deadline.isoformat() if c.deadline else "",
                     "deadlineWordLt": c.deadline_word_lt, "deadlineWordEn": c.deadline_word_en,
                     "descLt": c.desc_lt, "descEn": c.desc_en, "topics": topics, "url": c.url})
    js = json.dumps(data, ensure_ascii=False, indent=1).replace("</", "<\\/")
    tpl = re.sub(r"var CALLS = \[.*?\n\];", lambda _: f"var CALLS = {js};", tpl, count=1, flags=re.S)
    d = date.today()
    months = ["sausio", "vasario", "kovo", "balandžio", "gegužės", "birželio", "liepos", "rugpjūčio",
              "rugsėjo", "spalio", "lapkričio", "gruodžio"]
    tpl = re.sub(r"updatedLt: '[^']*'", f"updatedLt: 'Atnaujinta {d.year} m. {months[d.month - 1]} {d.day} d.'", tpl, 1)
    tpl = re.sub(r"updatedEn: '[^']*'", f"updatedEn: 'Updated {d.strftime('%d %B %Y')}'", tpl, 1)
    tpl = re.sub(r"checkBadge: true", "checkBadge: false", tpl, 1)
    return Response(tpl, mimetype="text/html")
