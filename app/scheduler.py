"""Optional in-process scheduler (ENABLE_SCHEDULER=1).

Use only with a single worker process; with several gunicorn workers prefer the cron/systemd
timer in deploy/ that runs `flask refresh`. A file lock prevents two processes running it at once."""
import fcntl
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)
_lock_handle = None


def start(app):
    global _lock_handle
    lock = Path(app.instance_path) / "scheduler.lock"
    _lock_handle = open(lock, "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info("Scheduler already running in another process")
        return

    def job():
        with app.app_context():
            from .refresh import run_refresh
            run = run_refresh()
            log.info("refresh: checked=%s changed=%s errors=%s", run.checked, run.changed, run.errors)

    sched = BackgroundScheduler(timezone="Europe/Vilnius")
    sched.add_job(job, "cron", hour=4, minute=15, id="refresh", coalesce=True, max_instances=1)
    sched.start()
    log.info("In-process scheduler started (daily 04:15 Europe/Vilnius)")
