# GUESSBNB – scraper dat (ETL)

`scraper.py` přečte `listings.csv`, z Airbnb stránky každého ubytování stáhne jeho
fotky, pošle je rovnou do Cloudflare R2, a do SQLite zapisuje řádek ubytování
plus řádky fotek s odkazy na cloud. Fotky projdou pamětí, na disku nic nenechávají
– výchozí chování je nic neukládat, volitelně `SAVE_LOCAL = True`.

```
listings.csv ──► stránka na Airbnb ──► fotky v RAM ──► R2
      │                                                 │
      └── údaje z CSV ──────────────────────────────────┴──► data/guessbnb.db
                                    (listings + photos, image_url = veřejná adresa)
```

Ubytování se neberou v pořadí, v jakém leží v CSV, ale **náhodně z celého
souboru** – hra nesmí stavět jen na tom, jak je seřadil Airbnb.

Všechno je jedna cesta, která se dá kdykoli přerušit `Ctrl-C` a spustit znovu –
to už zapsané přeskočí. Která dávka je „ta samá“ řeší `SAMPLE_SEED`.

---

## Co potřebuješ

- Python 3.11 (v repozitáři už je `.venv`)
- `listings.csv` v kořeni repozitáře – 11 804 řádků, z toho 10 342 s cenou
- přístup do R2: bucket `guessbnb`, access key + secret key, a zapnutý
  **public bucket** (bez něj jsou fotky ve hře nedostupné)
- připojení k internetu (Airbnb i R2)

Skript se spouští **z kořene repozitáře**, protože importuje `src.models` a
`src.repositories`.

---

## 1) Příprava

```powershell
# PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -c "import boto3, requests, pydantic; print('ok')"
```

```bash
# Git Bash
source .venv/Scripts/activate
pip install -r requirements.txt
python -c "import boto3, requests, pydantic; print('ok')"
```

---

## 2) Klíče do R2

Skript čte proměnné prostředí `R2_ACCESS_KEY_ID` a `R2_SECRET_ACCESS_KEY`.
**Nepíšou se do kódu ani do gitu** – `.env` je v `.gitignore`, ale skript si sám
nezve, takže nastav proměnné v shellu, ve kterém spouštíš:

```powershell
# PowerShell – platí jen pro tohle okno, nastav si je pokaždé znovu
$env:R2_ACCESS_KEY_ID = "abcd1234..."
$env:R2_SECRET_ACCESS_KEY = "secret..."
```

```bash
# Git Bash
export R2_ACCESS_KEY_ID="abcd1234..."
export R2_SECRET_ACCESS_KEY="secret..."
```

Bucket, endpoint, veřejnou doménu i složku `Prague`, pod kterou fotky v kbelíku
leží, měníš nahoře v [scraper.py](scraper.py) v sekci `--- Cloudflare R2 ---`.
Veřejná adresa, která se ukládá do databáze, je
`R2_PUBLIC_BASE/R2_PREFIX/<external_id>/<pořadí>.jpg`, tedy
`…/Prague/643856540801546198/1.jpg`. R2 nemá adresáře – „složka“ je jen prefix
klíče, v konzoli se ale `Prague` zobrazí jako složka a pod ní každé ubytování
jako další.

---

## 3) Test: co scraper najde na jedné stránce

Bez klíčů, bez zápisu, bez uploadu – jen regex a Airbnb:

```bash
python scraper.py test https://www.airbnb.com/rooms/1571705115265609740
```

Očekávej výtisk počtu fotek a jejich adres (aktuálně 22). Vyzkoušej i další tvary
odkazů, regex má chytit všechny tři:

| typ ubytování | spusť | mělo by vyjít |
|---|---|---|
| nové (`/hosting/Hosting-…`) | `python scraper.py test https://www.airbnb.com/rooms/1571705115265609740` | ~22 |
| nové (`/miso/Hosting-…`) | `python scraper.py test https://www.airbnb.com/rooms/1090345216121505149` | ~8 |
| staré (`/pictures/<uuid>.jpg`) | `python scraper.py test https://www.airbnb.com/rooms/25810946` | ~14 |

