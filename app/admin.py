from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .auth import safe_next
from .duplicates import find_duplicates
from .extract import extract_url, llm_available
from .i18n import get_lang, tr
from .importer import apply_record, import_payload, load_payload, parse_date
from .models import PAIR_FIELDS, SINGLE_PAIRS, STATUSES, Call, CallChange, RefreshRun, Series, User, db, today
from .refresh import check_call, check_series, run_refresh
from .series import expected_next, link_series, notify_change, on_publish, series_name_from, suggest_groups
from .translate import pending as pending_translations
from .translate import translate_call
from .messages import msg
from .messages import render as render_msg
from .views import to_record

bp = Blueprint("admin", __name__, url_prefix="/admin")

TEXT_FIELDS = ["title_lt", "title_en", "org", "city_lt", "city_en", "country_lt", "country_en", "country_code",
               "deadline_word_lt", "deadline_word_en", "url", "desc_lt", "desc_en", "kam_tinka", "nauda",
               "mokestis", "amzius", "padengiama", "nuotoliu", "registracija", "studentu_nuolaida", "note",
               "source", "source_url", "first_seen", "last_verified",
               *[f + "_en" for f in SINGLE_PAIRS]]
DATE_FIELDS = ["deadline", "expires", "event_start", "event_end"]


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if not current_user.is_admin:
            abort(403)
        return fn(*a, **kw)
    return wrapper


@bp.route("/")
@admin_required
def dashboard():
    review = Call.query.filter(Call.needs_review.is_(True), Call.status != "pending").order_by(Call.updated_at.desc()).all()
    pending = Call.query.filter_by(status="pending").order_by(Call.created_at.desc()).all()
    broken = [c for c in Call.query.filter(Call.last_http_status >= 400, Call.status.in_(["open", "watch"])).all()]
    runs = RefreshRun.query.order_by(RefreshRun.started_at.desc()).limit(5).all()
    stats = {s: Call.query.filter_by(status=s).count() for s in STATUSES}
    return render_template("admin/dashboard.html", review=review, pending=pending, broken=broken, runs=runs,
                           stats=stats, llm=llm_available(), untranslated=len(pending_translations()),
                           series_count=Series.query.count(), suggestions=len(suggest_groups()),
                           mail_backend=current_app.config["MAIL_BACKEND"])


def _form_to_call(call):
    changes = []
    for f in TEXT_FIELDS:
        val = (request.form.get(f) or "").strip()
        if f == "country_code":
            val = val.upper()[:2]
        if f == "source" and val == render_msg(call.source, get_lang()):
            continue  # shown translated in the form; keep the stored language-neutral token
        if getattr(call, f) != val:
            changes.append((f, getattr(call, f), val))
            setattr(call, f, val)
    for f in DATE_FIELDS:
        val = parse_date(request.form.get(f))
        if getattr(call, f) != val:
            changes.append((f, getattr(call, f), val))
            setattr(call, f, val)
    for f in ("status", "kind"):
        val = request.form.get(f) or getattr(call, f)
        if getattr(call, f) != val:
            changes.append((f, getattr(call, f), val))
            setattr(call, f, val)
    for f in ("star", "verified"):
        val = request.form.get(f) == "on"
        if getattr(call, f) != val:
            changes.append((f, getattr(call, f), val))
            setattr(call, f, val)
    # One language edited, the other not: the other side is now outdated — clear it so it is re-translated.
    changed = {f for f, _, _ in changes}
    for a, b in [(f + "_lt", f + "_en") for f in PAIR_FIELDS] + [(f, f + "_en") for f in SINGLE_PAIRS]:
        for edited, other in ((a, b), (b, a)):
            if edited in changed and other not in changed and getattr(call, edited) and getattr(call, other):
                changes.append((other, getattr(call, other), ""))
                setattr(call, other, "")
    sid = request.form.get("series_id", "")
    sid = int(sid) if sid.isdigit() else None
    if "series_id" in request.form and sid != call.series_id:
        changes.append(("series_id", call.series_id, sid))
        call.series_id = sid
    topics = request.form.getlist("topics")
    if topics != call.topic_list:
        changes.append(("topics", ",".join(call.topic_list), ",".join(topics)))
        call.topic_list = topics
    return changes


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    call = Call(status="open", kind="conference", first_seen=today().isoformat(), last_verified=today().isoformat(),
                verified=True, source=msg("manual_entry"))
    if request.method == "POST":
        _form_to_call(call)
        if not (call.title_en or call.title_lt):
            flash(tr("A title is required."), "error")
            return render_template("admin/form.html", c=call)
        dups = find_duplicates(call.url, [call.title_en, call.title_lt])
        if dups and request.form.get("not_duplicate") != "on":
            flash(tr("This may already be in the database. Check the entries below; to save anyway, tick "
                     "“It is a different call” and save again."), "error")
            return render_template("admin/form.html", c=call, duplicates=dups)
        db.session.add(call)
        link_series(call)
        db.session.flush()
        db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, note=msg("created")))
        on_publish(call)       # followers of its series get an e-mail; the placeholder goes away
        db.session.commit()
        translate_call(call)   # fill whichever language was left empty
        flash(tr("Saved."), "ok")
        return redirect(url_for("main.detail", call_id=call.id))
    return render_template("admin/form.html", c=call)


