"""ETL pipeline: listings.csv -> fotky z Airbnb -> R2 -> SQLite.

Spusteni:  python scraper.py
Test jedne stranky (jen vypise fotky, nic neuklada):
         python scraper.py test https://www.airbnb.com/rooms/1571705115265609740

Fotka leti z Airbnb do pameti a odtud primo do R2, takze na disku nic nesedi
(SAVE_LOCAL = True ji navyse ponecha ve photos/). Do databaze se uklada adresa
<R2_PUBLIC_BASE>/<external_id>/<poradi>.<ext>.
"""

import csv
import hashlib
import os
import random
import re
import sqlite3
import sys
import time

import boto3
from pydantic import ValidationError
import requests

from src.models import ListingCreate
from src.repositories.db import DB_PATH
from src.repositories.schema import SCHEMA

# Jmena ubytovani v CSV obsahuji hvezdicky a emoji, windows konzole by na nich
# skocila s UnicodeEncodeError uprostred celeho behu.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- nastaveni -------------------------------------------------------------
LISTINGS_CSV = "listings.csv"     # sem dej cestu ke svemu listings.csv
SAVE_LOCAL = False                # True = fotku zarad ponechat i na disku
PHOTO_DIR = "photos"              # slozka jen pro SAVE_LOCAL = True
CITY = "Berlin"                    # sloupec city v CSV neni, hrajeme za toto
COUNTRY = "Germany"                # sloupec country v CSV take neni
# Měna, ve které je sloupec price v LISTINGS_CSV. Do DB vždy letí koruny, takže
# to musí být deklarované – symbol v řetězci se na to spolehnout nedá (Praha má
# před korunami znak $). Přidat další město stojí dva řádky níže, ne nové schéma.
CSV_CURRENCY = "EUR"               # "CZK" = přečti jak je, "USD" = přepočítej
USD_TO_CZK = 23.1
EUR_TO_CZK = 24.36
GBP_TO_CZK = 29.22             # platí jen pro CSV_CURRENCY = "USD"
RATE_DATE = "2026-10-31"           # kdy byl kurz pořízen, ať tu nevisí bez data
MAX_PHOTOS = 8                    # max fotek na jedno ubytovani
LIMIT = 500                    # 0 = všech 11 804 radku, jinak počet ubytování
SAMPLE_SEED = 1           # cislo = stale ten samy nahodny vyber (obnova behu)
DRY_RUN = False                # True = jen stahuje fotky, nepise do DB ani R2
IM_WIDTH = 1200                   # a0.muscache.com umi mensi verze teze fotky
LISTING_DELAY = 2.0               # pauza mezi ubytovanimi (sekundy)
PHOTO_DELAY = 0.5                 # pauza mezi fotkami uvnitr jednoho ubytovani

# --- Cloudflare R2 ---------------------------------------------------------
# Verejnou adresu kbeliku ukladame do databaze. Kdybys prechazel na vlastni
# domenu, meni se to jen tady a v databazi staci prepsat stary zaklad na novy.
R2_PUBLIC_BASE = "https://pub-7001b7da379a442383fc98f61774c56b.r2.dev"
R2_BUCKET = "guessbnb"
R2_ENDPOINT = "https://c47dc1ff421395fa0cf45bdb140b1d13.r2.cloudflarestorage.com"
# S3 nema adresare, jen klice - "slozka", kterou ukazuje konzole, je cokoliv
# pred lomitkem. Fotky tudiz lezi pod prefixem Prague/<external_id>/<poradi>.
R2_PREFIX = CITY
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")

# --- stahovani stranky -----------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Dva tvary fotek ubytovani:
#   .../im/pictures/hosting/Hosting-<id>/original/<uuid>.jpeg   (nové)
#   .../im/pictures/miso/Hosting-<id>/original/<uuid>.jpeg      (nove, druhy folder)
#   .../im/pictures/<uuid>.jpg                                  (starsi)
# Slozka mezi pictures a Hosting- muze byt jaka chce. Stary tvar nema slozku
# zadnou - a prave to ho oddeluje od fotek hostitele a ikon Airbnb, protoze
# UserProfile, AirbnbPlatformAssets i user/ VZDY maji aspon jednu slozku, takze
# do zadne z vetveni nikdy nespadnou.
# POZOR: cislo za Hosting- neni id ubytovani, ale id foto sady. Stranka
# ubytovani muze bez presmerovani nest fotky pod jinym cislem a muze v nich byt
# i blok "podobne ubytovani", takze se podle id nic nefiltruje.
PHOTO_URL_RE = re.compile(
    r"https://a0\.muscache\.com/im/pictures/"
    r"(?:(?:[a-z]+/)?Hosting-\d+/original/[0-9a-fA-F-]+|[0-9a-fA-F-]{20,})"
    r"\.(?:jpg|jpeg|png|webp)"
)


