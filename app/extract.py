"""Turn a URL into a structured call entry.

1. fetch the organiser page (requests + BeautifulSoup, plus schema.org JSON-LD if present)
2. ask Claude to extract the fields using the MISC curation criteria (structured output)
3. if no API key is configured, fall back to a heuristic (title, meta description, date near "deadline")
"""
import hashlib
import json
import logging
import re
from datetime import date
from typing import List, Literal

import requests
from bs4 import BeautifulSoup
from flask import current_app
from pydantic import BaseModel, Field, create_model

from .messages import msg
from .taxonomy import KINDS, tax

log = logging.getLogger(__name__)

NOISE = re.compile(r"cookie|consent|gdpr|newsletter|banner|popup|modal", re.I)
UA = "Mozilla/5.0 (compatible; MISC-OpenCalls/1.0; +https://misc.lmta.lt)"
MAX_TEXT = 60_000


class Page(BaseModel):
    url: str
    final_url: str = ""
    status: int = 0
    title: str = ""
    description: str = ""
    text: str = ""
    jsonld: str = ""
    error: str = ""

    @property
    def blocked(self):
        """Bot protection (Cloudflare & co.) or access denied: the text is not the real page."""
        if self.status in (401, 403, 429, 503):
            return True
        t = f"{self.title} {self.text[:300]}".lower()
        return any(s in t for s in ("just a moment", "attention required", "are you a robot",
                                    "verify you are human", "captcha", "access denied"))

    @property
    def content_hash(self):
        # Hash the main visible text only (menus, footers, banners removed in fetch), so rotating
        # ads, tokens in markup or a changed menu don't count as a change.
        norm = re.sub(r"\s+", " ", self.text).strip()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else ""


def fetch(url, timeout=25):
    p = Page(url=url)
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en,lt;q=0.8,de;q=0.5"},
                         timeout=timeout, allow_redirects=True)
        p.status, p.final_url = r.status_code, r.url
        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype:
            p.error = "PDF document — open manually"
            return p
        r.encoding = r.encoding or r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        p.title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            p.title = og["content"].strip()
        md = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if md and md.get("content"):
            p.description = md["content"].strip()
        p.jsonld = "\n".join(s.get_text() for s in soup.find_all("script", type="application/ld+json"))[:8000]
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "nav", "header", "footer", "aside"]):
            tag.decompose()
        # cookie / consent / newsletter banners change often and say nothing about the call
        for tag in soup.find_all(attrs={"id": NOISE}) + soup.find_all(attrs={"class": NOISE}):
            if not tag.decomposed:
                tag.decompose()
        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
        text = (main if main and len(main.get_text(strip=True)) > 200 else soup).get_text("\n")
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        p.text = re.sub(r"[ \t]+", " ", text).strip()[:MAX_TEXT]
    except requests.RequestException as e:
        p.error = str(e)[:300]
    return p


KindLit = Literal[tuple(KINDS)]


