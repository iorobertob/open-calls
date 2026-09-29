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
from pydantic import BaseModel, Field

from .taxonomy import KINDS, TOPICS

log = logging.getLogger(__name__)

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
    def content_hash(self):
        # Hash the visible text only, so rotating ads / tokens in markup don't count as changes.
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
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
            tag.decompose()
        text = soup.get_text("\n")
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        p.text = re.sub(r"[ \t]+", " ", text).strip()[:MAX_TEXT]
    except requests.RequestException as e:
        p.error = str(e)[:300]
    return p


KindLit = Literal[tuple(KINDS)]
TopicLit = Literal[tuple(TOPICS)]


class Extraction(BaseModel):
    is_call: bool = Field(description="True if the page announces an open call / CFP / competition / residency / academy / funding scheme")
    status: Literal["open", "watch", "reject", "closed"] = Field(
        description="open = accepting applications now; watch = announced but not yet open / next edition expected; "
                    "reject = open but does not fit MISC or LT/EU applicants cannot apply; closed = deadline passed")
    kind: KindLit
    title_en: str
    title_lt: str = Field(description="Natural Lithuanian translation of the title")
    org: str
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
    topics: List[TopicLit] = Field(description="2–4 topic keys")
    kam_tinka: str = Field(description="LT: who is eligible; state restrictions (nationality, age, residency, degree level) explicitly")
    nauda: str = Field(description="LT: concrete benefit for an LMTA student/researcher")
    mokestis: str = Field(description="LT: application/participation fee, or 'Nemokama' / 'Nenurodyta'")
    amzius: str = Field(description="LT: age limits or 'Ribų nėra' / 'Nenurodyta'")
    padengiama: str = Field(description="LT: what is covered (travel, accommodation, fee, prize) or 'Nenurodyta'")
    nuotoliu: str = Field(description="LT, conferences only: remote participation possible? else empty")
    registracija: str = Field(description="LT, conferences only: registration fee, else empty")
    studentu_nuolaida: str = Field(description="LT, conferences only: student discount, else empty")
    note: str = Field(description="LT: caveats, visa/travel/funding reality for academies & residencies, reasons for reject")
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
say so in `note`. Dates are ISO YYYY-MM-DD. Fields marked LT are written in Lithuanian; everything
else bilingual as named. Keep desc_* under 165 characters and title_lt under 78 characters."""


def _client():
    import anthropic
    key = current_app.config.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def llm_available():
    return bool(current_app.config.get("ANTHROPIC_API_KEY"))


def extract_with_claude(page: Page, previous: dict | None = None) -> Extraction | None:
    import anthropic
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
    parts.append(f"Page text:\n{page.text}")
    kwargs = dict(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        output_format=Extraction,
        output_config={"effort": current_app.config["CLAUDE_EFFORT"]},
    )
    client = _client()
    try:
        # Server-side fallback: if the primary model declines, the API retries on a suitable model.
        resp = client.beta.messages.parse(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError as e:
        log.warning("Fallback request rejected (%s); retrying without fallbacks", e.message)
        resp = client.beta.messages.parse(**kwargs)
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
        "note": "Automatiškai nuskaityta be AI — patikrinkite visus laukus.",
    }


def extract_url(url):
    """Returns (fields: dict, page: Page, used_llm: bool)."""
    page = fetch(url)
    if page.error and not page.text:
        return {"url": url, "note": f"Nepavyko atidaryti puslapio: {page.error}"}, page, False
    if llm_available():
        try:
            ex = extract_with_claude(page)
            if ex:
                data = ex.model_dump()
                data["url"] = page.final_url or url
                return data, page, True
        except Exception as e:  # network/API errors must not break the admin form
            log.exception("Claude extraction failed: %s", e)
    return heuristic(page), page, False
