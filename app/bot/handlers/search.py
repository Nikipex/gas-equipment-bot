from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from app.bot.keyboards.main_menu import MenuButtons, get_main_menu_keyboard
from app.bot.states.search_states import ProductSearch
from app.repositories.product_repository import ProductRepository
from app.services.product_service import ProductService
from app.services.postgres_catalog_service import PostgresCatalogService

_product_repo = ProductRepository()
_product_service = ProductService(_product_repo)

_postgres_catalog_service: PostgresCatalogService | None = None

def _get_postgres_catalog_service() -> PostgresCatalogService:
    """Lazy PostgreSQL catalog service init.

    Keeps bot startup safe even if procurement PostgreSQL is temporarily unavailable.
    """
    global _postgres_catalog_service
    if _postgres_catalog_service is None:
        _postgres_catalog_service = PostgresCatalogService()
    return _postgres_catalog_service

router = Router()


@router.message(F.text == MenuButtons.SEARCH)
async def start_search(message: Message, state: FSMContext):
    """Старт поиска по кнопке reply keyboard."""
    await state.set_state(ProductSearch.waiting_for_query)

    await message.answer(
        "🔍 Введите название товара для поиска:\n"
        "<i>Например: котел, BAXI, радиатор 500</i>\n\n"
        "Для отмены введите /cancel или 'отмена'.",
        reply_markup=get_main_menu_keyboard(),
    )
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(f"Пользователь {user_id} начал поиск товаров")


@router.message(ProductSearch.waiting_for_query, F.text)
async def process_search_query(message: Message, state: FSMContext):
    query = message.text.strip()

    if query.lower() in {"/cancel", "отмена", "назад"}:
        await cancel_search(message, state)
        return

    used_postgres = True

    try:
        postgres_catalog = _get_postgres_catalog_service()
        postgres_results = postgres_catalog.search(query, limit=10)
        formatted = postgres_catalog.format_results(postgres_results, query)
        results_count = len(postgres_results)
    except Exception as e:
        logger.error(f"PostgreSQL catalog search failed: {type(e).__name__}: {e}")
        formatted = "❌ Ошибка поиска по живой базе 1С/PostgreSQL. Проверь логи бота."
        results_count = 0
        used_postgres = True

    await message.answer(
        formatted,
        reply_markup=get_main_menu_keyboard(),
    )

    await state.clear()
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(
        f"Пользователь {user_id} завершил поиск: "
        f"'{query}' -> {results_count} результатов "
        f"(source={'postgres' if used_postgres else 'local'})"
    )


async def cancel_search(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Поиск отменён",
        reply_markup=get_main_menu_keyboard(),
    )
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(f"Пользователь {user_id} отменил поиск")


@router.message(F.text == "/cancel")
async def cancel_search_global(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await cancel_search(message, state)