@bp.route("/import-url", methods=["POST"])
@admin_required
def import_url():
    """Fetch a link, extract its fields and show the pre-filled form for review before saving."""
    url = (request.form.get("url") or "").strip()
    data, page, used_llm = extract_url(url, request.form.get("page_text", ""))
    call = Call(status="open", first_seen=today().isoformat(), last_verified=today().isoformat(), verified=used_llm,
                source=msg("admin_link"), url=url)
    apply_record(call, to_record(data))
    call.review_reason = data.get("review", "")
    if used_llm and data.get("confidence") == "low":
        flash(tr("Low-confidence extraction — check every field."), "error")
    code, detail = data.get("problem") or ("", "")
    if code == "blocked":
        flash(tr("This site blocks automatic reading (HTTP {0}). Open the page in your browser, copy all its text "
                 "into “Page text” and extract again.").format(detail), "error")
    elif code == "unreachable":
        flash(tr("Could not open the page:") + " " + detail, "error")
    elif code == "no_api_key":
        flash(tr("ANTHROPIC_API_KEY is not set (restart the app after editing .env) — basic extraction only."), "error")
    elif code == "llm_failed":
        flash(tr("The Claude request failed — basic extraction only. Error:") + " " + detail, "error")
    elif code == "llm_refused":
        flash(tr("Claude declined to read this page — basic extraction only."), "error")
    if data.get("is_call") is False:
        flash(tr("The page does not look like an open call."), "error")
    dups = find_duplicates(call.url or url, [call.title_en, call.title_lt])
    return render_template("admin/form.html", c=call, extracted=True, duplicates=dups)


@bp.route("/call/<int:call_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(call_id):
    call = db.get_or_404(Call, call_id)
    if request.method == "POST":
        was_live = call.status in ("open", "watch")
        changes = _form_to_call(call)
        for f, old, new in changes:
            db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, field=f,
                                      old="" if old is None else str(old), new="" if new is None else str(new)))
        if request.form.get("clear_review") == "on":
            call.needs_review, call.review_reason = False, ""
        fields = {f for f, _, _ in changes}
        if call.status in ("open", "watch") and (not was_live or "series_id" in fields):
            on_publish(call)
        elif was_live and fields & {"deadline", "event_start", "event_end"}:
            notify_change(call, "; ".join(f"{f}: {new or '—'}" for f, _, new in changes
                                          if f in ("deadline", "event_start", "event_end")))
        db.session.commit()
        translate_call(call)
        flash(tr("Saved."), "ok")
        return redirect(url_for("main.detail", call_id=call.id))
    return render_template("admin/form.html", c=call)


@bp.route("/call/<int:call_id>/action", methods=["POST"])
@admin_required
def action(call_id):
    call = db.get_or_404(Call, call_id)
    act = request.form.get("action")
    if act == "approve":
        old = call.status
        call.status, call.needs_review, call.review_reason = "open", False, ""
        db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, field="status",
                                  old=old, new="open"))
        on_publish(call)
    elif act == "reviewed":
        call.needs_review, call.review_reason = False, ""
        call.last_verified = today().isoformat()
    elif act == "archive":
        db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, field="status",
                                  old=call.status, new="archived"))
        call.status = "archived"
    elif act == "delete":
        # Permanent: also removes its change history, subscriptions and reminder records.
        current_app.logger.warning("entry #%s '%s' deleted by %s (%s subscribers)", call.id,
                                   call.title_en or call.title_lt, current_user.email, len(call.subscriptions))
        db.session.delete(call)
        db.session.commit()
        flash(tr("Deleted."), "ok")
        return redirect(safe_next(request.form.get("next"), url_for(".dashboard")))
    elif act == "recheck":
        ch = check_call(call)
        flash(tr("Re-checked:") + " " + (", ".join(ch) if ch else tr("no changes")), "ok")
    db.session.commit()
    return redirect(safe_next(request.form.get("next"), url_for(".dashboard")))


