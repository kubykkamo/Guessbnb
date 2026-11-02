"""ETL pipeline: listings.csv -> photos from Airbnb -> R2 -> SQLite.

Run:  python scraper.py
Test of one page (only prints the photos, saves nothing):
         python scraper.py test https://www.airbnb.com/rooms/1571705115265609740

The photo flies from Airbnb into memory and from there straight into R2, so nothing
sits on disk (SAVE_LOCAL = True additionally keeps it in photos/). The database
stores the address <R2_PUBLIC_BASE>/<external_id>/<order>.<ext>.
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

# Listing names in the CSV contain asterisks and emoji, the windows console would
# crash on them with UnicodeEncodeError in the middle of the whole run.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- settings --------------------------------------------------------------
LISTINGS_CSV = "listings.csv"     # put the path to your listings.csv here
SAVE_LOCAL = False                # True = keep the photo on the disk too
PHOTO_DIR = "photos"              # folder only for SAVE_LOCAL = True
CITY = "Berlin"                    # there is no city column in the CSV, we play as this one
COUNTRY = "Germany"                # there is no country column in the CSV either
# Currency in which the price column of LISTINGS_CSV is. To the DB always go crowns,
# so it has to be declared - the symbol in the string cannot be relied on (Prague
# has the $ sign in front of the crowns). Adding another city costs two lines below,
# not a new schema.
CSV_CURRENCY = "EUR"               # "CZK" = read as is, "USD" = convert
USD_TO_CZK = 23.1
EUR_TO_CZK = 24.36
GBP_TO_CZK = 29.22             # valid only for CSV_CURRENCY = "USD"
RATE_DATE = "2026-10-31"           # when the rate was taken, so it does not hang here without a date
MAX_PHOTOS = 8                    # max photos for one listing
LIMIT = 500                    # 0 = all of the 11 804 rows, otherwise number of listings
SAMPLE_SEED = 1           # number = always the same random selection (resuming a run)
DRY_RUN = False                # True = only downloads photos, does not write to DB or R2
IM_WIDTH = 1200                   # a0.muscache.com can do smaller versions of the same photo
LISTING_DELAY = 2.0               # pause between listings (seconds)
PHOTO_DELAY = 0.5                 # pause between photos inside one listing

# --- Cloudflare R2 ---------------------------------------------------------
# We store the public address of the bucket in the database. If you switch to your
# own domain, it changes only here and in the database it is enough to rewrite the
# old base to the new one.
R2_PUBLIC_BASE = "https://pub-7001b7da379a442383fc98f61774c56b.r2.dev"
R2_BUCKET = "guessbnb"
R2_ENDPOINT = "https://c47dc1ff421395fa0cf45bdb140b1d13.r2.cloudflarestorage.com"
# S3 has no directories, only keys - the "folder" the console shows is anything
# before a slash. The photos therefore lie under the prefix Prague/<external_id>/<order>.
R2_PREFIX = CITY
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")

# --- page download ---------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Two shapes of listing photos:
#   .../im/pictures/hosting/Hosting-<id>/original/<uuid>.jpeg   (new)
#   .../im/pictures/miso/Hosting-<id>/original/<uuid>.jpeg      (new, second folder)
#   .../im/pictures/<uuid>.jpg                                  (older)
# The folder between pictures and Hosting- can be anything. The old shape has no
# folder at all - and that is exactly what separates it from host photos and Airbnb
# icons, because UserProfile, AirbnbPlatformAssets and user/ ALWAYS have at least
# one folder, so they never fall into either branch.
# WARNING: the number after Hosting- is not the listing id, it is the id of the
# photo set. The listing page can carry photos under a different number without a
# redirect and there can be a "similar listings" block among them, so nothing is
# filtered by id.
PHOTO_URL_RE = re.compile(
    r"https://a0\.muscache\.com/im/pictures/"
    r"(?:(?:[a-z]+/)?Hosting-\d+/original/[0-9a-fA-F-]+|[0-9a-fA-F-]{20,})"
    r"\.(?:jpg|jpeg|png|webp)"
)


def extract_photo_urls(html):
    """Listing photos without duplicates, in the order in which the host offers them."""
    # JSON inside <script> escapes slashes, so we unify them to a normal /
    text = html.replace(r"\\/", "/").replace(r"\/", "/")
    return list(dict.fromkeys(PHOTO_URL_RE.findall(text)))


def normalize(url):
    """Unifies the address to the shape the CDN can resize.

    The CSV uses a0.muscache.com/pictures/... and the page /im/pictures/... - the
    same thing, only the second path gets preprocessed. Without /im the original
    would download (1.8 MB instead of 150 kB) and the photo would not look like the
    ones from the page, so it would not even get filtered out as a duplicate.
    """
    url = (url or "").split("?")[0]
    return url.replace("muscache.com/pictures/", "muscache.com/im/pictures/")


def sized(url):
    """Adds the CDN resolution parameter so we download ~150 kB instead of ~210 kB."""
    return url if "?" in url else f"{url}?im_w={IM_WIDTH}"


def fetch_page(session, url):
    """HTML of the listing page, empty string when the page does not work."""
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
    """Photos from the page, filled in with the photo from the CSV, which always gets order 1."""
    urls = [normalize(u) for u in extract_photo_urls(fetch_page(session, listing_url))] if listing_url else []
    first = normalize(csv_picture_url)
    if first:
        urls = [u for u in urls if u != first]
        urls.insert(0, first)
    return list(dict.fromkeys(urls))[:count]


def download(session, url):
    """Photo bytes, or None when it does not download."""
    try:
        response = session.get(sized(url), timeout=30)
        if response.status_code != 200 or not response.content:
            print(f"    fotku nelze stahnout ({response.status_code})")
            return None
        return response.content
    except requests.RequestException as exc:
        print(f"    fotku nelze stahnout ({exc.__class__.__name__})")
        return None


# --- CSV row -> model ------------------------------------------------------
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
    """Text to the length of the column. Airbnb sometimes gives a name longer than
    200 characters and pydantic refuses that - a shorter name costs nothing, a
    discarded batch does."""
    return text.strip()[:limit]


def czk_multiplier():
    """Multiplier that turns the price in the CSV into crowns.

    An unknown currency means we did not understand each other with the CSV - there
    is nothing to guess here, because a wrong conversion would look in the data like
    a really expensive listing.

    The rate is fixed and with a date: the CSV itself is a price list for one future
    window (this CSV quotes 2027-09-16), so a daily rate would be a precision the
    data do not have.
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
    """'$2,283.00' -> 2283.0 in CZK, empty or zero string -> None.

    Always returns crowns; how many of them there are is said by CSV_CURRENCY, not
    by the character in the string.
    """
    price = to_float((raw or "").replace("$", "").replace(",", ""))
    if not price or price <= 0:
        return None
    return price * czk_multiplier()


