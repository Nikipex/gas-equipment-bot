from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from loguru import logger

from app.bot.keyboards.main_menu import MenuButtons, get_main_menu_keyboard
from app.bot.states.search_states import KnowledgeUploadState
from app.services.knowledge_summary_service import knowledge_summary_service

router = Router()

ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
ALLOWED_SUFFIXES = {".pdf", ".md", ".txt"}

CATEGORY_DIRS = {
    "котлы": "data/knowledge_base/passport_intelligence/boilers",
    "радиаторы": "data/knowledge_base/passport_intelligence/radiators",
    "бойлеры": "data/knowledge_base/passport_intelligence/water_heaters",
    "насосы": "data/knowledge_base/passport_intelligence/pumps",
    "стабилизаторы": "data/knowledge_base/passport_intelligence/stabilizers",
    "газовые колонки": "data/knowledge_base/passport_intelligence/gas_columns",
    "коаксиалы": "data/knowledge_base/passport_intelligence/coaxials",
    "прочее": "data/knowledge_base/passport_intelligence/uploads",
}


def _category_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="котлы"), KeyboardButton(text="радиаторы")],
            [KeyboardButton(text="бойлеры"), KeyboardButton(text="насосы")],
            [KeyboardButton(text="стабилизаторы"), KeyboardButton(text="газовые колонки")],
            [KeyboardButton(text="коаксиалы"), KeyboardButton(text="прочее")],
            [KeyboardButton(text="отмена")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите категорию паспорта",
    )


def _is_admin(message: Message) -> bool:
    user_id = str(message.from_user.id) if message.from_user else ""
    return bool(ADMIN_CHAT_ID) and user_id == ADMIN_CHAT_ID


def _safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]", "_", name)
    return name[:180] or "knowledge_file"


@router.message(F.text == MenuButtons.KB_UPLOAD)
async def start_kb_upload(message: Message, state: FSMContext):
    if not _is_admin(message):
        await message.answer("⛔ Загрузка базы знаний доступна только администратору.")
        return

    await state.set_state(KnowledgeUploadState.waiting_for_category)
    await message.answer(
        "📚 <b>Загрузка паспорта / инструкции / заметки</b>\n\n"
        "Сначала выберите категорию файла.",
        reply_markup=_category_keyboard(),
    )


@router.message(KnowledgeUploadState.waiting_for_category, F.text)
async def choose_category(message: Message, state: FSMContext):
    category = message.text.lower().strip() if message.text else ""

    if category in {"/cancel", "отмена", "назад"}:
        await state.clear()
        await message.answer("❌ Загрузка базы знаний отменена.", reply_markup=get_main_menu_keyboard())
        return

    if category not in CATEGORY_DIRS:
        await message.answer("Выберите категорию кнопкой ниже.", reply_markup=_category_keyboard())
        return

    await state.update_data(category=category, target_dir=CATEGORY_DIRS[category])
    await state.set_state(KnowledgeUploadState.waiting_for_file)

    await message.answer(
        f"✅ Категория: <b>{category}</b>\n\n"
        "Теперь отправьте файл PDF, MD или TXT документом.\n"
        "Для отмены: /cancel или «отмена».",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(KnowledgeUploadState.waiting_for_file, F.text)
async def cancel_or_wait_file(message: Message, state: FSMContext):
    if message.text and message.text.lower().strip() in {"/cancel", "отмена", "назад"}:
        await state.clear()
        await message.answer("❌ Загрузка базы знаний отменена.", reply_markup=get_main_menu_keyboard())
        return

    await message.answer("Пришлите файл PDF, MD или TXT документом.")


@router.message(KnowledgeUploadState.waiting_for_file, F.document)
async def process_kb_file(message: Message, state: FSMContext):
    if not _is_admin(message):
        await message.answer("⛔ Загрузка базы знаний доступна только администратору.")
        await state.clear()
        return

    data = await state.get_data()
    category = data.get("category", "прочее")
    target_dir = Path(data.get("target_dir", CATEGORY_DIRS["прочее"]))

    document = message.document
    if document is None:
        await message.answer("Не вижу файл. Пришлите документ PDF, MD или TXT.")
        return

    original_name = document.file_name or "knowledge_file"
    suffix = Path(original_name).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        await message.answer("❌ Поддерживаются только PDF, MD или TXT.")
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(original_name)
    target_path = target_dir / safe_name

    if target_path.exists():
        stem = target_path.stem
        target_path = target_path.with_name(f"{stem}_{document.file_unique_id}{suffix}")

    await message.answer("📥 Загружаю файл...")

    try:
        tg_file = await message.bot.get_file(document.file_id)
        downloaded = await message.bot.download_file(tg_file.file_path)

        with target_path.open("wb") as f:
            shutil.copyfileobj(downloaded, f)

        await message.answer(
            "✅ Файл сохранён.\n"
            f"Категория: <b>{category}</b>\n"
            f"Путь: <code>{target_path}</code>\n\n"
            "🧠 Создаю краткую карточку по документу..."
        )

        summary_path = knowledge_summary_service.create_summary_for_file(target_path)

        if summary_path:
            await message.answer(
                "✅ Карточка создана.\n"
                f"Путь: <code>{summary_path}</code>\n\n"
                "🔄 Пересобираю индекс базы знаний..."
            )
        else:
            await message.answer(
                "⚠️ Карточку создать не удалось или документ пустой.\n"
                "🔄 Всё равно пересобираю индекс базы знаний..."
            )

        result = subprocess.run(
            ["venv/bin/python", "scripts/build_knowledge_base_index.py"],
            cwd=".",
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error("KB index rebuild failed: {}", result.stderr)
            await message.answer(
                "⚠️ Файл сохранён, но индекс не пересобрался.\n\n"
                f"<pre>{result.stderr[-1500:]}</pre>"
            )
            await state.clear()
            return

        await message.answer(
            "✅ База знаний обновлена.\n\n"
            f"Категория: <b>{category}</b>\n"
            f"Файл: <code>{target_path.name}</code>\n"
            f"<pre>{result.stdout[-1500:]}</pre>",
            reply_markup=get_main_menu_keyboard(),
        )

        logger.info("Knowledge file uploaded: {}", target_path)

    except Exception as exc:
        logger.exception("Knowledge upload failed: {}", exc)
        await message.answer(f"❌ Ошибка загрузки: {type(exc).__name__}: {exc}")

    await state.clear()