def extract_photo_urls(html):
    """Fotky ubytovani bez duplicit, v poradi, ve kterem je nabizi hostitel."""
    # JSON uvnitr <script> escapuje lomitka, tak je sjednotime na normalni /
    text = html.replace(r"\\/", "/").replace(r"\/", "/")
    return list(dict.fromkeys(PHOTO_URL_RE.findall(text)))


def normalize(url):
    """Sjednoti adresu na tvar, ktery CDN umi zmenSit.

    CSV pouziva a0.muscache.com/pictures/... a stranka /im/pictures/... - to
    iste, jen ta druha cesta se preprocessuje. Bez /im by se stahoval original
    (1,8 MB misto 150 kB) a fotka by se nevypadala jako ty ze stranky, takze by
    se ani neodfiltrovala jako duplikat.
    """
    url = (url or "").split("?")[0]
    return url.replace("muscache.com/pictures/", "muscache.com/im/pictures/")


def sized(url):
    """Pida rozlisovaci parametr CDN, at stahujeme ~150 kB misto ~210 kB."""
    return url if "?" in url else f"{url}?im_w={IM_WIDTH}"


def fetch_page(session, url):
    """HTML stranky ubytovani, prazdny retezek kdyz stranka nejde."""
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200:
            print(f"    stranka vraci {response.status_code}, beru jen fotku z CSV")
            return ""
        return response.text
    except requests.RequestException as exc:
        print(f"    stranka selhala ({exc.__class__.__name__}), beru jen fotku z CSV")
        return ""


def gallery_urls(session, listing_url, csv_picture_url, count):
    """Fotky ze stranky, doplnene o fotku z CSV, ktera vzdy dostane poradí 1."""
    urls = [normalize(u) for u in extract_photo_urls(fetch_page(session, listing_url))] if listing_url else []
    first = normalize(csv_picture_url)
    if first:
        urls = [u for u in urls if u != first]
        urls.insert(0, first)
    return list(dict.fromkeys(urls))[:count]


def download(session, url):
    """Bytes fotky, nebo None kdyz se nestahne."""
    try:
        response = session.get(sized(url), timeout=30)
        if response.status_code != 200 or not response.content:
            print(f"    fotku nelze stahnout ({response.status_code})")
            return None
        return response.content
    except requests.RequestException as exc:
        print(f"    fotku nelze stahnout ({exc.__class__.__name__})")
        return None


# --- CSV radek -> model ----------------------------------------------------
def to_int(raw):
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def to_float(raw):
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def clip(text, limit):
    """Text na delku sloupce. Airbnb obcas da jmeno delsi nez 200 znaku a to
    pydantic odmitne - kratsi jmeno nestoji nic, zahozena davka ano."""
    return text.strip()[:limit]


def czk_multiplier():
    """Násobek, který z ceny v CSV udělá koruny.

    Neznámá měna znamená, že jsme si s CSV nerozuměli – hádat tady není co,
    protože špatný převod by se v datech tvářil jako opravdu drahé ubytování.

    Kurz je pevný a s datem: CSV samo je ceník pro jedno budoucí okno (tohle
    CSV cituje 2027-09-16), takže denní kurz by byl přesnost, kterou data nemají.
    """
    if CSV_CURRENCY == "CZK":
        return 1.0
    if CSV_CURRENCY == "USD":
        return USD_TO_CZK
    if CSV_CURRENCY == "EUR":
        return EUR_TO_CZK
    if CSV_CURRENCY == "GBP":
        return GBP_TO_CZK
    print(f"CSV_CURRENCY = {CSV_CURRENCY!r} – nevím, v jaké měně je sloupec price.")
    print("Nastav 'CZK' (cena už je v korunách), nebo měnu, která svůj kurz má:")
    print(f"USD {USD_TO_CZK}, EUR {EUR_TO_CZK}, GBP {GBP_TO_CZK}.")
    raise SystemExit(1)


