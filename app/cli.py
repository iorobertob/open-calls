from pathlib import Path

import click

from .importer import import_payload, load_payload
from .models import Call, User, db

SEED = Path(__file__).resolve().parent.parent / "seed"


def register(app):
    @app.cli.command("init-db")
    @click.option("--seed/--no-seed", default=True, help="Load the curator's initial list from seed/")
    def init_db(seed):
        """Create tables (dev convenience; use `flask db upgrade` in production) and seed."""
        db.create_all()
        click.echo("Tables created.")
        if seed and not Call.query.first():
            _import_files(sorted(SEED.glob("*.json")), drop_expired=False)

    @app.cli.command("import")
    @click.argument("paths", nargs=-1, type=click.Path(exists=True))
    @click.option("--drop-expired", is_flag=True, help="Skip entries whose deadline already passed")
    def import_cmd(paths, drop_expired):
        """Import/merge weekly MISC-sarasas-<date>.html or .json files."""
        _import_files([Path(p) for p in paths], drop_expired)

    @app.cli.command("refresh")
    @click.option("--limit", type=int, default=None)
    @click.option("--no-llm", is_flag=True, help="Only check links / archive; don't call Claude")
    def refresh_cmd(limit, no_llm):
        """Archive expired entries and re-check organiser pages (run daily from cron/systemd)."""
        from .refresh import run_refresh
        run = run_refresh(limit=limit, use_llm=not no_llm)
        click.echo(f"checked={run.checked} changed={run.changed} errors={run.errors}\n{run.log}")

    @app.cli.command("add-url")
    @click.argument("url")
    @click.option("--status", default="pending", type=click.Choice(["pending", "open", "watch"]))
    def add_url(url, status):
        """Extract a call from a link and store it (pending review by default)."""
        from datetime import date

        from .extract import extract_url
        from .importer import apply_record
        from .messages import msg
        from .views import to_record
        data, _, used = extract_url(url)
        from .duplicates import find_duplicates
        for d, why in find_duplicates(url, [data.get("title_en", ""), data.get("title_lt", "")]):
            click.echo(f"  ! possible duplicate ({why}): #{d.id} [{d.status}] {d.title_en or d.title_lt}")
        c = Call(first_seen=date.today().isoformat(), source="CLI add-url", url=url, needs_review=True,
                 review_reason=msg("added_cli"))
        apply_record(c, to_record(data))
        if status != "open" or c.status not in ("open", "watch", "reject"):
            c.status = status
        db.session.add(c)
        db.session.commit()
        from .translate import translate_call
        translate_call(c)
        click.echo(f"#{c.id} [{c.status}] {c.title_en} — deadline {c.deadline} (Claude: {used})")

    @app.cli.command("translate")
    @click.option("--limit", type=int, default=None, help="Max entries to process")
    @click.option("--dry-run", is_flag=True, help="Only count what is missing")
    def translate_cmd(limit, dry_run):
        """Fill missing Lithuanian/English versions of entry texts with Claude."""
        from .extract import llm_available
        from .translate import pending, translate_missing
        todo = pending(limit)
        fields = sum(len(c.missing_translations()) for c in todo)
        click.echo(f"{len(todo)} entries, {fields} fields missing a translation")
        if dry_run or not todo:
            return
        if not llm_available():
            raise click.ClickException("Set ANTHROPIC_API_KEY first.")
        n = translate_missing(limit, progress=lambda done, tot, n: click.echo(f"  {done}/{tot} entries, {n} fields"))
        click.echo(f"Translated {n} fields.")

    @app.cli.command("send-reminders")
    @click.option("--dry-run", is_flag=True, help="Show what would be sent without sending")
    def send_reminders_cmd(dry_run):
        """Email users about subscribed calls whose deadline is REMINDER_DAYS_BEFORE days away (run daily)."""
        from .reminders import send_reminders
        sent, failed = send_reminders(dry_run=dry_run)
        click.echo(f"{'would send' if dry_run else 'sent'}: {sent} users, failed: {failed}")
        if failed:
            raise SystemExit(1)

    @app.cli.command("mailerlite-setup")
    @click.option("--group-name", default="MISC open calls — deadline reminders")
    def mailerlite_setup(group_name):
        """Create the MailerLite custom fields (and the reminder group if MAILERLITE_REMINDER_GROUP_ID is empty)."""
        from flask import current_app

        from .mailer import MailerLite, create_group
        key = current_app.config["MAILERLITE_API_KEY"]
        if not key:
            raise click.ClickException("Set MAILERLITE_API_KEY in .env first.")
        gid = current_app.config["MAILERLITE_REMINDER_GROUP_ID"]
        if not gid:
            gid = create_group(key, group_name)
            click.echo(f"Created group '{group_name}'. Put this in .env:  MAILERLITE_REMINDER_GROUP_ID={gid}")
        created = MailerLite(key, gid).ensure_fields()
        click.echo(f"Custom fields created: {', '.join(created) or 'none (already present)'}")
        click.echo("Next: in MailerLite create an automation with trigger 'Joins a group' → this group, "
                   "tick 'Allow subscribers to re-enter automation', and design the email with "
                   "{$misc_reminder_subject}, {$misc_reminder_list} and {$misc_reminder_url}.")

    @app.cli.command("make-admin")
    @click.argument("email")
    def make_admin(email):
        """Grant admin rights (user is created if they have not logged in yet)."""
        u = User.query.filter_by(email=email.lower()).first() or User(email=email.lower())
        u.is_admin = True
        db.session.add(u)
        db.session.commit()
        click.echo(f"{u.email} is admin")


def _import_files(paths, drop_expired):
    for p in paths:
        payload = load_payload(p.read_text(encoding="utf-8"))
        c, u, s = import_payload(payload, drop_expired=drop_expired)
        click.echo(f"{p.name}: {c} new, {u} updated, {s} skipped")
