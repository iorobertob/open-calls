import re
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
from .series import (expected_next, link_series, move_to_series, notify_change, on_publish, redistribute,
                     series_name_from, suggest_groups)
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
    if "fields" in request.form or request.form.get("title_en") is not None:
        fields = request.form.getlist("fields")
        if fields != call.field_list:
            changes.append(("fields", ",".join(call.field_list), ",".join(fields)))
            call.field_list = fields          # implied fields are added again on save (sync_fields)
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
    s.is_aggregator = request.form.get("is_aggregator") == "on"


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
    # every entry not in this series (also those in other series — choosing one moves it here)
    unlinked = (Call.query.filter((Call.series_id.is_(None)) | (Call.series_id != s.id), Call.is_placeholder.is_(False),
                                  Call.status != "archived")
                .order_by(Call.series_id.isnot(None), Call.title_en).all() if s.id else [])
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
            move_to_series(c, s, user_id=current_user.id)
        db.session.commit()
        flash(tr("{0} entries added to the series.").format(len(ids)), "ok")
    elif act == "move":
        c = db.get_or_404(Call, int(request.form["call_id"]))
        tid = _int(request.form.get("target"))
        target = db.session.get(Series, tid) if tid else None     # 0 = no series
        move_to_series(c, target, user_id=current_user.id)
        db.session.commit()
        flash((tr("Moved to {0}.").format(target.name(get_lang())) if target else tr("Removed from the series.")), "ok")
    elif act == "redistribute":
        moved, loose = redistribute(s, user_id=current_user.id)
        db.session.commit()
        flash(tr("{0} entries moved to their own series, {1} left without a series.").format(moved, loose), "ok")
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


# ---------------------------------------------------------------- taxonomy (fields → categories → sub-disciplines)

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,38}$")