Mezi fotkami nesmí být nic s `UserProfile`, `user/`, `Favicons` ani
`AirbnbPlatformAssets` – to jsou fotky hostitele a ikony Airbnb.

`0 fotek` znamená, že se stránka vůbec nepřečetla (viz oddíl *Co když něco nejde*).

---

## 4) Test: nasucho

V [scraper.py](scraper.py) nastav:

```python
LIMIT = 3
DRY_RUN = True
```

```bash
python scraper.py
```

Potvrdí to, že se CSV čte, stránka načte a fotky stáhnou. Každou fotku vypíše
velikostí a typem, protože jiný výstup takový běh nemá – na disk se nepíše nic:

```
V databázi je už 0 ubytování s fotkami, ta přeskočím.
Měny: CSV je už v korunách, do DB vždy letí CZK.
Náhodný vzorek: 3 z 10342 hratelných řádků, seed=812447 (chceš-li obnovit, přepiš SAMPLE_SEED)
Start: limit=3, dry_run=True, city=Prague, zeme=Czechia
    1. 149 kB image/jpeg
    2. 149 kB image/jpeg
    3. 149 kB image/jpeg
    ...
Suchy beh, do DB ani do R2 nic neslo. Shrnutí: vlozeno=3, jiz v db=0, bez fotek=0, neplatny=0
```

Kolem 150 kB na fotku je v pořádku (`?im_w=1200`); 1,8 MB znamená, že se stahuje
originál bez `/im` v cestě. Prázdné `data/guessbnb.db` se vytvoří, ale řádky v něm
nejsou, a `photos/` vůbec nevznikne. Chceš-li fotky vidět i na disku, přepni
`SAVE_LOCAL = True`.

---

## 5) Test: naostro, pět ubytování

```python
LIMIT = 5
DRY_RUN = False
```

```bash
python scraper.py
```

Výtisk po spuštění vypadá takto:

```
V databázi je už 0 ubytování s fotkami, ta přeskočím.
Měny: CSV je už v korunách, do DB vždy letí CZK.
Náhodný vzorek: 5 z 10342 hratelných řádků, seed=412903 (chceš-li obnovit, přepiš SAMPLE_SEED)
Start: limit=5, dry_run=False, city=Prague, zeme=Czechia
  1090345216121505149: 8 fotek, 996 / noc, zbyva 4 z davky
  643856540801546198: 4 fotek, 2 283 / noc, zbyva 3 z davky
  ...
Shrnutí: vlozeno=5, jiz v db=0, bez fotek=0, neplatny=0
```

Která ubytování to jsou, pokaždé rozhodne los. Číslo seedu se vypisuje právě
proto, aby šlo po přerušení opsat do `SAMPLE_SEED` a dotáhnout tu samou dávku.

**Než uděláš cokoliv dalšího, otevři jednu uloženou adresu v prohlížeči:**

```bash
python -c "import sqlite3; print(sqlite3.connect('data/guessbnb.db').execute('select image_url from photos limit 1').fetchone()[0])"
```

Adresa musí v prohlížeči zobrazit fotku. Když vrací 403/404, **stopni to** a
zapni public bucket v R2 (bucket → Settings → Public bucket → Domain). Databáze
si jinak sešmodrchá tisíce mrtvých odkazů. Pak si ověř i upload v R2 – ve složce
`Prague` by mělo sedět `<external_id>/<pořadí>.jpg`.

---

## 6) Kontrola dat v databázi

```bash
python -c "import sqlite3 as s; c=s.connect('data/guessbnb.db'); [print(q, c.execute(q).fetchall()) for q in ['select count(*) from listings','select count(*) from photos','select min(price),max(price) from listings']]"
```

A rozpad fotek na ubytování (žádné ubytování bez fotky, žádné mezery v
`display_order`):

```bash
python -c "import sqlite3 as s; c=s.connect('data/guessbnb.db'); print(c.execute('select count(*) from listings l where not exists (select 1 from photos p where p.listing_id=l.id)').fetchone()); print(c.execute('select listing_id,count(*),min(display_order),max(display_order) from photos group by listing_id limit 5').fetchall())"
```

