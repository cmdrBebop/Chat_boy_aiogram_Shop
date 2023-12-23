from aiogram.dispatcher.filters.state import StatesGroup, State


class CryproBot(StatesGroup):
    sum = State()
    currency = State()