def parse_price(raw):
    """'$2,283.00' -> 2283.0 v CZK, prázdný nebo nulový řetězek -> None.

    Vrací vždy koruny; kolik jich je, říká CSV_CURRENCY, ne znak v řetězci.
    """
    price = to_float((raw or "").replace("$", "").replace(",", ""))
    if not price or price <= 0:
        return None
    return price * czk_multiplier()


BATHROOMS_RE = re.compile(r"\d+(?:[.,]\d+)?")


def parse_bathrooms(raw):
    """'1.5 shared baths' -> 1.5, 'Private half-bath' -> 0.5, prazdne -> None.

    CSV ma pocet koupelen jako volny text, proto cislo z retezce jen vybereme.
    'Half-bath' zadne cislo nema a polovina koupelny je 0.5, ne zadna - proto
    ten druhy vetveni.
    """
    text = (raw or "").strip()
    if not text or text == "None":
        return None
    match = BATHROOMS_RE.search(text)
    if match:
        return float(match.group().replace(",", "."))
    return 0.5 if "half" in text.lower() else None


def playable(row):
    """Da se s radkou hrat = ma cenu i sve id, bez ceny neni co hadat.

    Pouziva se na dvou mistech: pri vyberu vzorku se do nej berou jen hratelne
    radky a parse_row na stejne podmince vraci None.
    """
    return bool((row.get("id") or "").strip()) and parse_price(row.get("price")) is not None


def parse_row(row):
    """CSV radek -> ListingCreate, nebo None kdyz se radkou neda hrat."""
    if not playable(row):
        return None
    price = parse_price(row.get("price"))
    external_id = (row.get("id") or "").strip()
    return ListingCreate(
        external_id=external_id,
        city=CITY,
        country=COUNTRY,
        # CSV sloupec neighbourhood je vzdy prazdny, ctvrt zije v cleansed
        # textova policka se kraji na delku sloupce, viz clip()
        neighbourhood=clip(row.get("neighbourhood_cleansed") or "", 64) or None,
        latitude=to_float(row.get("latitude")),
        longitude=to_float(row.get("longitude")),
        name=clip(row.get("name") or "", 200) or f"Ubytovani {external_id}",
        property_type=clip(row.get("property_type") or "", 64) or "nezjisteno",
        room_type=clip(row.get("room_type") or "", 64) or "nezjisteno",
        accommodates=to_int(row.get("accommodates")) or 1,
        bedrooms=to_int(row.get("bedrooms")),
        beds=to_int(row.get("beds")),
        bathrooms=parse_bathrooms(row.get("bathrooms_text")),
        rating=to_float(row.get("review_scores_rating")),
        reviews_count=to_int(row.get("number_of_reviews")) or 0,
        price=price,
    )


# --- nahodny vyber ---------------------------------------------------------
def sample_positions(csv_path, limit, seed):
    """(vybrané pozice, kolik řádků celkem hraje) – výběr je náhodný z hratelných.

    První průchod si nechává jen čísla pozic (slovník se ~10 000 řádky by v
    paměti zabral víc než soubor sám), druhý průchod ve smyčce zpracuje jen
    vybrané. Podmínka je jasná: CSV se mezi průchody nesmí měnit.

    Výběr se nedívá do databáze, takže SAMPLE_SEED vrátí vždy tytéž řádky a
    spuštění se stejným seedem po přerušení dotáhne tu samou dávku.

    Počet hratelných řádků se vrací jen kvůli výtisku: hratelné jsou jen řádky
    s načtenou cenou, takže malé číslo u velkého CSV znamená, že jsme nepochopili
    jeho formát – ne že by v souboru data nebyla.
    """
    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        pool = [i for i, row in enumerate(csv.DictReader(csv_file)) if playable(row)]
    if not limit:
        return set(pool), len(pool)
    return set(random.Random(seed).sample(pool, min(limit, len(pool)))), len(pool)