Čeká se: `0` ubytování bez fotky, u každého `min=1` a `max=počet fotek`, ceny
v stokorunách až tisících (ne 0,99 – to by znamenalo špatné parsování měny).

A nakonec přesné čtení, které bude dělat hra – náhodné ubytování, které fotky má:

```bash
python -c "import sqlite3 as s; c=s.connect('data/guessbnb.db'); r=c.execute('select l.id,l.name,l.price from listings l join photos p on p.listing_id=l.id group by l.id order by random() limit 1').fetchone(); print(r, c.execute('select count(*) from photos where listing_id=?',(r[0],)).fetchone()[0], 'fotek')"
```

---

## 7) Plný běh

Nejdřív si změř čas na dvacítce – `LIMIT = 20` a přečti si, jak dlouho to trvalo:

```bash
time python scraper.py     # PowerShell: Measure-Command { python scraper.py }
```

Přibližný rozpočet (10 342 řádků s cenou, ~160 kB na fotku):

Je to horní odhad – počítá s 10 342 ubytováními, která mají cenu, a s tím, že
každé vytáhne plný počet fotek. Spousta ubytování má fotek míň, takže to reálně
bude rychlejší. Trvá to `3 s + 0,9 s · počet fotek` na ubytování (stránka, fotky, prodlevy):

| `MAX_PHOTOS` | fotek | velikost R2 | čas |
|---|---|---|---|
| 3 | ≤ 31 000 | ≤ 5 GB | ~16 h |
| 4 | ≤ 41 000 | ≤ 7 GB | ~19 h |
| 8 | ≤ 83 000 | ≤ 13 GB | ~29 h |

Na hadání stačí 3–4 fotky, osm je zbytek. Pak nastav:

```python
LIMIT = 0          # 0 = projít celý CSV soubor
MAX_PHOTOS = 4
DRY_RUN = False
LISTING_DELAY = 2.0
```

```bash
python scraper.py
```

Nebo to přerušovat a pokračovat po částech – `Ctrl-C` je vždy bezpečný, zapsaná
ubytování zůstávají a příště se přeskočí:

```python
LIMIT = 500              # dnes 500 náhodných
SAMPLE_SEED = 412903     # číslo z předchozího výtisku, chceš-li dotáhnout tutéž dávku
```

`LIMIT` je velikost **náhodné dávky**, ne ukazatel, kde pokračuješ. Bez seedu
každé spuštění losuje nové ubytování odjinud (co už je v databázi, se přeskočí,
proto bývá `vlozeno` o pár nižší než `LIMIT`); se seedem z předchozího výtisku
losuje tytéž řádky, takže po `Ctrl-C` zbytek doplní. `LIMIT = 0` je celý zbytek
najednou.

Průběh můžeš sledovat v druhém okně:

```bash
python -c "import sqlite3 as s,time
while True: c=s.connect('data/guessbnb.db'); print(c.execute('select count(*) from listings').fetchone()[0], c.execute('select count(*) from photos').fetchone()[0]); c.close(); time.sleep(60)"
```

---

## Nastavení

Všechno je nahoře v [scraper.py](scraper.py), žádné argumenty příkazového řádku:

