from aiogram.fsm.state import State, StatesGroup


class ProductSearch(StatesGroup):
    waiting_for_query = State()


class MiniPrice(StatesGroup):
    """FSM-состояния для мини-прайса."""
    waiting_for_query = State()

class SearchModeStates(StatesGroup):
    waiting_supplier_site_query = State()
    waiting_global_search_query = State()


class KnowledgeUploadState(StatesGroup):
    waiting_for_category = State()
    waiting_for_file = State()
