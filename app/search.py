"""Search and filtering shared by the HTML list, the JSON API and the calendar exports.

Taxonomy filters narrow step by step: field (Music and Sound, Theatre, …) → category → sub-disciplines
(several sub-disciplines = any of them). Counts for each level are computed with the levels below it
removed, so the explorer always shows how many results each choice would give."""
from collections import Counter
from datetime import date

from sqlalchemy import or_

from .importer import parse_date
from .models import Call, Subscription
from .taxonomy import tax

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
        self.field = args.get("field") or ""
        self.cat = args.get("cat") or args.get("family") or ""   # "family" = old links
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
        return not any([self.q, self.kinds, self.topics, self.field, self.cat, self.region, self.country, self.date_from,
                        self.date_to, self.star, self.remote, self.free, self.mine]) and self.show == "active"


def _base_query(f: Filters):
    q = Call.query.filter(Call.status.in_(["open", "watch", "reject", "archived"]))
    if f.q:
        for word in f.q.split():
            like = f"%{word}%"
            q = q.filter(or_(*[col.ilike(like) for col in TEXT_COLUMNS]))
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


def _in_field(c, f):
    return not f.field or f.field in c.field_list


def _in_cat(c, f, cat_topics):
    return not f.cat or any(t in cat_topics for t in c.topic_list)


def _in_topics(c, f):
    return not f.topics or any(t in f.topics for t in c.topic_list)


def run_search(f: Filters, lang="lt", facets=False):
    """Returns (calls, kind_counts) — or, with facets=True, (calls, counts) where counts has
    'kind', 'field', 'cat' and 'topic' Counters for the explorer."""
    ref = date.today()
    rows = _python_filters(_base_query(f).all(), f, ref)
    cat_topics = {d.key for d in tax().disciplines_in(f.cat)} if f.cat else set()
    by_kind = [c for c in rows if not f.kinds or c.kind in f.kinds]
    in_field = [c for c in by_kind if _in_field(c, f)]
    in_cat = [c for c in in_field if _in_cat(c, f, cat_topics)]
    result = [c for c in in_cat if _in_topics(c, f)]
    kind_counts = Counter(c.kind for c in rows if _in_field(c, f) and _in_cat(c, f, cat_topics) and _in_topics(c, f))
    if not facets:
        return sort_calls(result, f.sort, lang, ref), kind_counts
    t = tax()
    cat_counts = Counter()
    for c in in_field:
        for k in {t.category_of(x).key for x in c.topic_list if t.category_of(x)}:
            cat_counts[k] += 1
    counts = {"kind": kind_counts, "all": len(by_kind),
              "field": Counter(k for c in by_kind for k in c.field_list),
              "cat": cat_counts,
              "topic": Counter(x for c in in_cat for x in set(c.topic_list))}
    return sort_calls(result, f.sort, lang, ref), counts


class SeriesGroup:
    """A series with the (filtered, sorted) calls it contains — one card on the home page."""
    kind = "series"

    def __init__(self, series):
        self.series = series
        self.calls = []

    @property
    def lead(self):
        """The call that decides the card's deadline and badge: the first live one, else the first."""
        return next((c for c in self.calls if c.phase() not in ("closed", "rejected")), self.calls[0])

    @property
    def fields(self):
        out = []
        for c in self.calls:
            out += [f for f in c.field_list if f not in out]
        return out


def group_by_series(calls, view="series"):
    """Turn the sorted list of calls into home-page items, keeping the sort order:
    - a series card where its first matching call would be (listing pages don't count as series);
    - view "series": calls without a series go into one last group ("other");
    - view "all": calls without a series stay as normal cards in their place.
    Returns (items, n_series) where items are SeriesGroup, ("call", call) or ("other", [calls])."""
    items, groups, loose = [], {}, []
    for c in calls:
        s = c.series if c.series_id else None
        if s is not None and not s.is_aggregator:
            g = groups.get(s.id)
            if g is None:
                g = groups[s.id] = SeriesGroup(s)
                items.append(g)
            g.calls.append(c)
        elif view == "all":
            items.append(("call", c))
        else:
            loose.append(c)
    if loose:
        items.append(("other", loose))
    return items, len(groups)