class Extraction(BaseModel):
    is_call: bool = Field(description="True if the page announces an open call / CFP / competition / residency / academy / funding scheme")
    status: Literal["open", "watch", "reject", "closed"] = Field(
        description="open = accepting applications now; watch = announced but not yet open / next edition expected; "
                    "reject = open but does not fit MISC or LT/EU applicants cannot apply; closed = deadline passed")
    kind: KindLit
    url: str = Field(description="The most specific link to this call shown on the page, or empty")
    title_en: str
    title_lt: str = Field(description="Natural Lithuanian translation of the title")
    org: str = Field(description="Organiser as written in Lithuanian (proper names unchanged; translate generic words, "
                                 "e.g. 'Universität Wien' stays, 'Faculty of Music' → 'Muzikos fakultetas')")
    org_en: str = Field(description="Organiser in English / original form")
    city_en: str
    city_lt: str
    country_en: str
    country_lt: str
    country_code: str = Field(description="ISO 3166-1 alpha-2, or XX for online / international / various")
    deadline: str = Field(description="Submission deadline YYYY-MM-DD, empty if none/rolling/unknown")
    deadline_word_en: str = Field(description="Short (<=30 chars) wording when there is no exact deadline, e.g. 'Rolling', 'Not announced'")
    deadline_word_lt: str
    event_start: str = Field(description="Event/residency start YYYY-MM-DD or empty")
    event_end: str = Field(description="Event/residency end YYYY-MM-DD or empty")
    desc_en: str = Field(description="1–2 sentences, max 165 characters")
    desc_lt: str = Field(description="Same in Lithuanian, max 165 characters")
    topics: List[str] = Field(description="2–4 sub-discipline keys from the taxonomy")
    fields: List[str] = Field(description="1–2 field keys: every field the call is meant for")
    kam_tinka: str = Field(description="LT: who is eligible; state restrictions (nationality, age, residency, degree level) explicitly")
    nauda: str = Field(description="LT: concrete benefit for an LMTA student/researcher")
    mokestis: str = Field(description="LT: application/participation fee, or 'Nemokama' / 'Nenurodyta'")
    amzius: str = Field(description="LT: age limits or 'Ribų nėra' / 'Nenurodyta'")
    padengiama: str = Field(description="LT: what is covered (travel, accommodation, fee, prize) or 'Nenurodyta'")
    nuotoliu: str = Field(description="LT, conferences only: remote participation possible? else empty")
    registracija: str = Field(description="LT, conferences only: registration fee, else empty")
    studentu_nuolaida: str = Field(description="LT, conferences only: student discount, else empty")
    note: str = Field(description="LT: caveats, visa/travel/funding reality for academies & residencies, reasons for reject")
    kam_tinka_en: str = Field(description="English version of kam_tinka")
    nauda_en: str = Field(description="English version of nauda")
    mokestis_en: str = Field(description="English version of mokestis ('Free' / 'Not stated')")
    amzius_en: str = Field(description="English version of amzius ('No limits' / 'Not stated')")
    padengiama_en: str = Field(description="English version of padengiama")
    nuotoliu_en: str = Field(description="English version of nuotoliu (conferences only, else empty)")
    registracija_en: str = Field(description="English version of registracija (conferences only, else empty)")
    studentu_nuolaida_en: str = Field(description="English version of studentu_nuolaida (conferences only, else empty)")
    note_en: str = Field(description="English version of note")
    star: bool = Field(description="True only for an exceptionally good fit for MISC students/researchers")
    confidence: Literal["high", "medium", "low"]


SYSTEM_PROMPT = """You curate open calls for the Music Innovation Studies Centre (MISC) of the
Lithuanian Academy of Music and Theatre (LMTA, Vilnius). Audience: BA/MA/PhD students, teachers,
artists, doctoral and post-doctoral researchers.

SCOPE: media art, digital music and sound art, AI art, interactive art; electroacoustic music, sonic
arts; music technology, sound research, installations; art-science-technology, experimental media,
hybrid theory/practice; immersive/spatial/VR-AR audio, 3D sound; computer music, algorithmic
composition, electronic music; traditional and instrumental composition; musicology, artistic
research, music psychology, performance studies.

GEOGRAPHY:
- Conferences, symposia, calls for papers and journal special issues: worldwide, any format (online,
  one-day, doctoral colloquia).
- Academies, workshops, summer courses and residencies: worldwide, but a Lithuanian/EU resident must
  realistically be able to take part. Always state visa, travel and funding reality in `note`.
- Competitions, festivals, mobility: EU + Erasmus+ programme countries + CH, NO, IS, UK only. Outside
  that region, use status "reject" and explain.

ELIGIBILITY TRAPS (use status "reject" and state it clearly): calls limited to residents of a single
country or city; schemes excluding BA/MA students where that matters; mobility schemes that exclude
study-related travel; members-only calls; paid online "certificate" competitions.

RULES: only report what the page actually says; never invent dates. If the page is an aggregator,
say so in `note`. Dates are ISO YYYY-MM-DD. Fields marked LT are written in Lithuanian and each has an
*_en English counterpart with the same content; other fields are bilingual as named. Keep desc_* under 165 characters and title_lt under 78 characters."""


def _client():
    import anthropic
    key = current_app.config.get("ANTHROPIC_API_KEY")
    # Organisation-level API keys (not scoped to one workspace) must say which workspace to bill.
    workspace = current_app.config.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(api_key=key, default_headers=headers) if key else anthropic.Anthropic(default_headers=headers)