@bp.route("/import-data", methods=["POST"])
@admin_required
def import_data():
    """Upload the weekly MISC-sarasas-<date>.html (or its JSON) to merge the curator's list."""
    f = request.files.get("file")
    if not f:
        abort(400)
    try:
        payload = load_payload(f.read().decode("utf-8"))
        created, updated, skipped = import_payload(payload, drop_expired=True)
        flash(tr("Imported: {0} new, {1} updated, {2} expired skipped").format(created, updated, skipped), "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for(".dashboard"))


@bp.route("/refresh", methods=["POST"])
@admin_required
def refresh():
    run = run_refresh(limit=int(request.form.get("limit", 10)))
    flash(tr("Checked {0}, changed {1}, errors {2}").format(run.checked, run.changed, run.errors), "ok")
    return redirect(url_for(".dashboard"))


@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        u = db.get_or_404(User, int(request.form["user_id"]))
        if u.id != current_user.id:
            u.is_admin = not u.is_admin
            db.session.commit()
    return render_template("admin/users.html", users=User.query.order_by(User.created_at.desc()).all())



# ---------------------------------------------------------------- series

SERIES_FIELDS = ("name_lt", "name_en", "kind", "org", "url", "recurrence")


@bp.route("/series")
@admin_required
def series_list():
    rows = Series.query.order_by(Series.name_en).all()
    return render_template("admin/series_list.html", rows=rows, expected=expected_next,
                           suggestions=len(suggest_groups()))


def _form_to_series(s):
    for f in SERIES_FIELDS:
        setattr(s, f, (request.form.get(f) or "").strip())
    m = request.form.get("typical_month", "")
    s.typical_month = int(m) if m.isdigit() and 1 <= int(m) <= 12 else None
    s.active = request.form.get("active") == "on"


@bp.route("/series/new", methods=["GET", "POST"])
@bp.route("/series/<int:series_id>", methods=["GET", "POST"])
@admin_required
def series_edit(series_id=None):
    s = db.get_or_404(Series, series_id) if series_id else Series(recurrence="yearly", active=True)
    if request.method == "POST":
        _form_to_series(s)
        if not (s.name_lt or s.name_en):
            flash(tr("A name is required."), "error")
            return render_template("admin/series_form.html", s=s, expected=expected_next)
        if not s.id:
            db.session.add(s)
        db.session.commit()
        flash(tr("Saved."), "ok")
        return redirect(url_for(".series_edit", series_id=s.id))
    unlinked = (Call.query.filter(Call.series_id.is_(None), Call.is_placeholder.is_(False))
                .order_by(Call.title_en).all() if s.id else [])
    return render_template("admin/series_form.html", s=s, expected=expected_next, unlinked=unlinked)


@bp.route("/series/<int:series_id>/action", methods=["POST"])
@admin_required
def series_action(series_id):
    s = db.get_or_404(Series, series_id)
    act = request.form.get("action")
    if act == "check":
        found = check_series(s)
        db.session.commit()
        flash(tr("Series page checked: {0} new call(s) found (waiting for approval).").format(len(found)), "ok")
    elif act == "link":
        ids = [int(x) for x in request.form.getlist("call_id") if x.isdigit()]
        for c in Call.query.filter(Call.id.in_(ids)).all():
            c.series_id = s.id
            db.session.add(CallChange(call_id=c.id, origin="admin", user_id=current_user.id, field="series_id",
                                      new=str(s.id)))
        db.session.commit()
        flash(tr("{0} entries added to the series.").format(len(ids)), "ok")
    elif act == "unlink":
        c = db.get_or_404(Call, int(request.form["call_id"]))
        if c.is_placeholder:
            db.session.delete(c)
        else:
            c.series_id = None
        db.session.commit()
    elif act == "delete":
        for c in list(s.calls):
            if c.is_placeholder:
                db.session.delete(c)
            else:
                c.series_id = None
        db.session.delete(s)
        db.session.commit()
        flash(tr("Series deleted; its entries were kept."), "ok")
        return redirect(url_for(".series_list"))
    return redirect(url_for(".series_edit", series_id=s.id))


@bp.route("/series/suggestions", methods=["GET", "POST"])
@admin_required
def series_suggestions():
    """Entries without a series grouped by website — create a series from a group in one click."""
    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("call_id") if x.isdigit()]
        calls = Call.query.filter(Call.id.in_(ids)).all()
        if calls:
            first = max(calls, key=lambda c: c.deadline or today())
            s = Series(name_lt=request.form.get("name_lt") or series_name_from(first, "lt"),
                       name_en=request.form.get("name_en") or series_name_from(first, "en"),
                       kind=first.kind, org=first.org, url=request.form.get("url") or first.url,
                       recurrence=request.form.get("recurrence") or "yearly", active=True)
            db.session.add(s)
            db.session.flush()
            for c in calls:
                c.series_id = s.id
            db.session.commit()
            flash(tr("Series created — check its page address (where new calls appear)."), "ok")
            return redirect(url_for(".series_edit", series_id=s.id))
    groups = suggest_groups()
    return render_template("admin/series_suggest.html", groups=groups, name_from=series_name_from)


@bp.route("/call/<int:call_id>/make-series", methods=["POST"])
@admin_required
def make_series(call_id):
    c = db.get_or_404(Call, call_id)
    s = Series(name_lt=series_name_from(c, "lt"), name_en=series_name_from(c, "en"), kind=c.kind, org=c.org,
               url=c.url, recurrence="yearly", active=True)
    db.session.add(s)
    db.session.flush()
    c.series_id = s.id
    db.session.commit()
    flash(tr("Series created from this entry — check its name and page address."), "ok")
    return redirect(url_for(".series_edit", series_id=s.id))
