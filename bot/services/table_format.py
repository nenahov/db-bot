from __future__ import annotations

import html
from datetime import datetime

from aiogram.types import InputRichMessage

from bot.db.models import DbConnection

MAX_CELL_LEN = 64

_DB_TYPE_LABELS = {
    "postgres": "PostgreSQL",
    "clickhouse": "ClickHouse",
}


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    if len(text) > MAX_CELL_LEN:
        text = text[: MAX_CELL_LEN - 1] + "…"
    return html.escape(text)


def build_result_rich_message(
    columns: list[str],
    rows: list[list[object]],
    *,
    connection_name: str,
    preview_rows: int,
    total_rows: int,
    elapsed_ms: int,
    run_id: str | None = None,
) -> InputRichMessage:
    shown = rows[:preview_rows]
    header = "".join(f"<th>{_cell(col)}</th>" for col in columns)
    body_rows = []
    for row in shown:
        cells = "".join(f"<td>{_cell(value)}</td>" for value in row)
        body_rows.append(f"<tr>{cells}</tr>")

    truncated_note = ""
    if total_rows > preview_rows:
        truncated_note = (
            f"<p>Показаны первые {preview_rows} из {total_rows} строк. "
            "Полный результат — кнопкой «Скачать CSV».</p>"
        )
    elif total_rows == 0:
        truncated_note = "<p>Запрос выполнен, строк нет.</p>"

    executed_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S")
    refresh_button = ""
    if run_id:
        refresh_button = (
            f' <tg-button type="callback_data" '
            f'data="query:refresh:{html.escape(run_id, quote=True)}">'
            "🔄 Обновить</tg-button>"
        )
    content = (
        f"<h3>Результат ({total_rows} строк, {elapsed_ms} мс)</h3>"
        f"<p>Подключение: {html.escape(connection_name)}</p>"
        f"<p>Выполнено: {executed_at}{refresh_button}</p>"
        f"{truncated_note}"
        f"<table bordered><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )
    return InputRichMessage(html=content)


def build_connections_list_rich_message(
    connections: list[DbConnection],
    *,
    active_id: int | None = None,
    notice: str | None = None,
) -> InputRichMessage:
    notice_html = f"<p>{html.escape(notice)}</p>" if notice else ""
    add_button = (
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" data="conn:add">➕ Добавить</tg-button>'
        "</tg-button-row>"
    )
    if not connections:
        content = (
            f"<h3>Подключения</h3>"
            f"{notice_html}"
            f"<p>Подключений пока нет. Добавьте первое.</p>"
            f"{add_button}"
        )
        return InputRichMessage(html=content)

    header = "".join(
        f"<th>{html.escape(col)}</th>" for col in ("Название", "Тип", "Хост", "БД")
    )
    body_rows: list[str] = []
    for conn in connections:
        name = html.escape(conn.name)
        if conn.read_only:
            name = f"🔒 {name}"
        if conn.id == active_id:
            name = f"{name} ✓"
        name_button = (
            f'<tg-button type="callback_data" data="conn:view:{conn.id}">{name}</tg-button>'
        )
        type_label = html.escape(_DB_TYPE_LABELS.get(conn.db_type, conn.db_type))
        host = html.escape(f"{conn.host}:{conn.port}")
        database = html.escape(conn.database)
        body_rows.append(
            "<tr>"
            f"<td>{name_button}</td>"
            f"<td>{type_label}</td>"
            f"<td>{host}</td>"
            f"<td>{database}</td>"
            "</tr>"
        )

    content = (
        f"<h3>Подключения</h3>"
        f"{notice_html}"
        f"<table bordered><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        f"{add_button}"
    )
    return InputRichMessage(html=content)


def build_connection_card_rich_message(
    conn: DbConnection,
    *,
    is_active: bool,
    notice: str | None = None,
) -> InputRichMessage:
    notice_html = ""
    if notice:
        notice_html = "".join(
            f"<p>{html.escape(part)}</p>" for part in notice.split("\n") if part
        )
    active = "да" if is_active else "нет"
    buttons = ""
    if not is_active:
        buttons += (
            '<tg-button-row align="center">'
            f'<tg-button type="callback_data" data="conn:activate:{conn.id}">'
            "Подключиться</tg-button>"
            "</tg-button-row>"
        )
    buttons += (
        '<tg-button-row align="center">'
        f'<tg-button type="callback_data" data="conn:edit:{conn.id}">Изменить</tg-button>'
        f'<tg-button type="callback_data" data="conn:delete:{conn.id}">Удалить</tg-button>'
        "</tg-button-row>"
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" data="conn:list">⬅️ Назад</tg-button>'
        "</tg-button-row>"
    )
    content = (
        f"{notice_html}"
        f"<h3>{html.escape(conn.name)}</h3>"
        f"<p>Тип: <code>{html.escape(conn.db_type)}</code></p>"
        f"<p>Хост: <code>{html.escape(conn.host)}:{conn.port}</code></p>"
        f"<p>БД: <code>{html.escape(conn.database)}</code></p>"
        f"<p>Пользователь: <code>{html.escape(conn.username)}</code></p>"
        f"<p>Пароль: <code>••••</code></p>"
        f"<p>Режим SQL: {html.escape(conn.sql_mode_label)}</p>"
        f"<p>Активно: {active}</p>"
        f"{buttons}"
    )
    return InputRichMessage(html=content)