def parse_with_fallback(**kwargs):
    """Structured-output request with the API's server-side refusal fallback enabled."""
    import anthropic
    client = _client()
    try:
        return client.beta.messages.parse(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError as e:
        log.warning("Fallback request rejected (%s); retrying without fallbacks", e.message)
        return client.beta.messages.parse(**kwargs)


def llm_available():
    return bool(current_app.config.get("ANTHROPIC_API_KEY"))


def extraction_model():
    """Extraction with the CURRENT taxonomy as enums (admins can edit fields / sub-disciplines)."""
    t = tax()
    topics = tuple(d.key for d in t.disciplines) or ("research",)
    fields = tuple(f.key for f in t.fields) or ("music",)
    return create_model("Extraction", __base__=Extraction,
                        topics=(List[Literal[topics]], Field(description="2–4 sub-discipline keys from the taxonomy")),
                        fields=(List[Literal[fields]], Field(description="1–2 field keys: every field the call is meant for")))


def taxonomy_brief():
    """The tree as text for the prompt: keys with names, grouped field → category."""
    t = tax()
    lines = ["Taxonomy (choose keys): fields → categories → sub-disciplines."]
    for f, cats in t.grouped():
        lines.append(f"FIELD {f.key} = {f.name_en}" if f else "SHARED (any field):")
        for c, discs in cats:
            lines.append(f"  {c.name_en}: " + ", ".join(f"{d.key} ({d.name_en})" for d in discs))
    return "\n".join(lines)


def extract_with_claude(page: Page, previous: dict | None = None) -> Extraction | None:
    today = date.today().isoformat()
    parts = [f"Today is {today}.", f"URL: {page.final_url or page.url}", f"Page title: {page.title}"]
    if page.description:
        parts.append(f"Meta description: {page.description}")
    if page.jsonld:
        parts.append(f"JSON-LD:\n{page.jsonld}")
    if previous:
        parts.append("The entry is already in the database with these values; re-check them against the "
                     "page and report the current state (keep fields the page does not contradict):\n"
                     + json.dumps(previous, ensure_ascii=False))
    parts.append(taxonomy_brief())
    parts.append(f"Page text:\n{page.text}")
    kwargs = dict(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        output_format=extraction_model(),
        output_config={"effort": current_app.config["CLAUDE_EFFORT"]},
    )
    resp = parse_with_fallback(**kwargs)
    if resp.stop_reason == "refusal":
        log.warning("Extraction refused for %s", page.url)
        return None
    return resp.parsed_output


DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
]
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
WORD_DATE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\.?,?\s+(\d{4})|(" + "|".join(MONTHS)
                       + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)


def _dates_in(s):
    out = []
    for rx, fn in DATE_PATTERNS:
        for m in rx.finditer(s):
            try:
                out.append(date(*fn(m)))
            except ValueError:
                pass
    for m in WORD_DATE.finditer(s):
        try:
            if m[1]:
                out.append(date(int(m[3]), MONTHS[m[2].lower()], int(m[1])))
            else:
                out.append(date(int(m[6]), MONTHS[m[4].lower()], int(m[5])))
        except ValueError:
            pass
    return out


def heuristic(page: Page) -> dict:
    """No-LLM fallback: title, description and the first future date near 'deadline'."""
    deadline = None
    for m in re.finditer(r"(deadline|submission|apply by|due|terminas|closing date|bewerbungsschluss)", page.text, re.I):
        window = page.text[m.start(): m.start() + 160]
        future = [d for d in _dates_in(window) if d >= date.today()]
        if future:
            deadline = future[0]
            break
    return {
        "title_en": page.title[:400], "desc_en": page.description[:500], "url": page.final_url or page.url,
        "deadline": deadline.isoformat() if deadline else "", "status": "open" if deadline else "watch",
        "review": msg("heuristic"),
    }


def _describe(e):
    """Short, readable reason for an API failure (shown to admins)."""
    body = getattr(e, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return f"HTTP {getattr(e, 'status_code', '?')} {body['error'].get('type', '')}: {body['error'].get('message', '')}"[:300]
    return f"{type(e).__name__}: {e}"[:300]


def extract_url(url, pasted_text=""):
    """Returns (fields: dict, page: Page, used_llm: bool).

    `pasted_text`: the page's text copied from a browser, for sites that block automated access.
    When something goes wrong, fields["problem"] = (code, detail) with code in
    blocked | unreachable | no_api_key | llm_failed | llm_refused."""
    if pasted_text.strip():
        page = Page(url=url, final_url=url, status=200, text=pasted_text.strip()[:MAX_TEXT])
    else:
        page = fetch(url)
        if page.error and not page.text:
            return {"url": url, "review": msg("page_unreachable", error=page.error),
                    "problem": ("unreachable", page.error)}, page, False
        if page.blocked:
            data = {"url": url}
            data.update(review=msg("site_blocked", status=str(page.status)), problem=("blocked", str(page.status)))
            return data, page, False
    if not llm_available():
        data = heuristic(page)
        data["problem"] = ("no_api_key", "")
        return data, page, False
    try:
        ex = extract_with_claude(page)
        if ex:
            data = ex.model_dump()
            data["url"] = page.final_url or url
            return data, page, True
        problem = ("llm_refused", "")
    except Exception as e:  # network/API errors must not break the admin form
        log.exception("Claude extraction failed: %s", e)
        problem = ("llm_failed", _describe(e))
    data = heuristic(page)
    data["problem"] = problem
    return data, page, False
