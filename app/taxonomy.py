"""Controlled vocabularies.

* Entry types (KINDS), countries and regions: fixed here.
* Fields → categories → sub-disciplines: stored in the database (Field, Category, Discipline) so
  admins can edit them (Admin → Disciplines). DEFAULT_TREE below is only the initial content.
  `tax()` gives the current tree for one request.
* FAMILIES / TOPICS below are the fixed vocabulary of the MISC TV-screen template
  (MISC-ekranas-SABLONAS.html); only /screen still uses them."""

KINDS = {
    "competition": {"lt": "Konkursai", "en": "Competitions", "short_lt": "Konkursas", "short_en": "Competition", "hue": 38},
    "works":       {"lt": "Kvietimai teikti kūrinius", "en": "Calls for scores & works", "short_lt": "Kūrinių kvietimas", "short_en": "Call for works", "hue": 8},
    "festival":    {"lt": "Festivaliai ir koncertai", "en": "Festivals & concerts", "short_lt": "Festivalis", "short_en": "Festival", "hue": 318},
    "academy":     {"lt": "Akademijos ir dirbtuvės", "en": "Academies & workshops", "short_lt": "Akademija", "short_en": "Academy", "hue": 172},
    "conference":  {"lt": "Konferencijos ir simpoziumai", "en": "Conferences & symposia", "short_lt": "Konferencija", "short_en": "Conference", "hue": 212},
    "journal":     {"lt": "Žurnalai ir leidiniai", "en": "Journals & publications", "short_lt": "Žurnalas", "short_en": "Journal", "hue": 262},
    "residency":   {"lt": "Rezidencijos", "en": "Residencies", "short_lt": "Rezidencija", "short_en": "Residency", "hue": 142},
    "mobility":    {"lt": "Mobilumas ir finansavimas", "en": "Mobility & funding", "short_lt": "Mobilumas", "short_en": "Mobility", "hue": 22},
    "grant":       {"lt": "Stipendijos ir grantai", "en": "Grants & fellowships", "short_lt": "Grantas", "short_en": "Grant", "hue": 92},
    "other":       {"lt": "Kita", "en": "Other", "short_lt": "Kita", "short_en": "Other", "hue": 220},
}
KIND_ORDER = list(KINDS)

FAMILIES = {
    "studio":   {"lt": "Elektronika ir studija", "en": "Electronics & studio"},
    "spatial":  {"lt": "Erdvinis garsas", "en": "Spatial audio"},
    "acoustic": {"lt": "Instrumentinė muzika", "en": "Instrumental music"},
    "compute":  {"lt": "Kompiuterinė muzika ir AI", "en": "Computer music & AI"},
    "ctx":      {"lt": "Formatas ir kontekstas", "en": "Format & context"},
}

TOPICS = {
    "electronic":   ("studio", "elektroninė", "electronic"),
    "acousmatic":   ("studio", "akuzmatinė", "acousmatic"),
    "concrete":     ("studio", "musique concrète", "musique concrète"),
    "fixedmedia":   ("studio", "fixed media", "fixed media"),
    "liveelec":     ("studio", "gyva elektronika", "live electronics"),
    "spatial":      ("spatial", "erdvinis garsas", "spatial audio"),
    "ambisonics":   ("spatial", "ambisonics", "ambisonics"),
    "multichannel": ("spatial", "daugiakanalis", "multichannel"),
    "immersive":    ("spatial", "immersive / 3D", "immersive / 3D"),
    "vrar":         ("spatial", "VR / AR", "VR / AR"),
    "instrumental": ("acoustic", "instrumentinė", "instrumental"),
    "ensemble":     ("acoustic", "ansamblis", "ensemble"),
    "orchestra":    ("acoustic", "orkestras", "orchestra"),
    "chamber":      ("acoustic", "kamerinė", "chamber"),
    "solo":         ("acoustic", "solo", "solo"),
    "voice":        ("acoustic", "balsas", "voice"),
    "accordion":    ("acoustic", "akordeonas", "accordion"),
    "winds":        ("acoustic", "pučiamieji", "winds"),
    "percussion":   ("acoustic", "mušamieji", "percussion"),
    "algorithmic":  ("compute", "algoritminė kompozicija", "algorithmic composition"),
    "ai":           ("compute", "generatyvus AI", "generative AI"),
    "computermus":  ("compute", "computer music", "computer music"),
    "livecoding":   ("compute", "live coding", "live coding"),
    "musictech":    ("compute", "muzikos technologijos", "music technology"),
    "soundart":     ("ctx", "garso menas", "sound art"),
    "mediaart":     ("ctx", "medijų menas", "media art"),
    "installation": ("ctx", "instaliacija", "installation"),
    "audiovisual":  ("ctx", "audiovizualika", "audiovisual"),
    "radio":        ("ctx", "radijas", "radio"),
    "performance":  ("ctx", "performansas", "performance"),
    "research":     ("ctx", "tyrimas", "research"),
    "paper":        ("ctx", "pranešimas", "paper"),
    "workshop":     ("ctx", "dirbtuvės", "workshop"),
    "mobility":     ("ctx", "mobilumas", "mobility"),
    "premiere":     ("ctx", "premjera", "premiere"),
    "musicology":   ("ctx", "muzikologija", "musicology"),
    "pedagogy":     ("ctx", "pedagogika", "music education"),
    "theatre":      ("ctx", "teatras ir šokis", "theatre & dance"),
}


