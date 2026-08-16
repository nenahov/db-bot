from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import DbConnection, FavoriteQuery, User


async def get_or_create_user(session: AsyncSession, telegram_id: int) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def list_connections(session: AsyncSession, user_id: int) -> list[DbConnection]:
    result = await session.scalars(
        select(DbConnection)
        .where(DbConnection.user_id == user_id)
        .order_by(DbConnection.name)
    )
    return list(result)


async def get_connection(
    session: AsyncSession,
    user_id: int,
    connection_id: int,
) -> DbConnection | None:
    result = await session.scalar(
        select(DbConnection).where(
            DbConnection.id == connection_id,
            DbConnection.user_id == user_id,
        )
    )
    return result


async def get_connection_by_name(
    session: AsyncSession,
    user_id: int,
    name: str,
) -> DbConnection | None:
    result = await session.scalar(
        select(DbConnection).where(
            DbConnection.user_id == user_id,
            DbConnection.name == name,
        )
    )
    return result


async def create_connection(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password_encrypted: str,
    read_only: bool = True,
) -> DbConnection:
    conn = DbConnection(
        user_id=user_id,
        name=name,
        db_type=db_type,
        host=host,
        port=port,
        database=database,
        username=username,
        password_encrypted=password_encrypted,
        read_only=read_only,
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return conn


async def update_connection(
    session: AsyncSession,
    conn: DbConnection,
    **fields: object,
) -> DbConnection:
    for key, value in fields.items():
        if value is not None:
            setattr(conn, key, value)
    await session.commit()
    await session.refresh(conn)
    return conn


async def delete_connection(session: AsyncSession, conn: DbConnection) -> None:
    user = await session.get(User, conn.user_id)
    if user and user.active_connection_id == conn.id:
        user.active_connection_id = None
    await session.delete(conn)
    await session.commit()


async def set_active_connection(
    session: AsyncSession,
    user_id: int,
    connection_id: int | None,
) -> User:
    user = await get_or_create_user(session, user_id)
    user.active_connection_id = connection_id
    await session.commit()
    await session.refresh(user)
    return user


async def get_active_connection(
    session: AsyncSession,
    user_id: int,
) -> DbConnection | None:
    user = await session.scalar(
        select(User)
        .where(User.telegram_id == user_id)
        .options(selectinload(User.active_connection))
    )
    if user is None or user.active_connection_id is None:
        return None
    return user.active_connection


async def list_favorites_for_connection(
    session: AsyncSession,
    user_id: int,
    connection_id: int,
) -> list[FavoriteQuery]:
    result = await session.scalars(
        select(FavoriteQuery)
        .where(
            FavoriteQuery.user_id == user_id,
            FavoriteQuery.connection_id == connection_id,
        )
        .order_by(FavoriteQuery.title)
    )
    return list(result)


async def list_all_favorites(
    session: AsyncSession,
    user_id: int,
) -> list[FavoriteQuery]:
    result = await session.scalars(
        select(FavoriteQuery)
        .where(FavoriteQuery.user_id == user_id)
        .options(selectinload(FavoriteQuery.connection))
        .order_by(FavoriteQuery.title)
    )
    return list(result)


async def get_favorite(
    session: AsyncSession,
    user_id: int,
    favorite_id: int,
) -> FavoriteQuery | None:
    result = await session.scalar(
        select(FavoriteQuery)
        .where(
            FavoriteQuery.id == favorite_id,
            FavoriteQuery.user_id == user_id,
        )
        .options(selectinload(FavoriteQuery.connection))
    )
    return result


async def create_favorite(
    session: AsyncSession,
    *,
    user_id: int,
    connection_id: int,
    title: str,
    sql_text: str,
) -> FavoriteQuery:
    fav = FavoriteQuery(
        user_id=user_id,
        connection_id=connection_id,
        title=title,
        sql_text=sql_text,
    )
    session.add(fav)
    await session.commit()
    await session.refresh(fav)
    return fav


async def delete_favorite(session: AsyncSession, fav: FavoriteQuery) -> None:
    await session.delete(fav)
    await session.commit()


async def get_favorite_by_title(
    session: AsyncSession,
    user_id: int,
    connection_id: int,
    title: str,
) -> FavoriteQuery | None:
    return await session.scalar(
        select(FavoriteQuery).where(
            FavoriteQuery.user_id == user_id,
            FavoriteQuery.connection_id == connection_id,
            FavoriteQuery.title == title,
        )
    )


async def update_favorite_sql(
    session: AsyncSession,
    fav: FavoriteQuery,
    sql_text: str,
) -> FavoriteQuery:
    fav.sql_text = sql_text
    await session.commit()
    await session.refresh(fav)
    return fav
