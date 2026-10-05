"""Find entries that may be the same call as a new one, before it is saved.

Two signals: the same link (ignoring http/https, "www.", trailing slashes, #fragments and
tracking parameters) or a very similar title in either language. Several real calls can share
one page (e.g. impuls special programmes), so a match is a warning for the admin, not a block."""
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit

from .models import Call

TITLE_SIMILARITY = 0.85
TRACKING = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref)$", re.I)


def norm_url(url):
    if not url:
        return ""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", p.path) or ""
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k)))
    return f"{host}{path}" + (f"?{query}" if query else "")


def norm_title(title):
    t = unicodedata.normalize("NFKD", (title or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def _similar(a, b):
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 25 and (a in b or b in a)):
        return True
    return SequenceMatcher(None, a, b).ratio() >= TITLE_SIMILARITY


def find_duplicates(url="", titles=(), exclude_id=None):
    """Returns [(call, reason)] — reason is "link" or "title"."""
    u = norm_url(url)
    new_titles = [norm_title(t) for t in titles if t]
    out = []
    for c in Call.query.all():
        if exclude_id and c.id == exclude_id:
            continue
        if u and norm_url(c.url) == u:
            out.append((c, "link"))
        elif new_titles and any(_similar(n, norm_title(t)) for n in new_titles for t in (c.title_en, c.title_lt) if t):
            out.append((c, "title"))
    return out
