"""DDL according to the ERD (docs/ERD.drawio). Runs in db.connect().

An added column does not get into an already existing database by itself - every
table here is only CREATE TABLE IF NOT EXISTS, so it does not reach the half-done
schema, and an INSERT into the new column then hits "table listings has no column
named ...".

A column that has the same value for all existing rows is enough to add by hand
once - for `country` it ran like this:

    ALTER TABLE listings ADD COLUMN country TEXT NOT NULL DEFAULT 'Czechia';

SQLite allows NOT NULL on an added column only with a default value - and that one
gets filled into the existing rows immediately, so no UPDATE is needed. The result
differs from a freshly created DB only decoratively: the column is only at the end
and carries that DEFAULT. Nothing speaks against it, the model and the scraper both
give `country` always.

Everything else (renaming, type, CHECK) cannot be done this way - delete
data/guessbnb.db and run the scraper again, README "Reset completely from everything".
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    auth0_id     TEXT    NOT NULL UNIQUE,
    username     TEXT    NOT NULL,
    global_score INTEGER NOT NULL DEFAULT 0 CHECK (global_score >= 0),
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_users_score ON users (global_score DESC);

CREATE TABLE IF NOT EXISTS listings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id   TEXT    NOT NULL UNIQUE,
    city          TEXT    NOT NULL,
    country       TEXT    NOT NULL,
    neighbourhood TEXT,
    latitude      REAL             CHECK (latitude IS NULL OR (latitude >= -90 AND latitude <= 90)),
    longitude     REAL             CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180)),
    name          TEXT    NOT NULL,
    property_type TEXT    NOT NULL,
    room_type     TEXT    NOT NULL,
    accommodates  INTEGER NOT NULL CHECK (accommodates >= 1),
    bedrooms      INTEGER          CHECK (bedrooms >= 0),
    beds          INTEGER          CHECK (beds >= 0),
    bathrooms     REAL             CHECK (bathrooms >= 0),
    rating        REAL             CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5)),
    reviews_count INTEGER NOT NULL DEFAULT 0 CHECK (reviews_count >= 0),
    price         REAL    NOT NULL CHECK (price > 0)
);

CREATE INDEX IF NOT EXISTS idx_listings_city ON listings (city);

CREATE TABLE IF NOT EXISTS photos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id    INTEGER NOT NULL REFERENCES listings (id) ON DELETE CASCADE,
    image_url     TEXT    NOT NULL,
    display_order INTEGER NOT NULL CHECK (display_order >= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_photos_listing_order ON photos (listing_id, display_order);
"""
