"""Search and filtering shared by the HTML list, the JSON API and the calendar exports."""
from collections import Counter
from datetime import date

from sqlalchemy import or_

from .importer import parse_date
from .models import Call, Subscription
from .taxonomy import TOPICS

SHOW = {  # "show" filter -> phases included
    "active": {"due_today", "closing_soon", "open", "rolling", "upcoming"},
    "urgent": {"due_today", "closing_soon"},
    "open": {"due_today", "closing_soon", "open", "rolling"},
    "upcoming": {"upcoming"},
    "closed": {"closed"},
    "rejected": {"rejected"},
    "all": {"due_today", "closing_soon", "open", "rolling", "upcoming", "closed", "rejected"},
}
TEXT_COLUMNS = [Call.title_en, Call.title_lt, Call.org, Call.org_en, Call.desc_en, Call.desc_lt, Call.kam_tinka,
                Call.nauda, Call.note, Call.city_en, Call.city_lt, Call.country_en, Call.country_lt, Call.url]


class Filters:
    def __init__(self, args, user=None):
        self.q = (args.get("q") or "").strip()
        self.kinds = [k for k in args.getlist("kind") if k]
        self.topics = [t for t in args.getlist("topic") if t]
        self.family = args.get("family") or ""
        self.region = args.get("region") or ""
        self.country = (args.get("country") or "").upper()
        self.show = args.get("show") if args.get("show") in SHOW else "active"
        self.date_from = parse_date(args.get("from"))
        self.date_to = parse_date(args.get("to"))
        self.star = args.get("star") == "1"
        self.remote = args.get("remote") == "1"
        self.free = args.get("free") == "1"
        self.mine = args.get("mine") == "1" and user is not None and user.is_authenticated
        self.sort = args.get("sort") if args.get("sort") in ("deadline", "new", "title") else "deadline"
        self.user = user

    @property
    def is_default(self):
        return not any([self.q, self.kinds, self.topics, self.family, self.region, self.country, self.date_from,
                        self.date_to, self.star, self.remote, self.free, self.mine]) and self.show == "active"


def _base_query(f: Filters):
    q = Call.query.filter(Call.status.in_(["open", "watch", "reject", "archived"]))
    if f.q:
        for word in f.q.split():
            like = f"%{word}%"
            q = q.filter(or_(*[col.ilike(like) for col in TEXT_COLUMNS]))
    for t in f.topics:
        q = q.filter(Call.topics.like(f"%,{t},%"))
    if f.country:
        q = q.filter(Call.country_code == f.country)
    if f.star:
        q = q.filter(Call.star.is_(True))
    if f.date_from:
        q = q.filter(Call.deadline >= f.date_from)
    if f.date_to:
        q = q.filter(Call.deadline <= f.date_to)
    if f.mine:
        q = q.join(Subscription, Subscription.call_id == Call.id).filter(Subscription.user_id == f.user.id)
    return q


def _python_filters(calls, f: Filters, ref):
    phases = SHOW[f.show]
    out = []
    for c in calls:
        if c.phase(ref) not in phases:
            continue
        if f.region and c.region != f.region:
            continue
        if f.family and not any(TOPICS.get(t, ("",))[0] == f.family for t in c.topic_list):
            continue
        if f.remote and not c.remote_possible:
            continue
        if f.free and not c.is_free:
            continue
        out.append(c)
    return out


def sort_calls(calls, how, lang="lt", ref=None):
    ref = ref or date.today()
    if how == "new":
        return sorted(calls, key=lambda c: c.created_at or ref, reverse=True)
    if how == "title":
        return sorted(calls, key=lambda c: c.title(lang).lower())
    order = {"due_today": 0, "closing_soon": 0, "open": 0, "rolling": 1, "upcoming": 2, "closed": 3, "rejected": 4}
    return sorted(calls, key=lambda c: (order.get(c.phase(ref), 5), c.key_date or date.max, not c.star))


def run_search(f: Filters, lang="lt"):
    """Returns (calls, kind_counts)."""
    ref = date.today()
    rows = _python_filters(_base_query(f).all(), f, ref)
    kind_counts = Counter(c.kind for c in rows)
    if f.kinds:
        rows = [c for c in rows if c.kind in f.kinds]
    return sort_calls(rows, f.sort, lang, ref), kind_counts
