"""CRUD nad tabulkou listings."""

import aiosqlite

from src.models import Listing, ListingCreate


async def create_listing(conn: aiosqlite.Connection, data: ListingCreate) -> Listing:
    cursor = await conn.execute(
        "INSERT INTO listings (external_id, city, name, property_type, accommodates,"
        " bedrooms, rating, reviews_count, price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data.external_id,
            data.city,
            data.name,
            data.property_type,
            data.accommodates,
            data.bedrooms,
            data.rating,
            data.reviews_count,
            data.price,
        ),
    )
    await conn.commit()
    return await get_listing(conn, cursor.lastrowid)


async def get_listing(conn: aiosqlite.Connection, listing_id: int) -> Listing | None:
    cursor = await conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
    row = await cursor.fetchone()
    return Listing(**dict(row)) if row else None


async def list_listings(conn: aiosqlite.Connection, limit: int = 100, offset: int = 0) -> list[Listing]:
    cursor = await conn.execute(
        "SELECT * FROM listings ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
    )
    rows = await cursor.fetchall()
    return [Listing(**dict(row)) for row in rows]


async def update_listing(conn: aiosqlite.Connection, listing: Listing) -> Listing | None:
    await conn.execute(
        "UPDATE listings SET external_id = ?, city = ?, name = ?, property_type = ?,"
        " accommodates = ?, bedrooms = ?, rating = ?, reviews_count = ?, price = ? WHERE id = ?",
        (
            listing.external_id,
            listing.city,
            listing.name,
            listing.property_type,
            listing.accommodates,
            listing.bedrooms,
            listing.rating,
            listing.reviews_count,
            listing.price,
            listing.id,
        ),
    )
    await conn.commit()
    return await get_listing(conn, listing.id)


async def delete_listing(conn: aiosqlite.Connection, listing_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    await conn.commit()
    return cursor.rowcount > 0
