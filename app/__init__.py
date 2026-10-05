import logging
from datetime import date
from pathlib import Path

from flask import Flask, render_template
from flask_login import current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

from .i18n import get_lang, tr
from .messages import render as render_msg
from .models import URGENT_DAYS, Series, db
from .taxonomy import COUNTRIES, FAMILIES, KIND_ORDER, KINDS, REGIONS, TOPICS, country_name, topic_label

csrf = CSRFProtect()
migrate = Migrate()


def create_app(config=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    logging.basicConfig(level=logging.INFO)
    if app.config["DEV_LOGIN"] and not (app.debug or app.testing):
        app.logger.warning("DEV_LOGIN ignored: only allowed with --debug or in tests")
        app.config["DEV_LOGIN"] = False

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from .auth import bp as auth_bp, login_manager
    from .views import bp as main_bp
    from .admin import bp as admin_bp
    login_manager.init_app(app)
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    from .cli import register
    register(app)

    @app.context_processor
    def inject():
        lang = get_lang()
        return dict(lang=lang, _=lambda s: tr(s, lang), KINDS=KINDS, KIND_ORDER=KIND_ORDER, TOPICS=TOPICS,
                    FAMILIES=FAMILIES, REGIONS=REGIONS, COUNTRIES=COUNTRIES, topic_label=topic_label,
                    country_name=country_name, today=date.today(), URGENT_DAYS=URGENT_DAYS, user=current_user,
                    SERIES_ALL=lambda: Series.query.order_by(Series.name_en).all())

    @app.template_filter("fmtdate")
    def fmtdate(d, lang="lt"):
        if not d:
            return ""
        if lang == "lt":
            return d.isoformat()
        return f"{d.day} {d.strftime('%b %Y')}"

    @app.template_filter("sysmsg")
    def sysmsg(text):
        return render_msg(text, get_lang())

    @app.template_filter("firstseen")
    def firstseen(text):
        # The curator's data uses "YYYY-MM-DD ar anksčiau" (= "or earlier").
        return (text or "").replace(" ar anksčiau", " " + tr("or earlier", get_lang()))

    @app.template_filter("flag")
    def flag(code):
        code = (code or "").upper()
        if len(code) == 2 and code.isalpha() and code != "XX":
            return "".join(chr(127397 + ord(ch)) for ch in code)
        return "🌐"

    for code in (403, 404):
        app.register_error_handler(code, lambda e, code=code: (render_template("error.html", code=code, e=e), code))

    if app.config["ENABLE_SCHEDULER"]:
        from .scheduler import start
        start(app)
    return app