BATHROOMS_RE = re.compile(r"\d+(?:[.,]\d+)?")


def parse_bathrooms(raw):
    """'1.5 shared baths' -> 1.5, 'Private half-bath' -> 0.5, empty -> None.

    The CSV has the number of bathrooms as free text, so we just pick the number
    out of the string. 'Half-bath' has no number at all and half a bathroom is 0.5,
    not none - that is why the second branch.
    """
    text = (raw or "").strip()
    if not text or text == "None":
        return None
    match = BATHROOMS_RE.search(text)
    if match:
        return float(match.group().replace(",", "."))
    return 0.5 if "half" in text.lower() else None


def playable(row):
    """Can the row be played = it has a price and its id, without a price there is
    nothing to guess.

    Used in two places: when selecting the sample only playable rows are taken into
    it, and parse_row returns None on the same condition.
    """
    return bool((row.get("id") or "").strip()) and parse_price(row.get("price")) is not None


def parse_row(row):
    """CSV row -> ListingCreate, or None when the row cannot be played."""
    if not playable(row):
        return None
    price = parse_price(row.get("price"))
    external_id = (row.get("id") or "").strip()
    return ListingCreate(
        external_id=external_id,
        city=CITY,
        country=COUNTRY,
        # the CSV neighbourhood column is always empty, the quarter lives in cleansed
        # text fields are cut to the length of the column, see clip()
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


# --- random selection ------------------------------------------------------
def sample_positions(csv_path, limit, seed):
    """(selected positions, how many rows play in total) - the selection is random
    from the playable ones.

    The first pass keeps only the position numbers (a dictionary with ~10 000 rows
    would take more memory than the file itself), the second pass in the loop
    processes only the selected ones. The condition is clear: the CSV must not
    change between the passes.

    The selection does not look into the database, so SAMPLE_SEED always returns the
    same rows and a run with the same seed after an interruption finishes the same batch.

    The number of playable rows is returned only because of the printout: playable
    are only rows with a loaded price, so a small number for a big CSV means we did
    not understand its format - not that the file would have no data.
    """
    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        pool = [i for i, row in enumerate(csv.DictReader(csv_file)) if playable(row)]
    if not limit:
        return set(pool), len(pool)
    return set(random.Random(seed).sample(pool, min(limit, len(pool)))), len(pool)


# --- database --------------------------------------------------------------
def connect_db():
    """Opens SQLite and runs the schema, the same path and the same tables as the api has."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def imported_ids(conn):
    """External ids of listings that are done = they have at least one photo.

    The check requires a photo too, so a Ctrl-C between inserting the listing and
    its photos gets finished by itself on the next run.
    """
    rows = conn.execute(
        "SELECT DISTINCT l.external_id FROM listings l"
        " JOIN photos p ON p.listing_id = l.id"
    )
    return {row["external_id"] for row in rows}


def insert_listing(conn, listing, photo_urls):
    """One listing with its photos in one commit."""
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


# --- one photo -------------------------------------------------------------
def image_kind(data):
    """Which format it is, by the header, not by the extension in the address.

    The CDN returns jpeg even when the address ends with .png, and we have to give
    R2 the right Content-Type, otherwise the browser downloads the photo instead of
    displaying it.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return "image/jpeg", ".jpg"


def object_key(external_id, order, ext):
    """File key in R2, i.e. the path the console shows in the R2_PREFIX folder.

    The address in the database is built from the same base, otherwise the photo
    would sit somewhere else than where it points. An empty prefix gets dropped so
    there is no key with a leading slash.
    """
    return "/".join(p for p in (R2_PREFIX.strip("/"), external_id, f"{order}{ext}") if p)


def store_photos(session, s3, external_id, urls):
    """Downloads the photo into memory and sends it straight to R2, returns addresses for the database.

    Nothing stays on disk unless you turn on SAVE_LOCAL. The key in R2 is
    <R2_PREFIX>/<id>/<order>.<ext> and exactly that address is stored in the
    database. Duplicates are forgiven by content, because Airbnb can offer the same
    photo under two different names.
    """
    public_urls = []
    seen = set()
    for url in urls:
        data = download(session, url)
        time.sleep(PHOTO_DELAY)         # the pause belongs after the request, not creating the file
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
            print(f"    {order}. {len(data) // 1024} kB {kind}")  # a dry run has no other output
        else:
            s3.put_object(Bucket=R2_BUCKET, Key=key, Body=data, ContentType=kind)
        public_urls.append(f"{R2_PUBLIC_BASE.rstrip('/')}/{key}")
    return public_urls


# --- the whole round -------------------------------------------------------
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
    # without a seed it draws differently every run, but the number is printed, so
    # after an interruption you can copy it and finish the same batch
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
                    # one row must not stop the whole run - another city can have
                    # a CSV with other dimensions than the prague one and it would show up only here
                    problem = error.errors()[0]
                    stats["neplatny"] += 1
                    print(f"  {row.get('id')}: preskoceno ({problem['loc'][0]}: {problem['type']})")
                    continue
                if listing is None:           # the CSV changed between the passes
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
                # the counter is right only from the size of the drawn batch, not from LIMIT:
                # the batch can be smaller (LIMIT=0 can be 0 too), part was already in the DB
                # earlier and a photo did not work out, all of that is handled rows of the batch
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
    """Serves only for a peek at what the scraper finds on one page."""
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