| proměnná | výchozí | smysl |
|---|---|---|
| `LISTINGS_CSV` | `listings.csv` | kde je CSV s ubytováními |
| `SAVE_LOCAL` | `False` | `True` = fotku navyse nech na disku, jinak žije jen v RAM a v R2 |
| `PHOTO_DIR` | `photos` | složka jen pro `SAVE_LOCAL = True` |
| `CITY` | `Prague` | CSV sloupec `city` nemá, do DB jde tahle hodnota |
| `COUNTRY` | `Czechia` | země na kartě; CSV ji taky nemá. Přidáváš město, přidáváš řádek vedle `CITY` |
| `CSV_CURRENCY` | `CZK` | měna sloupce `price` v tom kterém CSV. `CZK` = ber jak je, `USD` = přepočítej. **Do DB vždy letí koruny** |
| `USD_TO_CZK` / `RATE_DATE` | `23.1` / `2026-10-31` | kurz a datum, kdy byl pořízen; platí jen pro `CSV_CURRENCY = "USD"` |
| `MAX_PHOTOS` | `8` | strop fotek na ubytování |
| `LIMIT` | `500` | velikost náhodné dávky ubytování, `0` = všechny |
| `SAMPLE_SEED` | `None` | `None` = každé spuštění jiný výběr, číslo = pořád ten samý (obnovení přerušené dávky) |
| `DRY_RUN` | `False` | `True` = jen stahování, žádný R2 ani zápis do DB |
| `IM_WIDTH` | `1200` | šířka, kterou vyžaduje od CDN Airbnb |
| `LISTING_DELAY` | `2.0` | pauza mezi ubytováními (sekundy) |
| `PHOTO_DELAY` | `0.5` | pauza mezi fotkami |
| `R2_PUBLIC_BASE` | `https://pub-…r2.dev` | základ adresy, která se ukládá do `photos.image_url` |
| `R2_PREFIX` | `CITY` (`Prague`) | složka v kbelíku, pod kterou fotky leží; prázdné = bez složky |
| `R2_BUCKET` / `R2_ENDPOINT` | `guessbnb` / `…r2.cloudflarestorage.com` | kam se posílají soubory |

Databáze je `data/guessbnb.db`, schema v [src/repositories/schema.py](src/repositories/schema.py).
Schéma ale tabulky jen zakládá (`CREATE TABLE IF NOT EXISTS`), takže změna
schématu do už existující databáze **nikdy** nezasáhne – scraper by pak na nové
sloupce narazil s „table listings has no column named …“. Jestli proto musíš
běhet import znovu, se rozhoduje takhle:

