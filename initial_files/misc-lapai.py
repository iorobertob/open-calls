#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MISC — ekrano HTML  →  lapų PNG  →  PDF  +  JPEG 4K ZIP  +  QR patikra
=====================================================================

Vienintelis vizualinis šablonas yra ekrano HTML failas (MISC-ekranas-SABLONAS.html).
PDF ir JPEG nėra atskiri šablonai — tai to paties HTML lapų nuotraukos.
Šis skriptas atlieka visą grandinę ir visas patikras.

NAUDOJIMAS
----------
    python3 misc-lapai.py MISC-ekranas-2026-09-28.html
    python3 misc-lapai.py ekranas.html --isvestis ./2026-09-28 --data 2026-09-28
    python3 misc-lapai.py ekranas.html --tik-geometrija     # greita patikra prieš generavimą
    python3 misc-lapai.py ekranas.html --tik-qr             # perskaičiuoti QR jau sugeneruotiems failams

PRIKLAUSOMYBĖS
--------------
    pip install playwright pillow img2pdf opencv-python-headless pypdfium2 numpy --break-system-packages
    # Chromium debesyje jau įdiegtas (PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers);
    # savo kompiuteryje vieną kartą: python3 -m playwright install chromium

KĄ DARO, EILĖS TVARKA
---------------------
 1. GEOMETRINĖ PATIKRA. Pereina visus lapus ir tikrina, ar kiekvieno kortelės QR
    langelio (.qrBox) apatinis kraštas telpa į 2160 px, o dešinysis — į 3840 px.
    Šito `checkData()` NEDARO. Netelpanti kortelė reiškia nukirstą QR kodą PDF ir JPEG
    failuose. Dažniausia priežastis — per ilgas deadlineWordLt/En šoniniame stulpelyje
    (362 px plotis, 34 px šriftas). Radęs problemų, skriptas sustoja ir parodo, kurią
    kortelę trumpinti.
 2. LAPŲ NUOTRAUKOS 3840×2160 (device_scale_factor=1), sustabdžius vartymą ir animacijas.
    Failų vardai: NN-<sritis>.png, sritis lietuviškai (titulinis, konkursai, festivaliai,
    akademijos, konferencijos, rezidencijos, mobilumas).
 3. PDF, 1280×720 taškų lapai. Naudojamas img2pdf, NE reportlab: reportlab drawImage
    perkoduoja JPEG į Flate ir išpučia failą ~13 %, todėl kokybę tektų be reikalo mažinti.
    JPEG kokybė renkama mažėjančia tvarka, kol failas tilps po riba (numatyta 29 MB —
    pokalbio įkėlimo riba yra 30 MB). 2026-09-28, 51 lapas: tiko kokybė 58.
 4. JPEG 3840×2160, kokybė 94, subsampling=0, progressive. Supakuojama į ZIP;
    jei viena dalis viršytų ribą — dalijama į …-1dalis.zip, …-2dalis.zip ir t. t.
    ZIP daromas be spaudimo (ZIP_STORED) — JPEG jau suspaustas, o taip pakavimas
    trunka sekundę vietoj minučių.
 5. QR PATIKRA. Dekoduoja QR iš GALUTINIO PDF ir iš JPEG, palygina su visų CALLS
    įrašų url. Trūkstant bent vieno — parodo, kurio, ir grąžina klaidos kodą.

JEI QR NENUSKAITOMAS
--------------------
 1) Pirmiausia paleisk --tik-geometrija. Dažniausiai kodas ne „blogas", o nukirstas.
 2) Žinoma šablono klaida: retais atvejais generatorius sukuria nenuskaitomą kodą,
    nors checkData() švarus. Užfiksuoti atvejai:
      2026-09-07  https://positiveambisonics.org/   — su pasvirčiu gale nedekoduojasi
      2026-09-21  ilgi URL (IRCAM Forum su pasvirčiu, Theia PDF)
      2026-09-28  https://www.mdpi.com/...          — su „www." nedekoduojasi, be jo veikia
    Sprendimas: keisk URL (be pasvirčio gale, be „www.", trumpesnis organizatoriaus
    puslapis), o NE QR generatorių šablone.
