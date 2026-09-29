"""Minimal LT/EN interface strings. English is the key; Lithuanian is the translation."""
from flask import request, session

LT = {
    "MISC open calls": "MISC atviri kvietimai",
    "Open calls": "Atviri kvietimai",
    "Music Innovation Studies Centre": "Muzikos inovacijų studijų centras",
    "Lithuanian Academy of Music and Theatre": "Lietuvos muzikos ir teatro akademija",
    "Calls, conferences, journals, residencies and competitions for LMTA students, teachers, artists and researchers.":
        "Kvietimai, konferencijos, žurnalai, rezidencijos ir konkursai LMTA studentams, dėstytojams, menininkams ir tyrėjams.",
    "Search": "Paieška", "Search titles, organisers, descriptions…": "Ieškoti pavadinimuose, organizatoriuose, aprašymuose…",
    "Type": "Tipas", "Status": "Būsena", "Discipline": "Disciplina", "Area": "Sritis", "Region": "Regionas",
    "Country": "Šalis", "Deadline from": "Terminas nuo", "Deadline to": "Terminas iki", "Sort": "Rikiuoti",
    "Any": "Visi", "Filter": "Filtruoti", "Reset": "Išvalyti", "More filters": "Daugiau filtrų",
    "Best fit only": "Tik geriausiai tinkantys", "Remote participation": "Galima dalyvauti nuotoliu",
    "Free to apply": "Nemokama teikti", "My subscriptions": "Mano prenumeratos",
    "Active (open + upcoming)": "Aktyvūs (atviri + netrukus)", "Closing within 14 days": "Baigiasi per 14 d.",
    "Open": "Atviras", "Open now": "Atviri dabar", "Opens soon": "Netrukus atsidaro", "Closed": "Pasibaigę",
    "Checked — not eligible": "Patikrinta — netinka", "All": "Visi",
    "Due today": "Terminas šiandien", "Closing soon": "Greitai baigiasi", "Rolling": "Nuolatinis",
    "Upcoming": "Netrukus", "Not eligible": "Netinka", "Pending review": "Laukia peržiūros",
    "Deadline": "Terminas", "deadline": "terminas", "days left": "d. liko", "day left": "d. liko", "today": "šiandien",
    "Soonest deadline": "Artimiausias terminas", "Recently added": "Naujausi", "Title": "Pavadinimas",
    "results": "rezultatai", "Download calendar (.ics)": "Atsisiųsti kalendorių (.ics)",
    "Subscribe to this list": "Prenumeruoti šį sąrašą", "Add to calendar": "Įtraukti į kalendorių",
    "Subscribe": "Prenumeruoti", "Subscribed": "Prenumeruojama", "Unsubscribe": "Atsisakyti",
    "Log in with LMTA account": "Prisijungti su LMTA paskyra", "Log in": "Prisijungti", "Log out": "Atsijungti",
    "Suggest a call": "Pasiūlyti kvietimą", "Map": "Žemėlapis", "About": "Apie", "Admin": "Administravimas",
    "Official page": "Oficialus puslapis", "Who it suits": "Kam tinka", "Benefit": "Nauda", "Fee": "Mokestis",
    "Age limits": "Amžiaus ribos", "Covered": "Padengiama", "Remote": "Nuotoliu", "Registration": "Registracija",
    "Student discount": "Studentų nuolaida", "Note": "Pastaba", "Found via": "Rasta per", "Organiser": "Organizatorius",
    "Location": "Vieta", "Topics": "Temos", "Event dates": "Renginio datos", "Last verified": "Paskutinį kartą patikrinta",
    "First seen": "Pirmą kartą rasta", "Not verified — open manually": "Nepatikrinta — atidaryti rankiniu būdu",
    "Deadline in 7 days": "Terminas po 7 d.", "Deadline tomorrow": "Terminas rytoj",
    "Back to list": "Atgal į sąrašą", "History": "Pakeitimų istorija", "Edit": "Redaguoti",
    "Log in to subscribe": "Prisijunkite, kad galėtumėte prenumeruoti",
    "Your personal calendar feed": "Jūsų asmeninis kalendoriaus srautas",
    "Add this address to Outlook, Google or Apple Calendar as an internet calendar. Deadlines of everything you subscribe to appear there and update automatically.":
        "Įtraukite šį adresą į Outlook, Google ar Apple kalendorių kaip interneto kalendorių. Visų prenumeruojamų kvietimų terminai atsiras ten ir atsinaujins automatiškai.",
    "Open in Outlook / Apple Calendar": "Atidaryti Outlook / Apple kalendoriuje", "Copy": "Kopijuoti",
    "Reset feed address": "Pakeisti srauto adresą", "You have no subscriptions yet.": "Kol kas nieko neprenumeruojate.",
    "Paste a link to a call, CFP, residency or competition. It will be read automatically and reviewed by the MISC coordinator before it is published.":
        "Įklijuokite nuorodą į kvietimą, CFP, rezidenciją ar konkursą. Informacija bus nuskaityta automatiškai, o MISC koordinatorius ją peržiūrės prieš paskelbiant.",
    "Link": "Nuoroda", "Comment (optional)": "Komentaras (neprivaloma)", "Send": "Siųsti",
    "Thank you — the suggestion was sent for review.": "Ačiū — pasiūlymas perduotas peržiūrai.",
    "No calls match these filters.": "Pagal šiuos filtrus kvietimų nėra.",
    "Calls by location": "Kvietimai pagal vietą", "Online / international": "Internetu / tarptautiniai",
    "Everything": "Viskas", "Updated": "Atnaujinta", "calls": "kvietimai",
    "Subscribe without an account": "Prenumeruoti be paskyros",
    "Copy the link below into your calendar app to follow this filtered list; it updates automatically.":
        "Nukopijuokite nuorodą į kalendoriaus programą ir sekite šį filtruotą sąrašą — jis atsinaujina automatiškai.",
    "Please log in first.": "Pirmiausia prisijunkite.", "Access denied.": "Prieiga uždrausta.",
    "Only institutional accounts can log in.": "Prisijungti galima tik su institucine paskyra.",
    "Logged in as": "Prisijungta kaip", "Upcoming deadlines": "Artėjantys terminai",
}


def get_lang():
    lang = session.get("lang")
    if lang in ("lt", "en"):
        return lang
    best = request.accept_languages.best_match(["lt", "en"]) if request else None
    return best or "lt"


def tr(text, lang=None):
    lang = lang or get_lang()
    return LT.get(text, text) if lang == "lt" else text
