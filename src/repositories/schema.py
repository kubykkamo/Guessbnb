"""DDL podle ERD (docs/ERD.drawio). Spouští se v db.connect()."""

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
    name          TEXT    NOT NULL,
    property_type TEXT    NOT NULL,
    accommodates  INTEGER NOT NULL CHECK (accommodates >= 1),
    bedrooms      INTEGER          CHECK (bedrooms >= 0),
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