def topic_label(key, lang):
    t = TOPICS.get(key)
    if not t:
        return key
    return t[1] if lang == "lt" else t[2]


REGIONS = {
    "LT":     {"lt": "Lietuva", "en": "Lithuania"},
    "BALTIC": {"lt": "Baltijos ir Šiaurės šalys", "en": "Baltic & Nordic"},
    "EU":     {"lt": "Kitos ES šalys", "en": "Other EU countries"},
    "EUROPE": {"lt": "Europa ne ES", "en": "Europe (non-EU)"},
    "NAM":    {"lt": "Šiaurės Amerika", "en": "North America"},
    "LATAM":  {"lt": "Lotynų Amerika", "en": "Latin America"},
    "ASIA":   {"lt": "Azija ir Artimieji Rytai", "en": "Asia & Middle East"},
    "OCEANIA": {"lt": "Okeanija", "en": "Oceania"},
    "AFRICA": {"lt": "Afrika", "en": "Africa"},
    "ONLINE": {"lt": "Internetu / tarptautinis", "en": "Online / international"},
}

# code: (region, lat, lon, name_lt, name_en)
COUNTRIES = {
    "LT": ("LT", 55.17, 23.88, "Lietuva", "Lithuania"),
    "LV": ("BALTIC", 56.88, 24.60, "Latvija", "Latvia"),
    "EE": ("BALTIC", 58.60, 25.01, "Estija", "Estonia"),
    "FI": ("BALTIC", 61.92, 25.75, "Suomija", "Finland"),
    "SE": ("BALTIC", 60.13, 18.64, "Švedija", "Sweden"),
    "DK": ("BALTIC", 56.26, 9.50, "Danija", "Denmark"),
    "NO": ("BALTIC", 60.47, 8.47, "Norvegija", "Norway"),
    "IS": ("BALTIC", 64.96, -19.02, "Islandija", "Iceland"),
    "DE": ("EU", 51.17, 10.45, "Vokietija", "Germany"),
    "AT": ("EU", 47.52, 14.55, "Austrija", "Austria"),
    "FR": ("EU", 46.23, 2.21, "Prancūzija", "France"),
    "IT": ("EU", 41.87, 12.57, "Italija", "Italy"),
    "ES": ("EU", 40.46, -3.75, "Ispanija", "Spain"),
    "PT": ("EU", 39.40, -8.22, "Portugalija", "Portugal"),
    "BE": ("EU", 50.50, 4.47, "Belgija", "Belgium"),
    "NL": ("EU", 52.13, 5.29, "Nyderlandai", "Netherlands"),
    "LU": ("EU", 49.82, 6.13, "Liuksemburgas", "Luxembourg"),
    "IE": ("EU", 53.41, -8.24, "Airija", "Ireland"),
    "PL": ("EU", 51.92, 19.15, "Lenkija", "Poland"),
    "CZ": ("EU", 49.82, 15.47, "Čekija", "Czechia"),
    "SK": ("EU", 48.67, 19.70, "Slovakija", "Slovakia"),
    "SI": ("EU", 46.15, 14.99, "Slovėnija", "Slovenia"),
    "HR": ("EU", 45.10, 15.20, "Kroatija", "Croatia"),
    "HU": ("EU", 47.16, 19.50, "Vengrija", "Hungary"),
    "RO": ("EU", 45.94, 24.97, "Rumunija", "Romania"),
    "BG": ("EU", 42.73, 25.49, "Bulgarija", "Bulgaria"),
    "GR": ("EU", 39.07, 21.82, "Graikija", "Greece"),
    "CY": ("EU", 35.13, 33.43, "Kipras", "Cyprus"),
    "MT": ("EU", 35.94, 14.38, "Malta", "Malta"),
    "GB": ("EUROPE", 55.38, -3.44, "Jungtinė Karalystė", "United Kingdom"),
    "CH": ("EUROPE", 46.82, 8.23, "Šveicarija", "Switzerland"),
    "RS": ("EUROPE", 44.02, 21.01, "Serbija", "Serbia"),
    "UA": ("EUROPE", 48.38, 31.17, "Ukraina", "Ukraine"),
    "GE": ("EUROPE", 42.32, 43.36, "Sakartvelas", "Georgia"),
    "BA": ("EUROPE", 43.92, 17.68, "Bosnija ir Hercegovina", "Bosnia and Herzegovina"),
    "ME": ("EUROPE", 42.71, 19.37, "Juodkalnija", "Montenegro"),
    "MK": ("EUROPE", 41.61, 21.75, "Šiaurės Makedonija", "North Macedonia"),
    "AL": ("EUROPE", 41.15, 20.17, "Albanija", "Albania"),
    "MD": ("EUROPE", 47.41, 28.37, "Moldova", "Moldova"),
    "TR": ("EUROPE", 38.96, 35.24, "Turkija", "Türkiye"),
    "US": ("NAM", 39.83, -98.58, "JAV", "United States"),
    "CA": ("NAM", 56.13, -106.35, "Kanada", "Canada"),
    "MX": ("LATAM", 23.63, -102.55, "Meksika", "Mexico"),
    "BR": ("LATAM", -14.24, -51.93, "Brazilija", "Brazil"),
    "AR": ("LATAM", -38.42, -63.62, "Argentina", "Argentina"),
    "CL": ("LATAM", -35.68, -71.54, "Čilė", "Chile"),
    "CO": ("LATAM", 4.57, -74.30, "Kolumbija", "Colombia"),
    "JM": ("LATAM", 18.11, -77.30, "Jamaika", "Jamaica"),
    "JP": ("ASIA", 36.20, 138.25, "Japonija", "Japan"),
    "KR": ("ASIA", 35.91, 127.77, "Pietų Korėja", "South Korea"),
    "CN": ("ASIA", 35.86, 104.20, "Kinija", "China"),
    "TW": ("ASIA", 23.70, 120.96, "Taivanas", "Taiwan"),
    "HK": ("ASIA", 22.32, 114.17, "Honkongas", "Hong Kong"),
    "SG": ("ASIA", 1.35, 103.82, "Singapūras", "Singapore"),
    "IN": ("ASIA", 20.59, 78.96, "Indija", "India"),
    "IL": ("ASIA", 31.05, 34.85, "Izraelis", "Israel"),
    "AE": ("ASIA", 23.42, 53.85, "JAE", "United Arab Emirates"),
    "AU": ("OCEANIA", -25.27, 133.78, "Australija", "Australia"),
    "NZ": ("OCEANIA", -40.90, 174.89, "Naujoji Zelandija", "New Zealand"),
    "ZA": ("AFRICA", -30.56, 22.94, "Pietų Afrika", "South Africa"),
    "XX": ("ONLINE", None, None, "Internetu / įvairiose vietose", "Online / various"),
}


