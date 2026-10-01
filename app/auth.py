"""Microsoft Entra ID (Azure AD) login for LMTA institutional accounts, via MSAL auth-code flow.

Register an app in the LMTA tenant (Entra admin centre → App registrations):
  * Redirect URI (Web): https://<host>/auth/callback
  * Client secret → MS_CLIENT_SECRET; Application (client) ID → MS_CLIENT_ID; Directory (tenant) ID → MS_TENANT_ID
  * API permissions: Microsoft Graph → delegated `User.Read` (default) is enough.
"""
import re
from urllib.parse import urlencode, urlparse

import msal
from flask import Blueprint, abort, current_app, flash, redirect, request, session, url_for
from flask_login import LoginManager, login_user, logout_user

from .i18n import tr
from .models import User, db, utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


@login_manager.unauthorized_handler
def unauthorized():
    flash(tr("Please log in first."), "error")
    return redirect(url_for("auth.login", next=request.full_path))


def _is_guid(value):
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", value or ""))


def _msal_app():
    cfg = current_app.config
    return msal.ConfidentialClientApplication(
        cfg["MS_CLIENT_ID"], client_credential=cfg["MS_CLIENT_SECRET"],
        authority=f"https://login.microsoftonline.com/{cfg['MS_TENANT_ID']}")


def safe_next(target, fallback=None):
    """Only allow local paths; app-relative paths get the mount prefix (e.g. /open-calls) added."""
    fallback = fallback or url_for("main.index")
    if not target or not target.startswith("/") or target.startswith("//"):
        return fallback
    p = urlparse(target)
    if p.netloc or p.scheme:
        return fallback
    root = request.script_root
    return target if not root or target == root or target.startswith(root + "/") else root + target


def _finish_login(email, name, oid=None, tid=None):
    email = email.lower().strip()
    domains = current_app.config["ALLOWED_EMAIL_DOMAINS"]
    if domains and email.rsplit("@", 1)[-1] not in domains:
        flash(tr("Only institutional accounts can log in."), "error")
        return redirect(url_for("main.index"))
    user = (User.query.filter_by(ms_oid=oid).first() if oid else None) or User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email)
        db.session.add(user)
    user.email, user.name = email, name or user.name
    user.ms_oid, user.ms_tid = oid or user.ms_oid, tid or user.ms_tid
    if email in current_app.config["ADMIN_EMAILS"]:
        user.is_admin = True
    user.last_login_at = utcnow()
    if session.get("lang"):
        user.lang = session["lang"]
    db.session.commit()
    login_user(user, remember=True)
    return redirect(session.pop("login_next", None) or url_for("main.index"))


@bp.route("/login")
def login():
    session["login_next"] = safe_next(request.args.get("next"))
    if not current_app.config["MS_CLIENT_ID"]:
        if current_app.config["DEV_LOGIN"]:
            return redirect(url_for(".dev_login"))
        abort(503, "Microsoft login is not configured (MS_CLIENT_ID).")
    flow = _msal_app().initiate_auth_code_flow(
        ["User.Read"], redirect_uri=url_for(".callback", _external=True), prompt="select_account")
    session["auth_flow"] = flow
    return redirect(flow["auth_uri"])


@bp.route("/callback")
def callback():
    flow = session.pop("auth_flow", None)
    if not flow:
        return redirect(url_for(".login"))
    result = _msal_app().acquire_token_by_auth_code_flow(flow, request.args.to_dict())
    if "error" in result:
        current_app.logger.warning("MS login failed: %s", result.get("error_description"))
        flash(result.get("error_description", "Login failed"), "error")
        return redirect(url_for("main.index"))
    claims = result.get("id_token_claims", {})
    tenant = current_app.config["MS_TENANT_ID"]
    # MS_TENANT_ID may be the Directory (tenant) ID (a GUID) or a domain such as lmta.lt. The token's
    # `tid` claim is always the GUID, so only compare when a GUID was configured; with a domain, the
    # authority URL already restricts sign-in to that tenant.
    if _is_guid(tenant) and claims.get("tid", "").lower() != tenant.lower():
        flash(tr("Only institutional accounts can log in."), "error")
        return redirect(url_for("main.index"))
    email = claims.get("email") or claims.get("preferred_username") or ""
    return _finish_login(email, claims.get("name", ""), claims.get("oid"), claims.get("tid"))


@bp.route("/dev-login", methods=["GET", "POST"])
def dev_login():
    """Local development only (DEV_LOGIN=1): log in as any email without Microsoft."""
    if not current_app.config["DEV_LOGIN"]:
        abort(404)
    if request.method == "POST":
        email = request.form.get("email", "")
        return _finish_login(email, email.split("@")[0])
    return (f'<form method="post" style="font:16px sans-serif;margin:3em">'
            f'<input type="hidden" name="csrf_token" value="{_csrf()}">'
            f'<p>DEV login (disable in production)</p><input name="email" value="admin@lmta.lt" size="30"> '
            f'<button>Log in</button></form>')


def _csrf():
    from flask_wtf.csrf import generate_csrf
    return generate_csrf()


@bp.route("/logout")
def logout():
    logout_user()
    session.pop("auth_flow", None)
    tenant = current_app.config["MS_TENANT_ID"]
    if current_app.config["MS_CLIENT_ID"]:
        back = urlencode({"post_logout_redirect_uri": url_for("main.index", _external=True)})
        return redirect(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/logout?{back}")
    return redirect(url_for("main.index"))