# --- databaze --------------------------------------------------------------
def connect_db():
    """Otevre SQLite a pusti schema, stejnou cestu i tabulky jako ma api."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def imported_ids(conn):
    """External id ubytovani, ktera jsou hotova = maji aspon jednu fotku.

    Kontrola vyzaduje i fotku, takze Ctrl-C mezi vlozenim ubytovani a jeho
    fotkami se pri pristim spusteni dotahne samo.
    """
    rows = conn.execute(
        "SELECT DISTINCT l.external_id FROM listings l"
        " JOIN photos p ON p.listing_id = l.id"
    )
    return {row["external_id"] for row in rows}


def insert_listing(conn, listing, photo_urls):
    """Jedno ubytovani i s jeho fotkami v jednom commitu."""
    cursor = conn.execute(
        "INSERT INTO listings (external_id, city, country, neighbourhood, latitude,"
        " longitude, name, property_type, room_type, accommodates, bedrooms, beds,"
        " bathrooms, rating, reviews_count, price)"
        " VALUES (:external_id, :city, :country, :neighbourhood, :latitude,"
        " :longitude, :name, :property_type, :room_type, :accommodates, :bedrooms,"
        " :beds, :bathrooms, :rating, :reviews_count, :price)",
        listing.model_dump(),
    )
    for order, url in enumerate(photo_urls, start=1):
        conn.execute(
            "INSERT INTO photos (listing_id, image_url, display_order) VALUES (?, ?, ?)",
            (cursor.lastrowid, url, order),
        )
    conn.commit()


# --- R2 --------------------------------------------------------------------
def r2_client():
    if not (R2_ACCESS_KEY and R2_SECRET_KEY):
        print("Chybí klíče do R2 – nastav R2_ACCESS_KEY_ID a R2_SECRET_ACCESS_KEY,")
        print("nebo si first spusteni jen se stahovanim prepnutim DRY_RUN = True.")
        raise SystemExit(1)
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
    )


# --- jedna fota ------------------------------------------------------------
def image_kind(data):
    """Jaky to je format, podle hlavicky, ne podle pripony v adrese.

    CDN vraci jpeg i kdyz adresa konci na .png, a do R2 musime dat spravny
    Content-Type, jinak si prohlizec fotku místo zobrazeni stiahne.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return "image/jpeg", ".jpg"


def object_key(external_id, order, ext):
    """Klic souboru v R2, tj. cesta, kterou ukazuje konzole ve slozce R2_PREFIX.

    Adresa v databazi se sklada ze stejneho zakladu, jinak by fotka sedela
    jinde, nez kam ukazuje. Prazdny prefix se zahodi, at nevznikne klic s
    uvodnim lomitkem.
    """
    return "/".join(p for p in (R2_PREFIX.strip("/"), external_id, f"{order}{ext}") if p)


