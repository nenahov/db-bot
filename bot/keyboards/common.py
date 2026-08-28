from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MENU_TEXT_CONNECTIONS = "🔌 Подключения"
MENU_TEXT_FAVORITES = "⭐ Избранное"
MENU_TEXT_QUERY = "📝 Запрос"

MENU_TEXTS = frozenset(
    {
        MENU_TEXT_CONNECTIONS,
        MENU_TEXT_QUERY,
        MENU_TEXT_FAVORITES,
    }
)


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_TEXT_CONNECTIONS, callback_data="menu:connections")
    builder.button(text=MENU_TEXT_FAVORITES, callback_data="menu:favorites")
    builder.adjust(1)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="cancel")
    return builder.as_markup()


def subscribe_gate_kb(subscribe_buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for text, url in subscribe_buttons:
        builder.button(text=text, url=url)
    builder.button(text="Проверить подписку", callback_data="auth:check")
    builder.adjust(1)
    return builder.as_markup()


def connection_edit_fields_kb(connection_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, title in (
        ("host", "IP / host"),
        ("database", "Имя БД"),
        ("username", "Пользователь"),
        ("password", "Пароль"),
        ("port", "Порт"),
        ("name", "Название"),
        ("read_only", "Режим SQL"),
    ):
        builder.button(
            text=title,
            callback_data=f"conn:editfield:{connection_id}:{field}",
        )
    builder.button(text="⬅️ Назад", callback_data=f"conn:view:{connection_id}")
    builder.adjust(2)
    return builder.as_markup()


def confirm_delete_kb(connection_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Да, удалить",
        callback_data=f"conn:delete_confirm:{connection_id}",
        style="danger",
    )
    builder.button(text="Отмена", callback_data=f"conn:view:{connection_id}")
    builder.adjust(1)
    return builder.as_markup()


def db_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="PostgreSQL", callback_data="conn:type:postgres")
    builder.button(text="ClickHouse", callback_data="conn:type:clickhouse")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def query_result_kb(run_id: str | None, *, can_favorite: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if run_id:
        builder.button(text="📥 Скачать CSV", callback_data=f"query:csv:{run_id}")
    if can_favorite:
        builder.button(text="⭐ В избранное", callback_data="query:fav")
    builder.adjust(1)
    return builder.as_markup()


def confirm_replace_favorite_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, заменить", callback_data="query:fav:replace")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def skip_default_port_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Оставить по умолчанию", callback_data="conn:port:default")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def read_only_choice_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔒 Только чтение", callback_data="conn:readonly:1")
    builder.button(text="✏️ Чтение и запись", callback_data="conn:readonly:0")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def read_only_edit_kb(connection_id: int, read_only: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    ro_mark = " ✓" if read_only else ""
    rw_mark = " ✓" if not read_only else ""
    builder.button(
        text=f"🔒 Только чтение{ro_mark}",
        callback_data=f"conn:setreadonly:{connection_id}:1",
    )
    builder.button(
        text=f"✏️ Чтение и запись{rw_mark}",
        callback_data=f"conn:setreadonly:{connection_id}:0",
    )
    builder.button(text="⬅️ Назад", callback_data=f"conn:edit:{connection_id}")
    builder.adjust(1)
    return builder.as_markup()