* **nový sloupec, který má pro všechny stávající řádky tu samou hodnotu** →
  jednou `ALTER` a import opakovat nemusíš:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/guessbnb.db'); c.execute(\"ALTER TABLE listings ADD COLUMN country TEXT NOT NULL DEFAULT 'Czechia'\"); c.commit()"
  ```

  `NOT NULL` SQLite u přidaného sloupce dovolí jen s výchozí hodnotou, a ta se
  okamžitě doplní i do existujících řádků – `UPDATE` ani netřeba. Takhle se
  `country` se přidávalo takhle: 500 ubytování i 3 239 fotek zůstaly v DB.
  Sloupec je pak až nakonec výčtu a nese ten `DEFAULT`, což je jediný rozdíl
  oproti čerstvě založené databázi.
* **cokoliv jiného** (přejmenování, typ, `CHECK`) → smaž `data/` a spusť znovu
  („Reset úplně ze všeho“ níže).

Po `ALTER`u se import opakovat nemusí ani příštím spuštěním: tech 500 už v DB
je, takže je scraper přeskočí (`jiz v db=500`) a nechají se dohazovat jen nová
ubytování. Větší vzorek nedostaneš dalším během se stejným seedem, ale novým
`SAMPLE_SEED` (nebo větším `LIMIT`).

Které CSV sloupce míří do `listings` (a proč právě ty):

| sloupec v DB | ze CSV | poznámka |
|---|---|---|
| `external_id` | `id` | **jediné správné propojení** – `name` není unikátní, 354 názvů v CSV patří aspoň dvěma různým ubytováním |
| `city`, `country` | **ne z CSV** | CSV ani jeden nemá (`country_code` v něm taky není), jsou to konstanty `CITY` a `COUNTRY` nahoře ve skriptu |
| `neighbourhood` | `neighbourhood_cleansed` | CSV sloupec `neighbourhood` je vždycky prázdný |
| `latitude`, `longitude` | `latitude`, `longitude` | na mapu; jako odhad ceny je slabé (62 % ubytování je do 2 km od centra) |
| `room_type` | `room_type` | Entire home/apt 2 920 / Private room 1 683 / Shared room 690 (medián ceny) |
| `beds`, `bathrooms` | `beds`, `bathrooms_text` | `bathrooms_text` je volný text, „Half-bath“ = 0,5 |
| `accommodates`, `bedrooms`, `property_type`, `rating`, `reviews_count`, `price` | stejnojmenné | byly v databázi už dřív |

Zbylé sloupce CSV stojí za zmínku málo: `rating`, `minimum_nights` a superhost
(+9 %) mají na cenu vlivej slabý a `instant_bookable`, `squared_spaces` ani
`license` jsou v tomhle exportu úplně prázdný.
Pod složkou `R2_PREFIX` (`Prague`) má fotka v R2 i v databázi čisté číslo
`<external_id>/<pořadí>.<přípona>` (`Prague/643856540801546198/1.jpg`).
Příponu i `Content-Type` určuje skript z hlavičky bajtů, ne z přípony v adrese
od Airbnb – CDN umí vrátit jpeg i na adrese končící `.png`, a špatný
`Content-Type` by způsobil, že si prohlížeč fotku stáhne místo aby ji zobrazil.

**Reset úplně ze všeho** – mažeš databázi, plus `photos/` pokud jsi běžel s
`SAVE_LOCAL = True`:

```bash
rm -rf data photos          # PowerShell: Remove-Item -Recurse -Force data, photos
```

---

## Co když něco nejde

| co vidíš | co s tím |
|---|---|
| `Chybí klíče do R2` | shell, ve kterém spouštíš, nemá nastavené `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` |
| `stranka vraci 403` / `stranka selhala` | Airbnb blokuje. Zvyš `LISTING_DELAY` (2 → 5), dělej menší `LIMIT`, zkus to jindy. Fotka z CSV se použije i tak, takže ubytování nespadne. |
| `Nalezeno 0 fotek ubytovani` ve `test` | stránka se nenačetla (403, nebo je ubytování nové). Zkus `curl -I` na ten odkaz. |
| `fotku nelze stahnout (404)` | CDN už fotku nemá, přeskočí se |
| `nevím, v jaké měně je sloupec price` | CSV je v jiné měně, než říká `CSV_CURRENCY` – nastav ji na tu, v které je `price` (CZK/USD/EUR/GBP) |
| `preskoceno (name: string_too_long)` | radek nesedí do DDL; scraper si ho poznamená do `neplatny` a běží dál, jedno ubytování za to celý vzorek nezaplatí |
| `NoSuchBucket` | špatné `R2_BUCKET` nebo `R2_ENDPOINT` (account ID v endpointu) |
| `InvalidAccessKeyId` / `SignatureDoesNotMatch` | špatné nebo zrušené klíče v R2 |
| `AccessDenied` při uploadu | token nemá právo zápisu do bucketu (policy `s3:PutObject`) |
| 403/404 ve prohlížeči | public bucket není zapnutý, nebo je `R2_PUBLIC_BASE` jiná než ta, kterou R2 ukazuje |
| `unable to open database file` | nespustil jsi to z kořene repozitáře |
| `UnicodeEncodeError` | starší verze skriptu; aktuální nastavuje výstup na UTF-8 samo |

---

## Co zatím ověřeno není

Ověřeno na skutečných datech (dočasná DB, falešné R2, které zaznamenalo každé
`put_object`): regex na všechny tři tvary odkazů, vyloučení fotek hostitele a
ikon, fotky za sebou s `display_order` 1..N, deduplikace podle obsahu, odeslání
pouze z RAM (s `SAVE_LOCAL = False` adresář `photos/` nevznikne), správný
`Content-Type`, obnovení po přerušení, ceny a `rating=None`. Nové sloupce
(`neighbourhood`, `latitude`, `longitude`, `room_type`, `beds`, `bathrooms`)
prošlo `parse_row()` všech 10 342 řádků s cenou bez jediné výjimky, včetně
zápisu do nového schématu, načtení přes `listing_repository` a toho, že `CHECK`
odmítne souřadnice mimo rozsah a `NULL` naopak projde. Nad náhodným výběrem
stejný seed vrátil stejných 500 pozic, jiný seed jen ~20 překryvů (což je u
500 z 10 342 očekávatelných ~24), `LIMIT = 0` vrátil všech 10 342 a celé
`run()` na simulovaných fotkách vylosovalo a zapsalo dávku včetně nových
sloupců; druhé kolo se stejným seedem nepřidalo nic.

`country` prošlo stejnou cestou: čerstvá databáze ho má v `pragma table_info`
a `NOT NULL` do něj nenechá zapsat `None`, a celé `run()` zapsalo 500 řádků
s `country = 'Czechia'` a **se stejnými cenami** jako před přidáním měny
(min 549, medián 2 666, max 243 815 Kč) – `CSV_CURRENCY = "CZK"` jen násobí
jedničkou. `USD` větev násobí 23,1 (`$180` → 4 158 Kč) a neznámá měna (`"XXX"`)
skript ukončí s hláškou, takže špatně označený soubor se k datům nedostane.
`ALTER` cesta výše je odběhaná na reálné DB: po ní prošel `db.connect()`,
čtení přes `listing_repository` i vložení dalšího řádku scraperem.

**Neověřeno, udělej jako první:** skutečný upload do R2 a to, že veřejná adresa
`pub-…r2.dev/Prague/<id>/1.jpg` načte obrázek v prohlížeči. K tomu potřebuješ klíče,
proto je krok 5 první ostrý test.

Ještě pár věcí k datům: CSV nemá sloupec `city` ani `country` (proto
`CITY = "Prague"` a `COUNTRY = "Czechia"`; pro New York se mění oba dva) a
`Hosting-<id>` v adrese fotek je ID sady fotek, ne ID ubytování – stránka
umí bez přesměrování nést fotky pod jiným číslem a bývá na ní i blok
*podobná ubytování*, proto se podle ID nic nefiltruje.

K cenám: částky ve sloupci `price` jsou **koruny** i přes rozporuplný `$`,
kterým začíní všech 10 342 ceněných řádků (`$996.00` je 996 Kč – ten samý
řádek má vedle v `price_quote_raw` `1 night x Kč 995.98`, kde „Kč“ nebo „CZK“
je celkem 10 353 z 11 804 řádků). Znak v řetězci o měně tedy neříká nic a
`parse_price()` se na něj nespolehne: měna se **deklaruje** v `CSV_CURRENCY` a
do DB vždycky jdou koruny – `CZK` násobí jedničkou, `USD` násobí `USD_TO_CZK`,
na jiné hodnotě skript rovnou odmítne spustit místo aby tipoval. Kurz je
napevno v kódu a s datem, protože i cena v CSV je jen nabídka na jedno
libovolné budoucí okno (tenhle export cituje `2027-09-16`) – kurz k přesnému
dni by byla falešná přesnost. New York proto nejsou úpravy schématu, ale
`CSV_CURRENCY = "USD"`, `CITY` a `COUNTRY`; **před prvním importem** se podívej do
prvních řádků CSV na `price` a `price_quote_raw`, jakou měnu tam jmenují, a po
importu porovnej medián – pro New York ~180 $ · 23 ≈ 4 000 Kč, tedy ani 180,
ani 4 000 000.
A v CSV jsou 84 ceny nad 20 000 Kč a 18 nad 100 000 Kč (největší 1 158 408 Kč
za noc), `CHECK (price > 0)` je nezastaví. Náhodný výběr je neodstraní – v
náhodné padesátce jich bývá typicky ~4 nad 20 000 Kč a ~1 nad sto tisíc. Hře
na hadání takový řádek rozbouje kolo, takže až na něj narazíš, zvaž horní mez:
buď filtr v `parse_row()`, který takový řádek nevrátí, nebo `CHECK` rovnou v
[schema.py](src/repositories/schema.py).

---

## Pravidla

Načítání stránek Airbnb je v rozporu s jejich podmínkami použití, i když
`robots.txt` konkrétně `/rooms/<id>` nezakazuje. Nech `LISTING_DELAY` na 2 s a
výš, neměň User-Agent na prázdný, nedělej paralelní požadavky a ber to jako
zdroj dat pro školní projekt, ne jako trvalou infrastrukturu.
