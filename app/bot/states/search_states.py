from aiogram.fsm.state import State, StatesGroup


class ProductSearch(StatesGroup):
    waiting_for_query = State()


class MiniPrice(StatesGroup):
    """FSM-состояния для мини-прайса."""
    waiting_for_query = State()