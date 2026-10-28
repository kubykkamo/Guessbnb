"""Otevření spojení do SQLite. Žádný wrapper kolem aiosqlite - repositories
dostanou obyčejné `aiosqlite.Connection` a volají na něm execute/commit."""

from pathlib import Path

import aiosqlite

from src.repositories.schema import SCHEMA

DB_PATH = "data/guessbnb.db"


async def connect(path: str | Path = DB_PATH) -> aiosqlite.Connection:
    """Otevře spojení, zapne WAL a cizí klíče, vytvoří tabulky podle schema.py."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn
