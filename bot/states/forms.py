from aiogram.fsm.state import State, StatesGroup


class ConnectionForm(StatesGroup):
    db_type = State()
    name = State()
    host = State()
    port = State()
    database = State()
    username = State()
    password = State()
    edit_field_value = State()


class QueryForm(StatesGroup):
    waiting_sql = State()
    editing_sql = State()


class FavoriteForm(StatesGroup):
    waiting_title = State()