def region_of(code):
    c = COUNTRIES.get((code or "").upper())
    return c[0] if c else ("ONLINE" if not code or code == "XX" else "OTHER")


def country_name(code, lang):
    c = COUNTRIES.get((code or "").upper())
    if not c:
        return code or ""
    return c[3] if lang == "lt" else c[4]


# ---------------------------------------------------------------- fields → categories → sub-disciplines

# (key, name_lt, name_en, hue)
DEFAULT_FIELDS = [
    ("music", "Muzika ir garsas", "Music and Sound", 210),
    ("theatre", "Teatras", "Theatre", 15),
    ("cinema", "Kinas", "Cinema", 245),
    ("dance", "Šokis ir performansas", "Dance and Performance", 160),
]
# (key, field key or None = shared by all fields, name_lt, name_en, hue or None, [(discipline key, lt, en), …])
DEFAULT_TREE = [
    ("studio", "music", "Elektronika ir studija", "Electronics & studio", 330, [
        ("electronic", "elektroninė", "electronic"), ("acousmatic", "akuzmatinė", "acousmatic"),
        ("concrete", "musique concrète", "musique concrète"), ("fixedmedia", "fixed media", "fixed media"),
        ("liveelec", "gyva elektronika", "live electronics")]),
    ("spatial", "music", "Erdvinis garsas", "Spatial audio", 212, [
        ("spatial", "erdvinis garsas", "spatial audio"), ("ambisonics", "ambisonics", "ambisonics"),
        ("multichannel", "daugiakanalis", "multichannel"), ("immersive", "immersive / 3D", "immersive / 3D"),
        ("vrar", "VR / AR", "VR / AR")]),
    ("acoustic", "music", "Instrumentinė ir vokalinė muzika", "Instrumental & vocal music", 42, [
        ("instrumental", "instrumentinė", "instrumental"), ("ensemble", "ansamblis", "ensemble"),
        ("orchestra", "orkestras", "orchestra"), ("chamber", "kamerinė", "chamber"), ("solo", "solo", "solo"),
        ("voice", "balsas", "voice"), ("accordion", "akordeonas", "accordion"), ("winds", "pučiamieji", "winds"),
        ("percussion", "mušamieji", "percussion")]),
    ("compute", "music", "Kompiuterinė muzika ir AI", "Computer music & AI", 142, [
        ("algorithmic", "algoritminė kompozicija", "algorithmic composition"), ("ai", "generatyvus AI", "generative AI"),
        ("computermus", "kompiuterinė muzika", "computer music"), ("livecoding", "live coding", "live coding"),
        ("musictech", "muzikos technologijos", "music technology")]),
    ("soundart", "music", "Garso ir medijų menas", "Sound & media art", 275, [
        ("soundart", "garso menas", "sound art"), ("mediaart", "medijų menas", "media art"),
        ("installation", "instaliacija", "installation"), ("audiovisual", "audiovizualika", "audiovisual"),
        ("radio", "radijas", "radio")]),
    ("musicology", "music", "Muzikologija", "Musicology", 190, [
        ("musicology", "muzikologija", "musicology")]),
    ("drama", "theatre", "Drama ir režisūra", "Drama & directing", 8, [
        ("drama", "drama", "drama"), ("directing", "režisūra", "directing"), ("acting", "vaidyba", "acting"),
        ("playwriting", "dramaturgija", "playwriting")]),
    ("musictheatre", "theatre", "Muzikinis teatras ir opera", "Music theatre & opera", 22, [
        ("opera", "opera", "opera"), ("musictheatre", "muzikinis teatras", "music theatre")]),
    ("stage", "theatre", "Scenografija ir scenos technologijos", "Stage design & technology", 32, [
        ("scenography", "scenografija", "scenography"), ("stagelighting", "scenos šviesos", "stage lighting"),
        ("stagesound", "scenos garsas", "stage sound")]),
    ("theatrestudies", "theatre", "Teatrologija", "Theatre studies", 355, [
        ("theatrestudies", "teatrologija", "theatre studies")]),
    ("film", "cinema", "Kinas ir video", "Film & video", 280, [
        ("filmmaking", "kino kūryba", "filmmaking"), ("documentary", "dokumentika", "documentary"),
        ("animation", "animacija", "animation"), ("videoart", "videomenas", "video art")]),
    ("filmsound", "cinema", "Garsas ir muzika kinui", "Film sound & music", 300, [
        ("filmmusic", "kino muzika", "film music"), ("sounddesign", "garso dizainas", "sound design")]),
    ("screenstudies", "cinema", "Kino studijos", "Screen studies", 260, [
        ("filmstudies", "kino studijos", "film studies")]),
    ("dancechoreo", "dance", "Šokis ir choreografija", "Dance & choreography", 142, [
        ("dance", "šokis", "dance"), ("choreography", "choreografija", "choreography")]),
    ("performanceart", "dance", "Performanso menas", "Performance art", 162, [
        ("performanceart", "performanso menas", "performance art"), ("liveart", "gyvasis menas", "live art")]),
    ("movementtech", "dance", "Judesys ir technologijos", "Movement & technology", 120, [
        ("motioncapture", "judesio fiksavimas", "motion capture"), ("interactive", "interaktyvus performansas", "interactive performance")]),
    ("formats", None, "Formatas ir kontekstas", "Format & context", None, [
        ("research", "tyrimas", "research"), ("paper", "pranešimas", "paper"), ("workshop", "dirbtuvės", "workshop"),
        ("performance", "atlikimas", "performance"), ("premiere", "premjera", "premiere"),
        ("mobility", "mobilumas", "mobility"), ("pedagogy", "pedagogika", "education")]),
]
DEFAULT_FIELD = "music"   # every entry belongs to at least one field; MISC's own field by default


