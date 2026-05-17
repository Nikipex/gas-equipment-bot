from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from playwright.async_api import async_playwright


@dataclass(frozen=True)
class BoilerSelectionRequest:
    brand: str | None = None
    boiler_type: str | None = None
    chamber: str | None = None
    circuits: int | None = None
    power_min: float | None = None
    power_max: float | None = None


@dataclass(frozen=True)
class BoilerSelectionResult:
    title: str
    url: str | None = None
    raw_text: str | None = None


class EquipmentSelectorService:
    def __init__(self) -> None:
        load_dotenv(".env")
        self.base_url = os.getenv("EQUIPMENT_SELECTOR_BASE_URL")

        if not self.base_url:
            raise RuntimeError("EQUIPMENT_SELECTOR_BASE_URL is empty")

    async def select_boilers(
        self,
        request: BoilerSelectionRequest,
        limit: int = 10,
        headless: bool = True,
    ) -> list[BoilerSelectionResult]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})

            await page.goto(self.base_url, wait_until="networkidle", timeout=120000)

            try:
                await page.click("text=Принято", timeout=3000)
            except Exception:
                pass

            if "kotly" not in page.url and "kotel" not in page.url:
                try:
                    await page.click("text=КАТАЛОГ", timeout=5000)
                    await page.click("text=Котлы отопления", timeout=5000)
                    await page.wait_for_load_state("networkidle")
                except Exception:
                    pass

            sidebar = page.locator(".widget.filter").first

            if request.brand:
                await _click_filter_label(sidebar, request.brand)

            if request.boiler_type:
                await _click_filter_label(sidebar, _map_boiler_type(request.boiler_type))

            if request.chamber:
                await _click_filter_label(sidebar, _map_chamber(request.chamber))

            if request.circuits:
                await _click_filter_label(sidebar, _map_circuits(request.circuits))

            if request.power_min is not None or request.power_max is not None:
                await _fill_power_range(
                    sidebar,
                    request.power_min,
                    request.power_max,
                )

            await _apply_filter(page)

            await page.wait_for_timeout(4000)

            await page.screenshot(
                path="data/web_snapshots/selector_selected.png",
                full_page=True,
            )

            results = await _collect_product_results(page, limit=limit)

            await browser.close()

            return results


async def _click_filter_label(sidebar, label_text: str) -> None:
    if not label_text:
        return

    labels = await sidebar.locator("label").all()

    for label in labels:
        try:
            text = (await label.inner_text(timeout=500)).strip()
        except Exception:
            continue

        if label_text.lower() not in text.lower():
            continue

        input_id = await label.get_attribute("for")

        if input_id:
            checkbox = sidebar.locator(f"#{input_id}").first

            try:
                await checkbox.evaluate(
                    """
                    el => {
                        el.checked = true;
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('click', { bubbles: true }));
                    }
                    """
                )
                return
            except Exception:
                pass

        try:
            await label.evaluate(
                """
                el => {
                    el.click();
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """
            )
            return
        except Exception:
            pass

    raise RuntimeError(f"Filter label not found or not clickable: {label_text}")


async def _fill_power_range(sidebar, power_min: float | None, power_max: float | None) -> None:
    section = sidebar.locator(".category-filter.product-filter-section").filter(has_text="Мощность").first
    inputs = section.locator("input")

    count = await inputs.count()

    if count < 2:
        return

    async def set_hidden_input(index: int, value: float) -> None:
        inp = inputs.nth(index)
        await inp.evaluate(
            """
            (el, value) => {
                el.value = String(value);
                el.setAttribute('value', String(value));
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            }
            """,
            str(value),
        )

    if power_min is not None:
        await set_hidden_input(0, power_min)

    if power_max is not None:
        await set_hidden_input(1, power_max)


async def _apply_filter(page) -> None:
    # Сначала пробуем явную кнопку Подобрать
    try:
        button = page.locator(".widget.filter").first.get_by_text("Подобрать", exact=False).first
        await button.scroll_into_view_if_needed(timeout=2000)
        await button.click(timeout=3000)
        await page.wait_for_load_state("networkidle", timeout=120000)
        return
    except Exception:
        pass

    # Иногда фильтр применяет переходом после клика
    try:
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle", timeout=120000)
    except Exception:
        pass


async def _collect_product_results(page, limit: int) -> list[BoilerSelectionResult]:
    results: list[BoilerSelectionResult] = []

    # На сайте карточки могут быть разной верстки, поэтому собираем осмысленные ссылки из main.
    links = await page.locator("main a").all()

    seen: set[str] = set()

    skip_words = {
        "купить",
        "подробнее",
        "в корзину",
        "сравнить",
        "избранное",
        "следующая",
        "предыдущая",
    }

    for link in links:
        try:
            title = (await link.inner_text(timeout=500)).strip()
            href = await link.get_attribute("href")
        except Exception:
            continue

        if not title:
            continue

        clean = _clean_title(title)
        if not _looks_like_boiler_title(clean):
            continue

        if clean.lower() in skip_words:
            continue

        if clean.lower() in seen:
            continue

        seen.add(clean.lower())

        raw_text = None
        try:
            raw_text = await link.locator(
                "xpath=ancestor::*[contains(@class, 'product') or contains(@class, 'item') or contains(@class, 'loop') or contains(@class, 'col')][1]"
            ).inner_text(timeout=1000)
        except Exception:
            pass

        results.append(
            BoilerSelectionResult(
                title=clean,
                url=href,
                raw_text=raw_text,
            )
        )

        if len(results) >= limit:
            break

    return results


def _map_boiler_type(value: str) -> str:
    text = value.lower()

    if "наст" in text or "wall" in text:
        return "Настенные газовые"

    if "нап" in text or "floor" in text:
        return "Напольные газовые"

    if "элект" in text:
        return "Электрические"

    return value


def _map_chamber(value: str) -> str:
    text = value.lower()

    if "зак" in text or "турбо" in text or "closed" in text:
        return "закрытая (турбо)"

    if "откр" in text or "атмо" in text or "open" in text:
        return "открытая (атмо)"

    return value


def _map_circuits(value: int) -> str:
    if value == 1:
        return "одноконтурный"

    if value == 2:
        return "двухконтурный"

    return str(value)


def _clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = text.replace("\xa0", " ")
    return text


def _looks_like_boiler_title(value: str) -> bool:
    text = value.lower()

    if len(text) < 8:
        return False

    boiler_markers = (
        "котел",
        "котёл",
        "baxi",
        "бакси",
        "navien",
        "навьен",
        "ariston",
        "аристон",
        "bosch",
        "бош",
        "protherm",
        "buderus",
        "viessmann",
        "лемакс",
        "zota",
        "эван",
        "fondital",
    )

    return any(marker in text for marker in boiler_markers)
