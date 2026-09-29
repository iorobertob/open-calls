"""Controlled vocabularies: entry types, topics (disciplines), topic families (areas),
countries and regions. Topic keys and families mirror the MISC TV-screen template
(MISC-ekranas-SABLONAS.html) so data stays interchangeable with the weekly workflow."""

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