def seed_defaults():
    """Fill the taxonomy tables when they are empty (fresh install, tests)."""
    from .models import Category, Discipline, Field, db
    if Field.query.first():
        return False
    fields = {}
    for i, (key, lt, en, hue) in enumerate(DEFAULT_FIELDS):
        fields[key] = Field(key=key, name_lt=lt, name_en=en, hue=hue, position=i)
        db.session.add(fields[key])
    db.session.flush()
    for i, (key, fkey, lt, en, hue, discs) in enumerate(DEFAULT_TREE):
        cat = Category(key=key, field_id=fields[fkey].id if fkey else None, name_lt=lt, name_en=en, hue=hue, position=i)
        db.session.add(cat)
        db.session.flush()
        for j, (dkey, dlt, den) in enumerate(discs):
            db.session.add(Discipline(key=dkey, category_id=cat.id, name_lt=dlt, name_en=den, position=j))
    db.session.commit()
    return True


class Tax:
    """The current field → category → sub-discipline tree (loaded once per request)."""

    def __init__(self):
        from .models import Category, Discipline, Field
        self.fields = Field.query.order_by(Field.position, Field.id).all()
        self.categories = Category.query.order_by(Category.position, Category.id).all()
        self.disciplines = Discipline.query.order_by(Discipline.position, Discipline.id).all()
        self.field_by_key = {f.key: f for f in self.fields}
        self.field_by_id = {f.id: f for f in self.fields}
        self.cat_by_key = {c.key: c for c in self.categories}
        self.cat_by_id = {c.id: c for c in self.categories}
        self.disc_by_key = {d.key: d for d in self.disciplines}

    # -- lookups
    def label(self, key, lang):
        d = self.disc_by_key.get(key)
        return d.name(lang) if d else key

    def category_of(self, key):
        d = self.disc_by_key.get(key)
        return self.cat_by_id.get(d.category_id) if d else None

    def hue(self, key):
        c = self.category_of(key)
        return c.hue if c else None

    def field_of_category(self, cat):
        return self.field_by_id.get(cat.field_id) if cat and cat.field_id else None

    def categories_for(self, field_key=None):
        """Categories shown under a field: its own + the shared ones. No field = all categories."""
        if not field_key:
            return self.categories
        f = self.field_by_key.get(field_key)
        return [c for c in self.categories if c.field_id is None or (f and c.field_id == f.id)]

    def disciplines_in(self, cat_key):
        c = self.cat_by_key.get(cat_key)
        return [d for d in self.disciplines if c and d.category_id == c.id]

    # Shared categories (no field) hold *formats* — research, paper, workshop, premiere… Visitors see
    # them next to the entry type (filter panel, "includes workshop" on cards), not in the field tree.
    def is_format(self, key):
        c = self.category_of(key)
        return bool(c) and c.field_id is None

    def formats(self):
        return [d for d in self.disciplines if self.is_format(d.key)]

    def public_categories(self, field_key=None):
        """Categories of a field (or of all fields) — without the shared format categories."""
        return [c for c in self.categories_for(field_key) if c.field_id is not None]

    def split_topics(self, keys):
        """(discipline topics, format topics) of an entry."""
        return [k for k in keys if not self.is_format(k)], [k for k in keys if self.is_format(k)]

    def implied_fields(self, topic_keys):
        out = []
        for t in topic_keys:
            f = self.field_of_category(self.category_of(t))
            if f and f.key not in out:
                out.append(f.key)
        return out

    def grouped(self):
        """[(field or None, [(category, [discipline, …]), …]), …] for pickers; shared categories last."""
        out = []
        for f in self.fields + [None]:
            cats = [c for c in self.categories if (c.field_id == f.id if f else c.field_id is None)]
            out.append((f, [(c, [d for d in self.disciplines if d.category_id == c.id]) for c in cats]))
        return out


def tax(refresh=False):
    from flask import g
    if refresh or "tax" not in g:
        g.tax = Tax()
    return g.tax


def sync_fields(call, t=None):
    """A call belongs to the fields of its sub-disciplines (plus any set by hand); never to none."""
    t = t or tax()
    fields = [f for f in call.field_list if f in t.field_by_key] if t.fields else call.field_list
    for f in t.implied_fields(call.topic_list):
        if f not in fields:
            fields.append(f)
    if not fields:
        fields = [DEFAULT_FIELD if (not t.fields or DEFAULT_FIELD in t.field_by_key) else t.fields[0].key]
    if fields != call.field_list:
        call.field_list = fields
