from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .auth import safe_next
from .extract import extract_url, llm_available
from .i18n import get_lang, tr
from .importer import apply_record, import_payload, load_payload, parse_date
from .models import DETAIL_FIELDS, STATUSES, Call, CallChange, RefreshRun, User, db, today
from .refresh import check_call, run_refresh
from .translate import pending as pending_translations
from .messages import msg
from .messages import render as render_msg
from .views import to_record

bp = Blueprint("admin", __name__, url_prefix="/admin")

TEXT_FIELDS = ["title_lt", "title_en", "org", "city_lt", "city_en", "country_lt", "country_en", "country_code",
               "deadline_word_lt", "deadline_word_en", "url", "desc_lt", "desc_en", "kam_tinka", "nauda",
               "mokestis", "amzius", "padengiama", "nuotoliu", "registracija", "studentu_nuolaida", "note",
               "source", "source_url", "first_seen", "last_verified",
               *[f + "_en" for f in DETAIL_FIELDS]]
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
                           stats=stats, llm=llm_available(), untranslated=len(pending_translations()))


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
        db.session.add(call)
        db.session.flush()
        db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, note=msg("created")))
        db.session.commit()
        flash(tr("Saved."), "ok")
        return redirect(url_for("main.detail", call_id=call.id))
    return render_template("admin/form.html", c=call)


@bp.route("/import-url", methods=["POST"])
@admin_required
def import_url():
    """Fetch a link, extract its fields and show the pre-filled form for review before saving."""
    url = (request.form.get("url") or "").strip()
    dup = Call.query.filter_by(url=url).first()
    if dup:
        flash(tr("Already in the database:") + f" #{dup.id} {dup.title(get_lang())}", "error")
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
    return render_template("admin/form.html", c=call, extracted=True)


@bp.route("/call/<int:call_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(call_id):
    call = db.get_or_404(Call, call_id)
    if request.method == "POST":
        for f, old, new in _form_to_call(call):
            db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, field=f,
                                      old="" if old is None else str(old), new="" if new is None else str(new)))
        if request.form.get("clear_review") == "on":
            call.needs_review, call.review_reason = False, ""
        db.session.commit()
        flash(tr("Saved."), "ok")
        return redirect(url_for("main.detail", call_id=call.id))
    return render_template("admin/form.html", c=call)


@bp.route("/call/<int:call_id>/action", methods=["POST"])
@admin_required
def action(call_id):
    call = db.get_or_404(Call, call_id)
    act = request.form.get("action")
    if act == "approve":
        call.status, call.needs_review, call.review_reason = "open", False, ""
        db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, field="status",
                                  old="pending", new="open"))
    elif act == "reviewed":
        call.needs_review, call.review_reason = False, ""
        call.last_verified = today().isoformat()
    elif act == "archive":
        db.session.add(CallChange(call_id=call.id, origin="admin", user_id=current_user.id, field="status",
                                  old=call.status, new="archived"))
        call.status = "archived"
    elif act == "delete":
        db.session.delete(call)
        db.session.commit()
        flash(tr("Deleted."), "ok")
        return redirect(url_for(".dashboard"))
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