def store_photos(session, s3, external_id, urls):
    """Fotku stahne do pameti a rovnou posle do R2, vraci adresy do databaze.

    Na disku nic nezustava, leda bys zapnul SAVE_LOCAL. Klic v R2 je
    <R2_PREFIX>/<id>/<poradi>.<ext> a presne ta adresa se uklada do databaze.
    Duplicity se odpousteji podle obsahu, protoze Airbnb umi nabidnout tu samou
    fotku pod dvema ruznymi jmeny.
    """
    public_urls = []
    seen = set()
    for url in urls:
        data = download(session, url)
        time.sleep(PHOTO_DELAY)         # pauza patri za pozadavek, ne zakladani souboru
        if data is None:
            continue
        digest = hashlib.md5(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        order = len(public_urls) + 1
        kind, ext = image_kind(data)
        if SAVE_LOCAL:
            os.makedirs(os.path.join(PHOTO_DIR, external_id), exist_ok=True)
            path = os.path.join(PHOTO_DIR, external_id, f"{order}{ext}")
            with open(path, "wb") as photo_file:
                photo_file.write(data)
        key = object_key(external_id, order, ext)
        if s3 is None:
            print(f"    {order}. {len(data) // 1024} kB {kind}")  # suchy beh nema jiny vystup
        else:
            s3.put_object(Bucket=R2_BUCKET, Key=key, Body=data, ContentType=kind)
        public_urls.append(f"{R2_PUBLIC_BASE.rstrip('/')}/{key}")
    return public_urls


# --- cele kolo -------------------------------------------------------------
def run():
    if SAVE_LOCAL:
        os.makedirs(PHOTO_DIR, exist_ok=True)
    conn = connect_db()
    s3 = None if DRY_RUN else r2_client()
    session = requests.Session()
    session.headers.update(HEADERS)

    done = imported_ids(conn)
    print(f"V databázi je už {len(done)} ubytování s fotkami, ta přeskočím.")
    mena = ("CSV je už v korunách" if CSV_CURRENCY == "CZK"
            else f"CSV je v {CSV_CURRENCY}, násobí se {USD_TO_CZK} (kurz z {RATE_DATE})")
    print(f"Měny: {mena}, do DB vždy letí CZK.")
    # bez seedu to tahne kazdy beh jinak, ale cislo se vytiskne, takze jde po
    # preruseni opsat a dotahnout tak tu samou davku
    seed = SAMPLE_SEED if SAMPLE_SEED is not None else random.randrange(1_000_000)
    wanted, playable_count = sample_positions(LISTINGS_CSV, LIMIT, seed)
    print(f"Náhodný vzorek: {len(wanted)} z {playable_count} hratelných řádků, seed={seed}"
          + ("" if SAMPLE_SEED is not None else " (chceš-li obnovit, přepiš SAMPLE_SEED)"))
    print(f"Start: limit={LIMIT or 'bez limitu'}, dry_run={DRY_RUN}, city={CITY}, zeme={COUNTRY}")

    stats = {"vlozeno": 0, "jiz v db": 0, "bez fotek": 0, "neplatny": 0}
    try:
        with open(LISTINGS_CSV, newline="", encoding="utf-8") as csv_file:
            for position, row in enumerate(csv.DictReader(csv_file)):
                if position not in wanted:
                    continue
                try:
                    listing = parse_row(row)
                except ValidationError as error:
                    # jeden radek nesmi zastavit cely beh - dalsi mesto muze mit
                    # CSV s jinymi rozmery nez to prazske a prislo by to az tady
                    problem = error.errors()[0]
                    stats["neplatny"] += 1
                    print(f"  {row.get('id')}: preskoceno ({problem['loc'][0]}: {problem['type']})")
                    continue
                if listing is None:           # CSV se mezi pruchody zmenil
                    continue
                if listing.external_id in done:
                    stats["jiz v db"] += 1
                    continue

                urls = gallery_urls(
                    session,
                    (row.get("listing_url") or "").strip(),
                    (row.get("picture_url") or "").strip(),
                    MAX_PHOTOS,
                )
                public_urls = store_photos(session, s3, listing.external_id, urls)
                if not public_urls:
                    stats["bez fotek"] += 1
                    print(f"  {listing.external_id}: zadne fotky, preskoceno")
                    continue
                if not DRY_RUN:
                    insert_listing(conn, listing, public_urls)
                done.add(listing.external_id)
                stats["vlozeno"] += 1
                # pocitadlo sedi az od velkosti vylosovane davky, ne od LIMITu:
                # davka muze byt mensi (LIMIT=0 muze byt i 0), cast uz v DB byla
                # driv a fota se nepovedla, to vsechno jsou obsluzene radky davky
                obslouzeno = sum(stats.values())
                print(f"  {listing.external_id}: {len(public_urls)} fotek, "
                      f"{listing.price:,.0f} / noc, zbyva {len(wanted) - obslouzeno} z davky")
                time.sleep(LISTING_DELAY)
    except KeyboardInterrupt:
        print("\nPřerušeno – co je zapsané, to v databázi zůstává. Spusť znovu a devam.")
        print("Bez SAMPLE_SEED tě čeká nová náhodná dávka. Tu předchozí dotáhneš tak,")
        print("že SAMPLE_SEED přepíšeš na číslo, které se vypsalo na začátku.")
    finally:
        conn.close()

    titulek = "\nSuchy beh, do DB ani do R2 nic neslo. Shrnutí: " if DRY_RUN else "\nShrnutí: "
    print(titulek + ", ".join(f"{k}={v}" for k, v in stats.items()))


def test_page(url):
    """Slouzi jen k nahlednuti, co scraper najde na jedne strance."""
    session = requests.Session()
    session.headers.update(HEADERS)
    urls = extract_photo_urls(fetch_page(session, url))
    print(f"Nalezeno {len(urls)} fotek ubytovani:")
    for photo_url in urls:
        print("  ", sized(photo_url))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "test":
        test_page(sys.argv[2])
    else:
        run()
