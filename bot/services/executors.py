from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import asyncpg
import clickhouse_connect

from bot.db.models import DbConnection, DbType
from bot.services.crypto import PasswordCipher


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    rowcount: int | None = None
    elapsed_ms: int = 0
    has_dataset: bool = False


def _stringify_rows(rows: list[tuple[Any, ...]] | list[list[Any]]) -> list[list[str]]:
    result: list[list[str]] = []
    for row in rows:
        result.append(["" if value is None else str(value) for value in row])
    return result


async def test_connection(
    conn: DbConnection,
    cipher: PasswordCipher,
    timeout_sec: int,
) -> None:
    await execute_sql(conn, cipher, "SELECT 1", timeout_sec=timeout_sec, max_rows=1)


async def execute_sql(
    conn: DbConnection,
    cipher: PasswordCipher,
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> QueryResult:
    password = cipher.decrypt(conn.password_encrypted)
    if conn.db_type == DbType.POSTGRES:
        return await _execute_postgres(
            conn,
            password,
            sql,
            timeout_sec=timeout_sec,
            max_rows=max_rows,
        )
    if conn.db_type == DbType.CLICKHOUSE:
        return await _execute_clickhouse(
            conn,
            password,
            sql,
            timeout_sec=timeout_sec,
            max_rows=max_rows,
        )
    raise ValueError(f"Неизвестный тип БД: {conn.db_type}")


def _postgres_server_settings(conn: DbConnection) -> dict[str, str] | None:
    if conn.read_only:
        return {"default_transaction_read_only": "on"}
    return None


def _clickhouse_settings(conn: DbConnection) -> dict[str, int]:
    if conn.read_only:
        return {"readonly": 1}
    return {}


async def _execute_postgres(
    conn: DbConnection,
    password: str,
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> QueryResult:
    started = time.perf_counter()
    connection = await asyncpg.connect(
        host=conn.host,
        port=conn.port,
        user=conn.username,
        password=password,
        database=conn.database,
        timeout=timeout_sec,
        server_settings=_postgres_server_settings(conn),
    )
    try:
        if conn.read_only:
            await connection.execute("SET default_transaction_read_only TO on")
        statement = await connection.prepare(sql)
        columns = [attr.name for attr in statement.get_attributes()]
        if columns:
            records = await asyncio.wait_for(
                statement.fetch(),
                timeout=timeout_sec,
            )
            total = len(records)
            limited = records[:max_rows]
            rows = _stringify_rows([tuple(record) for record in limited])
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return QueryResult(
                columns=columns,
                rows=rows,
                rowcount=total,
                elapsed_ms=elapsed_ms,
                has_dataset=True,
            )

        status = await asyncio.wait_for(
            connection.execute(sql),
            timeout=timeout_sec,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        affected = _parse_asyncpg_status(status)
        return QueryResult(
            columns=[],
            rows=[],
            rowcount=affected,
            elapsed_ms=elapsed_ms,
            has_dataset=False,
        )
    finally:
        await connection.close()


def _parse_asyncpg_status(status: str) -> int | None:
    parts = status.split()
    for part in reversed(parts):
        if part.isdigit():
            return int(part)
    return None


async def _execute_clickhouse(
    conn: DbConnection,
    password: str,
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> QueryResult:
    def _run() -> QueryResult:
        started = time.perf_counter()
        client = clickhouse_connect.get_client(
            host=conn.host,
            port=conn.port,
            username=conn.username,
            password=password,
            database=conn.database,
            connect_timeout=timeout_sec,
            send_receive_timeout=timeout_sec,
            settings=_clickhouse_settings(conn),
        )
        try:
            result = client.query(sql)
            columns = list(result.column_names)
            all_rows = result.result_rows
            total = len(all_rows)
            rows = _stringify_rows(all_rows[:max_rows])
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if columns:
                return QueryResult(
                    columns=columns,
                    rows=rows,
                    rowcount=total,
                    elapsed_ms=elapsed_ms,
                    has_dataset=True,
                )
            return QueryResult(
                columns=[],
                rows=[],
                rowcount=getattr(result, "row_count", None),
                elapsed_ms=elapsed_ms,
                has_dataset=False,
            )
        finally:
            client.close()

    return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_sec + 5)
