from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DbType(StrEnum):
    POSTGRES = "postgres"
    CLICKHOUSE = "clickhouse"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    active_connection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("db_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    active_connection: Mapped[Optional["DbConnection"]] = relationship(
        "DbConnection",
        foreign_keys=[active_connection_id],
        post_update=True,
    )
    connections: Mapped[list["DbConnection"]] = relationship(
        "DbConnection",
        back_populates="owner",
        foreign_keys="DbConnection.user_id",
        cascade="all, delete-orphan",
    )
    favorites: Mapped[list["FavoriteQuery"]] = relationship(
        "FavoriteQuery",
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class DbConnection(Base):
    __tablename__ = "db_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_connection_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    db_type: Mapped[str] = mapped_column(String(32), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped["User"] = relationship(
        "User",
        back_populates="connections",
        foreign_keys=[user_id],
    )
    favorites: Mapped[list["FavoriteQuery"]] = relationship(
        "FavoriteQuery",
        back_populates="connection",
        cascade="all, delete-orphan",
    )


class FavoriteQuery(Base):
    __tablename__ = "favorite_queries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "connection_id",
            "title",
            name="uq_favorite_user_connection_title",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("db_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    owner: Mapped["User"] = relationship("User", back_populates="favorites")
    connection: Mapped["DbConnection"] = relationship(
        "DbConnection",
        back_populates="favorites",
    )