"""

import argparse, asyncio, json, os, re, shutil, sys, unicodedata, zipfile
from pathlib import Path

STAGE_W, STAGE_H = 3840, 2160      # ekrano lauko dydis šablone
PDF_W, PDF_H     = 1280, 720       # PDF lapo dydis taškais (16:9)
JPEG_KOKYBE      = 94              # galutinių JPEG kokybė (nekeisti)
RIBA_MB          = 29              # po kiek MB turi tilpti PDF ir kiekviena ZIP dalis
PDF_KOKYBES      = [82, 74, 66, 58, 52, 46]   # bandoma iš eilės, kol PDF tilps

SRITYS = {'competition':'konkursai', 'festival':'festivaliai', 'academy':'akademijos',
          'conference':'konferencijos', 'residency':'rezidencijos', 'mobility':'mobilumas'}


def slug(s: str) -> str:
    s = unicodedata.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def mb(baitai: int) -> float:
    return baitai / 1024 / 1024


# ---------------------------------------------------------------- naršyklė

async def _atidaryti(pw, html: Path):
    b = await pw.chromium.launch(args=['--force-device-scale-factor=1'])
    pg = await b.new_page(viewport={'width': STAGE_W, 'height': STAGE_H},
                          device_scale_factor=1)
    klaidos = []
    pg.on('pageerror', lambda e: klaidos.append(str(e)))
    pg.on('console', lambda m: klaidos.append('console.' + m.type + ': ' + m.text)
          if m.type == 'error' else None)
    await pg.goto(html.resolve().as_uri())
    await pg.wait_for_timeout(1200)
    await pg.evaluate("() => { CONFIG.autoplay = false; }")
    return b, pg, klaidos


async def _sustabdyti_animacijas(pg):
    await pg.evaluate("""() => {
        CONFIG.autoplay = false;
        try { clearInterval(timer) } catch (e) {}
        try { clearInterval(tick) } catch (e) {}
        var pr = document.getElementById('prog');
        if (pr) pr.style.display = 'none';
    }""")
    await pg.add_style_tag(content='*{animation:none !important;transition:none !important}')


# ---------------------------------------------------------------- 1. patikros

async def patikros(html: Path):
    """checkData() + geometrinė patikra. Grąžina (checkdata_problemos, geometrijos_problemos, konsoles_klaidos, url_sarasas)."""
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b, pg, klaidos = await _atidaryti(pw, html)

        cd = await pg.evaluate("() => { try { return checkData(); } "
                               "catch (e) { return ['checkData() klaida: ' + e.message]; } }")

        urls = await pg.evaluate("() => CALLS.map(c => c.url)")
        n = await pg.evaluate("() => PAGES.length")

        blogi = []
        for i in range(n):
            await pg.evaluate(f"() => {{ idx = {i}; render(); }}")
            await pg.wait_for_timeout(110)
            eil = await pg.evaluate("""() => [...document.querySelectorAll('#grid .qrBox')].map(q => {
                var r = q.getBoundingClientRect(), c = q.closest('.card');
                return { apacia: Math.round(r.bottom), desine: Math.round(r.right),
                         pav: (c.querySelector('h2') || {textContent:''}).textContent.slice(0, 60) };
            })""")
            for x in eil:
                if x['apacia'] > STAGE_H or x['desine'] > STAGE_W:
                    blogi.append({'lapas': i, **x})

        await b.close()
        return cd, blogi, klaidos, urls


# ---------------------------------------------------------------- 2. lapų nuotraukos

async def nuotraukos(html: Path, kat: Path):
    from playwright.async_api import async_playwright
    kat.mkdir(parents=True, exist_ok=True)
    for senas in kat.glob('*.png'):
        senas.unlink()
    async with async_playwright() as pw:
        b, pg, klaidos = await _atidaryti(pw, html)
        await _sustabdyti_animacijas(pg)
        n = await pg.evaluate("() => PAGES.length")
        rusys = await pg.evaluate("""() => PAGES.map(p => p.cover ? 'cover'
            : (p.kind || (p.items && p.items[0] && p.items[0].kind) || 'kita'))""")
        for i in range(n):
            await pg.evaluate(f"() => {{ idx = {i}; render(); }}")
            await pg.wait_for_timeout(500)
            r = rusys[i]
            vardas = f"{i:02d}-" + ('titulinis' if r == 'cover' else slug(SRITYS.get(r, r)))
            await pg.screenshot(path=str(kat / f"{vardas}.png"))
        await b.close()
    return sorted(kat.glob('*.png')), klaidos


# ---------------------------------------------------------------- 3. PDF

def pdf(lapai, kelias: Path, tmp: Path):
    from PIL import Image
    import img2pdf
    lay = img2pdf.get_layout_fun((PDF_W, PDF_H))
    riba = RIBA_MB * 1024 * 1024
    for q in PDF_KOKYBES:
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for f in lapai:
            Image.open(f).convert('RGB').save(
                tmp / (f.stem + '.jpg'), 'JPEG',
                quality=q, subsampling=0, optimize=True)
        with open(kelias, 'wb') as o:
            o.write(img2pdf.convert([str(tmp / (f.stem + '.jpg')) for f in lapai],
                                    layout_fun=lay))
        dydis = kelias.stat().st_size
        print(f"    kokybė {q} → {mb(dydis):.2f} MB", flush=True)
        if dydis < riba:
            shutil.rmtree(tmp, ignore_errors=True)
            return q, dydis
    shutil.rmtree(tmp, ignore_errors=True)
    return PDF_KOKYBES[-1], kelias.stat().st_size      # netilpo, bet grąžinam ką turim


# ---------------------------------------------------------------- 4. JPEG + ZIP

def jpeg_ir_zip(lapai, jpg_kat: Path, zip_bazė: Path):
    from PIL import Image
    shutil.rmtree(jpg_kat, ignore_errors=True)
    jpg_kat.mkdir(parents=True)
    for f in lapai:
        im = Image.open(f).convert('RGB')
        if im.size != (STAGE_W, STAGE_H):
            im = im.resize((STAGE_W, STAGE_H), Image.LANCZOS)
        im.save(jpg_kat / (f.stem + '.jpg'), 'JPEG', quality=JPEG_KOKYBE,
                subsampling=0, optimize=True, progressive=True)

    for senas in zip_bazė.parent.glob(zip_bazė.name + '*.zip'):
        senas.unlink()

    failai = sorted(jpg_kat.glob('*.jpg'))
    riba = RIBA_MB * 1024 * 1024
    dalys, dabar, sud = [], [], 0
    for f in failai:
        d = f.stat().st_size
        if dabar and sud + d > riba:
            dalys.append(dabar); dabar, sud = [], 0
        dabar.append(f); sud += d
    if dabar:
        dalys.append(dabar)

    if len(dalys) == 1:
        vardai = [zip_bazė.with_name(zip_bazė.name + '.zip')]
    else:
        vardai = [zip_bazė.with_name(f"{zip_bazė.name}-{i+1}dalis.zip")
                  for i in range(len(dalys))]

    rez = []
    for vardas, grupė in zip(vardai, dalys):
        with zipfile.ZipFile(vardas, 'w', zipfile.ZIP_STORED) as z:
            for f in grupė:
                z.write(f, f.name)
        rez.append((vardas, vardas.stat().st_size, len(grupė)))
    return rez


# ---------------------------------------------------------------- 5. QR patikra

def qr_patikra(pdf_kelias: Path, jpg_kat: Path, urls):
    import numpy as np, cv2, pypdfium2 as pdfium
    det = cv2.QRCodeDetector()
    rasta = set()

    def scan(img):
        ok, texts, _, _ = det.detectAndDecodeMulti(img)
        if ok:
            rasta.update(t for t in texts if t)
        th = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY)[1]
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if 150 < w < 800 and 0.8 < w / h < 1.25:
                t, _, _ = det.detectAndDecode(
                    img[max(0, y - 12):y + h + 12, max(0, x - 12):x + w + 12])
                if t:
                    rasta.add(t)

    doc = pdfium.PdfDocument(str(pdf_kelias))
    for i in range(len(doc)):
        scan(np.array(doc[i].render(scale=3).to_pil().convert('L')))
    for j in sorted(jpg_kat.glob('*.jpg')):
        scan(cv2.imread(str(j), cv2.IMREAD_GRAYSCALE))

    unikalūs = sorted(set(urls))
    trūksta = [u for u in unikalūs if u not in rasta]
    return unikalūs, rasta, trūksta


# ---------------------------------------------------------------- vykdymas

def main():
    p = argparse.ArgumentParser(description='MISC ekrano HTML → PDF + JPEG 4K + QR patikra')
    p.add_argument('html', help='ekrano HTML failas')
    p.add_argument('--isvestis', default='.', help='kur dėti rezultatus (numatyta: čia pat)')
    p.add_argument('--data', default=None, help='data failų varduose (numatyta: iš HTML vardo)')
    p.add_argument('--tik-geometrija', action='store_true', help='tik patikros, nieko negeneruoti')
    p.add_argument('--tik-qr', action='store_true', help='tik QR patikra jau esantiems failams')
    a = p.parse_args()

    html = Path(a.html)
    if not html.exists():
        sys.exit(f"Nėra failo: {html}")
    data = a.data or (re.search(r'\d{4}-\d{2}-\d{2}', html.name) or [None])[0]
    if not data:
        sys.exit("Nepavyko nustatyti datos — nurodyk --data MMMM-MM-DD")

    isv = Path(a.isvestis); isv.mkdir(parents=True, exist_ok=True)
    lapai_kat = isv / 'lapai'
    jpg_kat   = isv / 'jpeg4k'
    pdf_kelias = isv / f'MISC-ekranas-{data}-visi-lapai.pdf'
    zip_bazė   = isv / f'MISC-ekranas-{data}-lapai-JPEG-4K'

    if a.tik_qr:
        urls = json.loads(Path(isv / 'urls.json').read_text(encoding='utf-8')) \
            if (isv / 'urls.json').exists() else []
        if not urls:
            sys.exit("Nerasta urls.json — paleisk be --tik-qr.")
        u, r, t = qr_patikra(pdf_kelias, jpg_kat, urls)
        print(f"QR: unikalių url {len(u)}, rasta {len(r)}, trūksta {len(t)}")
        for x in t:
            print("   TRŪKSTA:", x)
        sys.exit(1 if t else 0)

    print("1/5  Patikros (checkData + geometrija)…", flush=True)
    cd, geom, klaidos, urls = asyncio.run(patikros(html))
    if cd:
        print("     checkData() PROBLEMOS:")
        for x in (cd if isinstance(cd, list) else [cd]):
            print("       ", x)
    else:
        print("     checkData(): švaru")
    if geom:
        print(f"     GEOMETRIJA: {len(geom)} kortelė(s) netelpa į lapą —")
        for x in geom:
            print(f"       lapas {x['lapas']}: apačia={x['apacia']} (riba {STAGE_H}) · {x['pav']}")
        print("     Trumpink šia eile: 1) deadlineWordLt/En iki ~30 simbolių, "
              "2) titleLt, 3) descLt/descEn.")
    else:
        print("     geometrija: visos kortelės telpa")
    if klaidos:
        print("     KONSOLĖ:", klaidos[:5])
    (isv / 'urls.json').write_text(json.dumps(urls, ensure_ascii=False), encoding='utf-8')

    if cd or geom:
        sys.exit("\nSustota: pirma ištaisyk patikrų problemas.")
    if a.tik_geometrija:
        print("\nPatikros švarios (--tik-geometrija, toliau nevykdoma).")
        return

    print("2/5  Lapų nuotraukos 3840×2160…", flush=True)
    lapai, kl = asyncio.run(nuotraukos(html, lapai_kat))
    print(f"     {len(lapai)} lapų" + (f" · klaidos: {kl[:3]}" if kl else ""))

    print(f"3/5  PDF (ieškoma kokybės, kad tilptų po {RIBA_MB} MB)…", flush=True)
    q, dydis = pdf(lapai, pdf_kelias, isv / '_tmpjpg')
    print(f"     {pdf_kelias.name}: {mb(dydis):.2f} MB, kokybė {q}")

    print(f"4/5  JPEG 4K (kokybė {JPEG_KOKYBE}) ir ZIP…", flush=True)
    for vardas, d, kiek in jpeg_ir_zip(lapai, jpg_kat, zip_bazė):
        print(f"     {vardas.name}: {mb(d):.2f} MB, {kiek} failai")

    print("5/5  QR patikra (PDF + JPEG)…", flush=True)
    u, r, t = qr_patikra(pdf_kelias, jpg_kat, urls)
    print(f"     unikalių url {len(u)} · dekoduota {len(r)} · trūksta {len(t)}")
    if t:
        for x in t:
            print("       TRŪKSTA:", x)
        sys.exit("\nQR patikra NEPRAĖJO — žr. skripto antraštėje „JEI QR NENUSKAITOMAS\".")
    print("\nViskas gerai. Failai:", isv.resolve())


if __name__ == '__main__':
    main()
