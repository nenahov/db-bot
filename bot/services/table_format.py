from __future__ import annotations

import html
from datetime import datetime

from aiogram.types import InputRichMessage

MAX_CELL_LEN = 64


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
    content = (
        f"<h3>Результат ({total_rows} строк, {elapsed_ms} мс)</h3>"
        f"<p>Подключение: {html.escape(connection_name)}</p>"
        f"<p>Выполнено: {executed_at}</p>"
        f"{truncated_note}"
        f"<table bordered><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )
    return InputRichMessage(html=content)
