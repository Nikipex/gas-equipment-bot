from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from app.bot.keyboards.main_menu import MenuButtons, get_main_menu_keyboard
from app.bot.states.search_states import ProductSearch
from app.repositories.product_repository import ProductRepository
from app.services.product_service import ProductService
from app.services.postgres_catalog_service import PostgresCatalogService
from app.services.cache_service import cache_service

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


def _search_cache_key(query: str) -> str:
    normalized = " ".join(query.lower().strip().split())
    return f"catalog_search:v1:{normalized}"


def _cache_payload(formatted: str, results_count: int, query_type: str) -> dict:
    return {
        "formatted": formatted,
        "results_count": results_count,
        "query_type": query_type,
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


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

    result_source = "postgres"

    try:
        postgres_catalog = _get_postgres_catalog_service()

        queries = [
            line.strip(" •-—\t")
            for line in query.splitlines()
            if line.strip(" •-—\t")
        ]

        if len(queries) > 1:
            blocks = ["🔎 <b>Поиск по списку позиций</b>"]
            total_count = 0

            for idx, item_query in enumerate(queries[:20], start=1):
                postgres_results = postgres_catalog.search(item_query, limit=3)
                total_count += len(postgres_results)

                blocks.append(f"\n<b>{idx}. {item_query}</b>")
                if postgres_results:
                    blocks.append(postgres_catalog.format_results(postgres_results, item_query))
                else:
                    blocks.append("Ничего не найдено.")

            if len(queries) > 20:
                blocks.append(f"\n⚠️ Обработал первые 20 строк из {len(queries)}.")

            formatted = "\n".join(blocks)
            results_count = total_count

            cache_service.set_json(
                _search_cache_key(query),
                _cache_payload(formatted, results_count, "multi"),
            )
        else:
            postgres_results = postgres_catalog.search(query, limit=10)
            formatted = postgres_catalog.format_results(postgres_results, query)
            results_count = len(postgres_results)

            cache_service.set_json(
                _search_cache_key(query),
                _cache_payload(formatted, results_count, "single"),
            )

    except Exception as e:
        logger.error(f"PostgreSQL catalog search failed: {type(e).__name__}: {e}")

        cached = cache_service.get_json(_search_cache_key(query))
        if cached:
            formatted = (
                "⚠️ <b>Живая база 1С/PostgreSQL временно недоступна.</b>\n"
                "Показываю последний сохранённый результат из Redis-кэша.\n"
                f"Кэш от: {cached.get('cached_at', 'неизвестно')}\n\n"
                f"{cached.get('formatted', '')}"
            )
            results_count = int(cached.get("results_count", 0))
            result_source = "redis"
        else:
            formatted = (
                "❌ Живая база 1С/PostgreSQL временно недоступна.\n"
                "Кэша по этому запросу пока нет. Попробуйте позже."
            )
            results_count = 0
            result_source = "error"

    await message.answer(
        formatted,
        reply_markup=get_main_menu_keyboard(),
    )

    await state.clear()
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(
        f"Пользователь {user_id} завершил поиск: "
        f"'{query}' -> {results_count} результатов "
        f"(source={result_source})"
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