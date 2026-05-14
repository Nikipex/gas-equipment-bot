from aiogram.fsm.state import State, StatesGroup


class ProductSearch(StatesGroup):
    """FSM-состояния для поиска товаров."""
    waiting_for_query = State()