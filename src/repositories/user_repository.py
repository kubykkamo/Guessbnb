"""CRUD nad tabulkou users. Každý zápis skončí commit(), nic víc."""

import aiosqlite

from src.models import User, UserCreate


async def create_user(conn: aiosqlite.Connection, data: UserCreate) -> User:
    cursor = await conn.execute(
        "INSERT INTO users (auth0_id, username) VALUES (?, ?)",
        (data.auth0_id, data.username),
    )
    await conn.commit()
    return await get_user(conn, cursor.lastrowid)


async def get_user(conn: aiosqlite.Connection, user_id: int) -> User | None:
    cursor = await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    return User(**dict(row)) if row else None


async def list_users(conn: aiosqlite.Connection, limit: int = 100, offset: int = 0) -> list[User]:
    cursor = await conn.execute(
        "SELECT * FROM users ORDER BY global_score DESC LIMIT ? OFFSET ?", (limit, offset)
    )
    rows = await cursor.fetchall()
    return [User(**dict(row)) for row in rows]


async def update_user(conn: aiosqlite.Connection, user: User) -> User | None:
    await conn.execute(
        "UPDATE users SET auth0_id = ?, username = ?, global_score = ? WHERE id = ?",
        (user.auth0_id, user.username, user.global_score, user.id),
    )
    await conn.commit()
    return await get_user(conn, user.id)


async def delete_user(conn: aiosqlite.Connection, user_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await conn.commit()
    return cursor.rowcount > 0
