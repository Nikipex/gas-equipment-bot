"""Supplier Excel file upload handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import main_menu_kb
from app.services.supplier_file_service import SupplierFileService
from app.services.supplier_parser_service import SupplierParserService
from app.services.supplier_cache_service import SupplierCacheService

router = Router()
_supplier_file_service = SupplierFileService()
_supplier_parser_service = SupplierParserService()
_supplier_cache_service = SupplierCacheService()


@router.message(F.document)
async def process_supplier_file(message: Message) -> None:
    document = message.document
    if document is None:
        return

    filename = document.file_name or "supplier_price.xlsx"

    try:
        save_path = _supplier_file_service.build_save_path(filename)
    except ValueError:
        await message.answer(
            "❌ Поддерживаются только файлы: .xlsx, .xls, .csv",
            reply_markup=main_menu_kb,
        )
        return

    bot = message.bot
    file = await bot.get_file(document.file_id)

    if file.file_path is None:
        await message.answer(
            "❌ Не смог получить путь к файлу Telegram.",
            reply_markup=main_menu_kb,
        )
        return

    await bot.download_file(file.file_path, destination=save_path)

    await message.answer(
        "✅ Файл поставщика сохранён.\n\n"
        f"📄 Имя: <b>{filename}</b>\n"
        f"📁 Путь: <code>{save_path}</code>",
        reply_markup=main_menu_kb,
    )

    try:
        result = _supplier_parser_service.parse_file(save_path, limit=5000)
        saved_count = _supplier_cache_service.save_parse_result(result)
        preview_text = _supplier_parser_service.build_preview_text(result, limit=10)
        preview_text += f"\n\n💾 В кэш поставщиков записано: <b>{saved_count}</b>"
        await message.answer(preview_text, reply_markup=main_menu_kb)
    except Exception as exc:
        await message.answer(
            "⚠️ Файл сохранён, но распарсить пока не получилось.\n\n"
            f"Ошибка: <code>{type(exc).__name__}: {exc}</code>",
            reply_markup=main_menu_kb,
        )