def _int(v, default=None, lo=None, hi=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        return default
    return n


def _names(obj):
    obj.name_lt = (request.form.get("name_lt") or "").strip()
    obj.name_en = (request.form.get("name_en") or "").strip()
    obj.position = _int(request.form.get("position"), obj.position or 0)
    return bool(obj.name_lt or obj.name_en)


def _new_key(model):
    key = (request.form.get("key") or "").strip().lower()
    if not KEY_RE.match(key):
        flash(tr("The key must be 2–39 lowercase letters, digits, - or _ (e.g. film-music)."), "error")
        return None
    if model.query.filter_by(key=key).first():
        flash(tr("This key is already used."), "error")
        return None
    return key


def _swap_key(attr, old, new):
    """Replace (or remove, when new is empty) a key in every entry's topics / fields list."""
    n = 0
    col = getattr(Call, attr)
    for c in Call.query.filter(col.like(f"%,{old},%")).all():
        lst = c.topic_list if attr == "topics" else c.field_list
        lst = [new if x == old else x for x in lst if new or x != old]
        lst = list(dict.fromkeys(x for x in lst if x))
        if attr == "topics":
            c.topic_list = lst
        else:
            c.field_list = lst
        n += 1
    return n


@bp.route("/taxonomy", methods=["GET", "POST"])
@admin_required
def taxonomy():
    from collections import Counter

    from .models import Category, Discipline, Field
    from .taxonomy import tax
    if request.method == "POST":
        act = request.form.get("action", "")
        oid = _int(request.form.get("id"))
        anchor = ""
        if act == "field_save":
            fl = db.get_or_404(Field, oid) if oid else Field()
            if not oid:
                fl.key = _new_key(Field)
                if not fl.key:
                    return redirect(url_for(".taxonomy"))
                db.session.add(fl)
            if not _names(fl):
                flash(tr("A name is required."), "error")
                return redirect(url_for(".taxonomy"))
            fl.hue = _int(request.form.get("hue"), fl.hue if fl.hue is not None else 212, 0, 359)
            anchor = f"f-{fl.key}"
        elif act == "field_delete":
            fl = db.get_or_404(Field, oid)
            target = Field.query.filter_by(key=request.form.get("move_to") or "").first()
            if target and target.id == fl.id:
                target = None
            key = fl.key
            for c in list(fl.categories):
                c.field_id = target.id if target else None
            db.session.delete(fl)
            db.session.flush()          # tree first, so the entries' field sync sees the new tree
            tax(refresh=True)
            n = _swap_key("fields", key, target.key if target else "")
            flash(tr("Field deleted; {0} entries updated.").format(n), "ok")
        elif act == "cat_save":
            c = db.get_or_404(Category, oid) if oid else Category()
            if not oid:
                c.key = _new_key(Category)
                if not c.key:
                    return redirect(url_for(".taxonomy"))
                db.session.add(c)
            if not _names(c):
                flash(tr("A name is required."), "error")
                return redirect(url_for(".taxonomy"))
            c.field_id = _int(request.form.get("field_id"))
            c.hue = _int(request.form.get("hue"), None, 0, 359)
            anchor = f"c-{c.key}"
        elif act == "cat_delete":
            c = db.get_or_404(Category, oid)
            target = db.session.get(Category, _int(request.form.get("move_to")) or 0)
            if c.disciplines and (not target or target.id == c.id):
                flash(tr("Choose another category for its sub-disciplines first."), "error")
                return redirect(url_for(".taxonomy", _anchor=f"c-{c.key}"))
            for d in list(c.disciplines):
                d.category_id = target.id
            db.session.delete(c)
            flash(tr("Category deleted."), "ok")
        elif act == "disc_save":
            d = db.get_or_404(Discipline, oid) if oid else Discipline()
            if not oid:
                d.key = _new_key(Discipline)
                if not d.key:
                    return redirect(url_for(".taxonomy"))
                db.session.add(d)
            if not _names(d):
                flash(tr("A name is required."), "error")
                return redirect(url_for(".taxonomy"))
            cid = _int(request.form.get("category_id"))
            if not cid or not db.session.get(Category, cid):
                flash(tr("Choose a category."), "error")
                return redirect(url_for(".taxonomy"))
            d.category_id = cid
            cat = db.session.get(Category, cid)
            anchor = f"c-{cat.key}"
        elif act == "disc_delete":
            d = db.get_or_404(Discipline, oid)
            repl = request.form.get("replace_with") or ""
            if repl == d.key or not Discipline.query.filter_by(key=repl).first():
                repl = ""
            key, cat = d.key, d.category
            db.session.delete(d)
            db.session.flush()
            tax(refresh=True)
            n = _swap_key("topics", key, repl)
            flash(tr("Sub-discipline deleted; {0} entries updated.").format(n), "ok")
            anchor = f"c-{cat.key}" if cat else ""
        db.session.commit()
        tax(refresh=True)
        if act.endswith("_save"):
            flash(tr("Saved."), "ok")
        return redirect(url_for(".taxonomy", _anchor=anchor) if anchor else url_for(".taxonomy"))

    t = tax(refresh=True)
    calls = Call.query.with_entities(Call.topics, Call.fields).all()
    topic_n = Counter(x for topics, _ in calls for x in (topics or "").split(",") if x)
    field_n = Counter(x for _, fields in calls for x in (fields or "").split(",") if x)
    return render_template("admin/taxonomy.html", t=t, topic_n=topic_n, field_n=field_n)


# ---------------------------------------------------------------- e-mail log and test e-mails

@bp.route("/emails")
@admin_required
def emails():
    from .models import EmailLog
    q = EmailLog.query
    status, kind, who = request.args.get("status", ""), request.args.get("kind", ""), request.args.get("q", "").strip()
    if status:
        q = q.filter(EmailLog.status == status)
    if kind:
        q = q.filter(EmailLog.kind == kind)
    if who:
        q = q.filter(EmailLog.to.ilike(f"%{who}%") | EmailLog.subject.ilike(f"%{who}%"))
    page = _int(request.args.get("page"), 1, 1)
    total = q.count()
    rows = q.order_by(EmailLog.at.desc()).offset((page - 1) * 100).limit(100).all()
    counts = {s: EmailLog.query.filter_by(status=s).count() for s in ("sent", "failed", "logged")}
    return render_template("admin/emails.html", rows=rows, total=total, page=page, pages=(total + 99) // 100,
                           status=status, kind=kind, who=who, counts=counts)


@bp.route("/emails/<int:email_id>")
@admin_required
def email_detail(email_id):
    from .models import EmailLog
    return render_template("admin/email_detail.html", e=db.get_or_404(EmailLog, email_id))


@bp.route("/emails/test", methods=["GET", "POST"])
@admin_required
def email_test():
    import smtplib

    from .notify import describe_smtp_error, send_test
    cfg = current_app.config
    users = (User.query.filter(User.subscriptions.any() | User.follows.any()).order_by(User.email).all())
    if request.method == "POST":
        to = (request.form.get("to") or "").strip()
        kind = request.form.get("kind", "simple")
        user = db.session.get(User, _int(request.form.get("user_id")) or 0) if kind == "user" else None
        if "@" not in to:
            flash(tr("Enter a valid e-mail address."), "error")
        elif kind == "user" and not user:
            flash(tr("Choose whose daily e-mail to preview."), "error")
        else:
            try:
                send_test(to, kind, user, get_lang())
                if cfg["MAIL_BACKEND"] == "smtp":
                    flash(tr("Test e-mail sent to {0}. If it does not arrive, check the spam folder and the log below.").format(to), "ok")
                else:
                    flash(tr("SMTP is not configured, so the e-mail was only written to the log (see below)."), "error")
            except (smtplib.SMTPException, OSError) as e:
                flash(tr("Sending failed:") + " " + describe_smtp_error(e), "error")
        return redirect(url_for(".email_test"))
    from .models import EmailLog
    recent = EmailLog.query.filter_by(kind="test").order_by(EmailLog.at.desc()).limit(10).all()
    smtp = {"backend": cfg["MAIL_BACKEND"], "host": cfg["SMTP_HOST"], "port": cfg["SMTP_PORT"],
            "user": cfg["SMTP_USERNAME"], "starttls": cfg["SMTP_STARTTLS"], "from": cfg["MAIL_FROM"],
            "reply_to": cfg["MAIL_REPLY_TO"], "password_set": bool(cfg["SMTP_PASSWORD"])}
    return render_template("admin/email_test.html", smtp=smtp, users=users, recent=recent)
