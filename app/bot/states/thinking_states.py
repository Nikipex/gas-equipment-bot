from aiogram.fsm.state import State, StatesGroup


class ThinkingState(StatesGroup):
    waiting_for_question = State()
