"""iCalendar output: one file per call, a file for any filtered list, and subscribable feeds.

Each call becomes an all-day "Deadline" event with reminders 7 days and 1 day before; if the
event itself has dates, a second event is added. UIDs are stable, so calendar apps that
subscribe to a feed update the entry in place when the deadline changes."""
from datetime import datetime, timedelta, timezone

from flask import Response, current_app, url_for
from icalendar import Alarm, Calendar, Event

from .i18n import tr


def _alarm(days, text):
    a = Alarm()
    a.add("action", "DISPLAY")
    a.add("description", text)
    a.add("trigger", timedelta(days=-days))
    return a


def build_calendar(calls, lang="lt", name=None):
    cal = Calendar()
    cal.add("prodid", "-//LMTA MISC//Open Calls//LT")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name or tr("MISC open calls", lang))
    cal.add("x-wr-timezone", "Europe/Vilnius")
    cal.add("refresh-interval", timedelta(hours=12), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT12H")
    domain = current_app.config["ICS_UID_DOMAIN"]
    stamp = datetime.now(timezone.utc)
    for c in calls:
        link = url_for("main.detail", call_id=c.id, _external=True)
        body = "\n\n".join(x for x in [c.desc(lang), c.org_name(lang), f"{tr('Official page', lang)}: {c.url}", f"MISC: {link}"] if x)
        if c.deadline:
            ev = Event()
            ev.add("uid", f"call-{c.id}-deadline@{domain}")
            ev.add("dtstamp", stamp)
            ev.add("last-modified", c.updated_at.replace(tzinfo=timezone.utc) if c.updated_at else stamp)
            ev.add("summary", f"⏰ {tr('Deadline', lang)}: {c.title(lang)}")
            ev.add("dtstart", c.deadline)
            ev.add("dtend", c.deadline + timedelta(days=1))
            ev.add("description", body)
            ev.add("url", c.url or link)
            loc = ", ".join(x for x in [c.city(lang), c.country(lang)] if x)
            if loc:
                ev.add("location", loc)
            ev.add("categories", [c.kind])
            ev.add("transp", "TRANSPARENT")
            ev.add_component(_alarm(7, f"{tr('Deadline in 7 days', lang)}: {c.title(lang)}"))
            ev.add_component(_alarm(1, f"{tr('Deadline tomorrow', lang)}: {c.title(lang)}"))
            cal.add_component(ev)
        if c.event_start:
            ev = Event()
            ev.add("uid", f"call-{c.id}-event@{domain}")
            ev.add("dtstamp", stamp)
            ev.add("summary", c.title(lang))
            ev.add("dtstart", c.event_start)
            ev.add("dtend", (c.event_end or c.event_start) + timedelta(days=1))
            ev.add("description", body)
            ev.add("url", c.url or link)
            ev.add("transp", "TRANSPARENT")
            cal.add_component(ev)
    return cal


def ics_response(calls, filename, lang="lt", name=None, attachment=True):
    data = build_calendar(calls, lang, name).to_ical()
    disp = "attachment" if attachment else "inline"
    return Response(data, mimetype="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'{disp}; filename="{filename}"'})
