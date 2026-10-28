"""CRUD nad tabulkou photos."""

import aiosqlite

from src.models import Photo, PhotoCreate


async def create_photo(conn: aiosqlite.Connection, data: PhotoCreate) -> Photo:
    cursor = await conn.execute(
        "INSERT INTO photos (listing_id, image_url, display_order) VALUES (?, ?, ?)",
        (data.listing_id, data.image_url, data.display_order),
    )
    await conn.commit()
    return await get_photo(conn, cursor.lastrowid)


async def get_photo(conn: aiosqlite.Connection, photo_id: int) -> Photo | None:
    cursor = await conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,))
    row = await cursor.fetchone()
    return Photo(**dict(row)) if row else None


async def list_photos(conn: aiosqlite.Connection, listing_id: int) -> list[Photo]:
    cursor = await conn.execute(
        "SELECT * FROM photos WHERE listing_id = ? ORDER BY display_order", (listing_id,)
    )
    rows = await cursor.fetchall()
    return [Photo(**dict(row)) for row in rows]


async def update_photo(conn: aiosqlite.Connection, photo: Photo) -> Photo | None:
    await conn.execute(
        "UPDATE photos SET listing_id = ?, image_url = ?, display_order = ? WHERE id = ?",
        (photo.listing_id, photo.image_url, photo.display_order, photo.id),
    )
    await conn.commit()
    return await get_photo(conn, photo.id)


async def delete_photo(conn: aiosqlite.Connection, photo_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    await conn.commit()
    return cursor.rowcount > 0
