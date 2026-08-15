from __future__ import annotations

from dataclasses import dataclass

from bot.db.models import DbType

CARD_MARKERS = ("Тип:", "Хост:", "БД:", "Пользователь:")
_FIELD_PREFIXES = (*CARD_MARKERS, "Пароль:", "Активно:")

DEFAULT_PORTS = {
    DbType.POSTGRES: 5432,
    DbType.CLICKHOUSE: 8123,
}


class ConnectionCardParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedConnectionCard:
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str


def looks_like_connection_card(text: str) -> bool:
    return all(marker in text for marker in CARD_MARKERS)


def parse_connection_card(text: str) -> ParsedConnectionCard:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    name = ""

    for line in lines:
        matched_prefix = next(
            (prefix for prefix in _FIELD_PREFIXES if line.startswith(prefix)),
            None,
        )
        if matched_prefix is None:
            if not name:
                name = line
            continue
        if matched_prefix in ("Пароль:", "Активно:"):
            continue
        fields[matched_prefix] = line[len(matched_prefix) :].strip()

    if not name or len(name) > 128:
        raise ConnectionCardParseError("Название обязательно, до 128 символов.")

    db_type_raw = fields.get("Тип:", "").lower()
    try:
        db_type = DbType(db_type_raw)
    except ValueError as exc:
        raise ConnectionCardParseError(
            "Тип БД должен быть postgres или clickhouse."
        ) from exc

    host_raw = fields.get("Хост:", "")
    if not host_raw:
        raise ConnectionCardParseError("Не указан хост.")
    host, port = _split_host_port(host_raw, db_type)

    database = fields.get("БД:", "")
    if not database:
        raise ConnectionCardParseError("Не указано имя БД.")

    username = fields.get("Пользователь:", "")
    if not username:
        raise ConnectionCardParseError("Не указан пользователь.")

    return ParsedConnectionCard(
        name=name,
        db_type=db_type.value,
        host=host,
        port=port,
        database=database,
        username=username,
    )


def _split_host_port(host_raw: str, db_type: DbType) -> tuple[str, int]:
    if ":" not in host_raw:
        return host_raw, DEFAULT_PORTS[db_type]

    host, port_s = host_raw.rsplit(":", 1)
    host = host.strip()
    port_s = port_s.strip()
    if not host:
        raise ConnectionCardParseError("Host не может быть пустым.")
    if not port_s.isdigit():
        raise ConnectionCardParseError("Порт должен быть числом.")
    port = int(port_s)
    if not 1 <= port <= 65535:
        raise ConnectionCardParseError("Порт вне диапазона 1–65535.")
    return host, port
