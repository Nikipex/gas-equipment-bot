from __future__ import annotations

from app.services.supplier_product_candidate_ranker import rank_supplier_candidate

from app.services.ai.teplocel_ranker import rank_teplocel

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright

FAST_NAV_TIMEOUT_MS = int(os.getenv('SUPPLIER_SITE_NAV_TIMEOUT_MS', '6000'))
FAST_ACTION_TIMEOUT_MS = int(os.getenv('SUPPLIER_SITE_ACTION_TIMEOUT_MS', '2500'))
FAST_SETTLE_TIMEOUT_MS = int(os.getenv('SUPPLIER_SITE_SETTLE_TIMEOUT_MS', '800'))
FAST_MAX_SUPPLIERS = int(os.getenv('SUPPLIER_SITE_MAX_SUPPLIERS', '2'))
FAST_SUPPLIER_TOTAL_TIMEOUT_SECONDS = int(os.getenv('SUPPLIER_SITE_TOTAL_TIMEOUT_SECONDS', '6'))
SAVE_SCREENSHOTS = os.getenv('SUPPLIER_SITE_SAVE_SCREENSHOTS', '0') == '1'


@dataclass(frozen=True)
class SupplierWebsiteConfig:
    key: str
    name: str
    base_url: str
    login: str | None
    password: str | None


@dataclass(frozen=True)
class SupplierWebsiteResult:
    supplier_key: str
    supplier_name: str
    title: str
    price: str | None = None
    stock: str | None = None
    url: str | None = None
    raw_text: str | None = None


class WebSupplierSearchService:
    def __init__(self) -> None:
        load_dotenv(".env")
        self.suppliers = _load_supplier_configs()

    async def search_all(
        self,
        query: str,
        limit_per_supplier: int = 10,
        headless: bool = True,
    ) -> list[SupplierWebsiteResult]:
        results: list[SupplierWebsiteResult] = []

        for supplier in self.suppliers[:FAST_MAX_SUPPLIERS]:
            try:
                task = asyncio.create_task(
                    self.search_supplier(
                        supplier=supplier,
                        query=query,
                        limit=limit_per_supplier,
                        headless=headless,
                    )
                )

                done, pending = await asyncio.wait(
                    {task},
                    timeout=FAST_SUPPLIER_TOTAL_TIMEOUT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if pending:
                    task.cancel()
                    try:
                        await task
                    except Exception:
                        pass

                    raise TimeoutError

                supplier_results = task.result()
                results.extend(supplier_results)
            except TimeoutError:
                logger.warning(
                    "Supplier website search timeout: supplier={} timeout={}s",
                    supplier.key,
                    FAST_SUPPLIER_TOTAL_TIMEOUT_SECONDS,
                )

            except Exception as exc:
                logger.warning(
                    "Supplier website search failed: supplier={} error={}: {}",
                    supplier.key,
                    type(exc).__name__,
                    exc,
                )

        return results

    async def search_supplier(
        self,
        supplier: SupplierWebsiteConfig,
        query: str,
        limit: int = 10,
        headless: bool = True,
    ) -> list[SupplierWebsiteResult]:
        snapshot_dir = Path("data/web_snapshots/suppliers") / supplier.key
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            user_data_dir = Path("data/browser_sessions") / supplier.key
            user_data_dir.mkdir(parents=True, exist_ok=True)

            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
                viewport={"width": 1440, "height": 1000},
            )

            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(FAST_ACTION_TIMEOUT_MS)
            page.set_default_navigation_timeout(FAST_NAV_TIMEOUT_MS)

            url = _ensure_url(supplier.base_url)
            logger.info("Opening supplier site: {} {}", supplier.key, url)

            await page.goto(url, wait_until="domcontentloaded", timeout=FAST_NAV_TIMEOUT_MS)
            await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)

            await _safe_screenshot(
                page,
                str(snapshot_dir / "before_login.png"),
                full_page=True,
            )

            if not await _looks_logged_in(page, supplier):
                await _try_login(page, supplier)
            else:
                logger.info("Supplier already logged in: {}", supplier.key)

            await _safe_screenshot(
                page,
                str(snapshot_dir / "after_try_login.png"),
                full_page=True,
            )
            await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)

            await _safe_screenshot(
                page,
                str(snapshot_dir / "after_login.png"),
                full_page=True,
            )

            results = []

            for idx, search_query in enumerate(_build_supplier_query_variants(query), start=1):
                logger.info("Supplier search variant: {} {} -> {}", supplier.key, idx, search_query)

                try:
                    await _try_search(page, search_query)
                    await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
                    await _handle_popups(page)

                    await _safe_screenshot(
                        page,
                        str(snapshot_dir / f"search_results_{idx}.png"),
                        full_page=True,
                    )

                    html = await page.content()
                    (snapshot_dir / f"search_results_{idx}.html").write_text(
                        html,
                        encoding="utf-8",
                    )

                    results = await _collect_results(
                        page=page,
                        supplier=supplier,
                        query=query,
                        limit=limit,
                    )

                    if results and supplier.key == "teplocel":
                        results = await _hydrate_teplocel_results(
                            page=page,
                            supplier=supplier,
                            results=results,
                            query=query,
                            limit=limit,
                        )

                    if results:
                        break

                except Exception as exc:
                    logger.warning("Supplier search variant failed: {} {} {}", supplier.key, search_query, exc)
                    continue

            await context.close()
            return results



async def _safe_screenshot(page, path: str, full_page: bool = True) -> None:
    if not SAVE_SCREENSHOTS:
        return

    try:
        await page.screenshot(
            path=path,
            full_page=full_page,
            timeout=FAST_ACTION_TIMEOUT_MS,
        )
    except Exception as exc:
        logger.warning("Supplier screenshot skipped: {}", exc)


def _load_supplier_configs() -> list[SupplierWebsiteConfig]:
    result: list[SupplierWebsiteConfig] = []

    for index in (1, 2):
        name = os.getenv(f"SUPPLIER_{index}_NAME")
        base_url = os.getenv(f"SUPPLIER_{index}_BASE_URL")
        login = os.getenv(f"SUPPLIER_{index}_LOGIN")
        password = os.getenv(f"SUPPLIER_{index}_PASSWORD")

        if not name or not base_url:
            continue

        result.append(
            SupplierWebsiteConfig(
                key=_slugify(name),
                name=name,
                base_url=base_url,
                login=login,
                password=password,
            )
        )

    return result


async def _try_login(page, supplier: SupplierWebsiteConfig) -> None:
    if not supplier.login or not supplier.password:
        return

    if supplier.key == "teplocel":
        await _teplocel_prepare_page(page)
        await _teplocel_open_login(page)
    else:
        login_open_selectors = [
            'a:has-text("Вход")',
            'a[href*="login"]',
            'a[href*="auth"]',
            'a[href*="user"]',
            'text=Вход',
            'text=Личный кабинет',
            'text=Авторизация',
            'text=Войти',
        ]

        for selector in login_open_selectors:
            try:
                await page.locator(selector).first.click(timeout=FAST_ACTION_TIMEOUT_MS)
                await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
                break
            except Exception:
                pass

    login_selectors = [
        'input[name="login"]',
        'input[name="USER_LOGIN"]',
        'input[name="email"]',
        'input[name="username"]',
        'input[type="email"]',
        'input[placeholder*="логин" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="почт" i]',
        'input[placeholder*="телефон" i]',
        'input[type="text"]',
    ]

    password_selectors = [
        'input[name="password"]',
        'input[name="USER_PASSWORD"]',
        'input[type="password"]',
        'input[placeholder*="пароль" i]',
    ]

    login_input = await _first_visible(page, login_selectors)
    password_input = await _first_visible(page, password_selectors)

    if not login_input or not password_input:
        logger.warning("Login fields not found for {}", supplier.key)
        return

    await login_input.fill(supplier.login)
    await password_input.fill(supplier.password)

    if supplier.key == "teplocel":
        try:
            await page.locator('form button[type="submit"]:has-text("Войти")').first.click(timeout=FAST_ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
            return
        except Exception:
            pass

    for selector in [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Войти")',
        'button:has-text("Вход")',
        'button:has-text("Авторизоваться")',
        'button:has-text("Login")',
    ]:
        try:
            await page.locator(selector).first.click(timeout=FAST_ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
            return
        except Exception:
            pass

    try:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
    except Exception:
        pass


async def _try_search(page, query: str) -> None:
    search_selectors = [
        'input[type="search"]',
        'input[name="q"]',
        'input[name="query"]',
        'input[name="search"]',
        'input[placeholder*="Поиск" i]',
        'input[placeholder*="Найти" i]',
        'input[placeholder*="поиск" i]',
        'input[placeholder*="найти" i]',
        'input[type="text"]',
    ]

    search_input = await _first_visible(page, search_selectors)

    if not search_input:
        raise RuntimeError("Search input not found")

    await search_input.fill(query)
    await page.keyboard.press("Enter")

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=FAST_NAV_TIMEOUT_MS)
    except Exception:
        pass


async def _collect_results(
    page,
    supplier: SupplierWebsiteConfig,
    query: str,
    limit: int,
) -> list[SupplierWebsiteResult]:
    if supplier.key == "teplocel":
        return await _collect_teplocel_search_results(
            page=page,
            supplier=supplier,
            query=query,
            limit=limit,
        )

    results: list[SupplierWebsiteResult] = []
    seen: set[str] = set()

    selectors = [
        ".product",
        ".product-item",
        ".catalog-item",
        ".goods-item",
        ".item",
        ".card",
        "tr",
        "article",
        "main a",
    ]

    for selector in selectors:
        locators = await page.locator(selector).all()

        for item in locators:
            if len(results) >= limit:
                break

            try:
                raw_text = (await item.inner_text(timeout=700)).strip()
            except Exception:
                continue

            if not _looks_like_result(raw_text):
                continue

            if not _matches_supplier_query(query, raw_text):
                continue

            title = _extract_title(raw_text)
            if not title:
                continue

            key = _norm(title)
            if key in seen:
                continue

            seen.add(key)

            href = None
            try:
                if selector == "main a":
                    href = await item.get_attribute("href")
                else:
                    href = await item.locator("a").first.get_attribute("href", timeout=500)
            except Exception:
                pass

            results.append(
                SupplierWebsiteResult(
                    supplier_key=supplier.key,
                    supplier_name=supplier.name,
                    title=title,
                    price=_extract_price(raw_text),
                    stock=_extract_stock(raw_text),
                    url=href,
                    raw_text=raw_text,
                )
            )

        if len(results) >= limit:
            break

    return results


async def _first_visible(page, selectors: list[str]):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=FAST_ACTION_TIMEOUT_MS)
            return loc
        except Exception:
            continue

    return None


def _looks_like_result(text: str) -> bool:
    clean = _norm(text)

    if len(clean) < 8:
        return False

    # Отсекаем разделы/меню
    bad_exact = {
        "радиаторы",
        "насосы",
        "tecofi",
        "navien",
        "комплектующие для котельных",
        "радиаторы отопления",
        "насосы",
    }

    if clean in bad_exact:
        return False

    bad_contains = [
        "главная",
        "каталог",
        "личный кабинет",
        "корзина",
        "оформить заказ",
        "политика",
    ]

    if any(x in clean for x in bad_contains):
        return False

    # Товарная строка должна иметь бренд/модель + товарный маркер или цену/остаток
    product_markers = [
        "baxi",
        "бакси",
        "eco4s",
        "eco 4s",
        "eco-4s",
        "котел",
        "котёл",
        "76596",
    ]

    has_product_marker = any(x in clean for x in product_markers)
    has_price_like = bool(re.search(r"\d[\d\s]{2,}\s*[ир₽]?", text, flags=re.I))

    return has_product_marker and has_price_like

def _extract_title(raw_text: str) -> str | None:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    for line in lines:
        clean = _norm(line)

        if len(clean) < 4:
            continue

        if any(x in clean for x in ["₽", "руб", "остат", "налич", "количество"]):
            continue

        return line[:200]

    return None


def _extract_price(raw_text: str) -> str | None:
    # Terem формат: "98 420И 0 98 420И 219"
    matches = re.findall(r"(\d[\d\s]{2,})\s*[Ии₽]?", raw_text)

    prices = []

    for item in matches:
        value = re.sub(r"\s+", "", item)

        try:
            number = int(value)
        except Exception:
            continue

        if 1000 <= number <= 1000000:
            prices.append(number)

    if prices:
        return f"{min(prices):,}".replace(",", " ") + " ₽"

    match = re.search(r"(\d[\d\s]{2,})\s*(?:₽|руб|р\.)", raw_text, flags=re.I)
    if not match:
        return None

    return re.sub(r"\s+", " ", match.group(0)).strip()

def _extract_stock(raw_text: str) -> str | None:
    # Terem часто в конце строки: "... 98 420И 219 шт"
    match = re.search(r"\b(\d+)\s*шт\b", raw_text, flags=re.I)
    if match:
        return match.group(1)

    match = re.search(
        r"(?:остаток|наличии|осталось|кол-во|количество)\D{0,20}(\d+)",
        raw_text,
        flags=re.I,
    )

    if not match:
        return None

    return match.group(1)






async def _collect_teplocel_search_results(
    page,
    supplier: SupplierWebsiteConfig,
    query: str,
    limit: int,
) -> list[SupplierWebsiteResult]:
    results: list[SupplierWebsiteResult] = []
    seen: set[str] = set()

    links = await page.locator("a").all()

    for link in links:
        if len(results) >= limit:
            break

        try:
            title = (await link.inner_text(timeout=300)).strip()
            href = await link.get_attribute("href")
        except Exception:
            continue

        if not href:
            continue

        if "/products/" not in href:
            continue

        combo = _norm(f"{title} {href}")

        if not title:
            title = href.rsplit("/", 2)[-2].replace("-", " ")

        ranked = rank_supplier_candidate(
            query=query,
            title=title,
            href=href,
        )

        if ranked.score < 0.72:
            continue

        key = href
        if key in seen:
            continue

        seen.add(key)

        results.append(
            SupplierWebsiteResult(
                supplier_key=supplier.key,
                supplier_name=supplier.name,
                title=title,
                price=None,
                stock=None,
                url=href,
                raw_text=f"{title}\nmatch_score={ranked.score}\nmatch_reason={ranked.reason}",
            )
        )

    return results


async def _hydrate_teplocel_results(
    page,
    supplier: SupplierWebsiteConfig,
    results: list[SupplierWebsiteResult],
    query: str,
    limit: int,
) -> list[SupplierWebsiteResult]:
    hydrated: list[SupplierWebsiteResult] = []

    for item in results[:limit]:
        if not item.url:
            continue

        url = item.url
        if url.startswith("/"):
            url = "https://teplocel.ru" + url

        try:
            # Жестко отсекаем 1.24F до перехода в карточку
            if not _matches_supplier_query(query, f"{item.title} {url}"):
                continue

            ranked = rank_supplier_candidate(
                query=query,
                title=item.title,
                href=url,
            )

            if ranked.score < 0.80:
                continue

            await page.goto(url, wait_until="domcontentloaded", timeout=FAST_NAV_TIMEOUT_MS)
            await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)

            try:
                await page.get_by_text("Наличие", exact=True).first.click(timeout=FAST_ACTION_TIMEOUT_MS)
                await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
            except Exception:
                pass

            raw_text = await page.locator("body").inner_text(timeout=FAST_NAV_TIMEOUT_MS)
            page_html = await page.content()

            title = _extract_teplocel_product_title(raw_text) or item.title
            price = _extract_teplocel_product_price(raw_text) or item.price
            stock = _extract_teplocel_warehouse_stock(page_html)

            if not stock:
                stock = _extract_teplocel_warehouse_stock(raw_text)

            if not stock:
                stock = _extract_teplocel_product_stock(raw_text) or item.stock

            # Повторная проверка уже по финальному title/url
            if not _matches_supplier_query(query, f"{title} {url}"):
                continue

            final_rank = rank_supplier_candidate(
                query=query,
                title=title,
                href=url,
            )

            if final_rank.score < 0.80:
                continue

            hydrated.append(
                SupplierWebsiteResult(
                    supplier_key=supplier.key,
                    supplier_name=supplier.name,
                    title=title,
                    price=price,
                    stock=stock,
                    url=url,
                    raw_text=raw_text,
                )
            )

        except Exception as exc:
            logger.warning("Teplocel hydrate failed: {} {}", item.url, exc)

    return hydrated


def _extract_teplocel_product_title(raw_text: str) -> str | None:
    for line in raw_text.splitlines():
        clean = line.strip()
        if not clean:
            continue

        norm = _norm(clean)

        if norm.startswith("котел газовый"):
            return clean

        if norm.startswith("котёл газовый"):
            return clean

    return None


def _extract_teplocel_product_price(raw_text: str) -> str | None:
    match = re.search(
        r"Цена\s+([\d\s]+(?:,\d+)?)\s*руб",
        raw_text,
        flags=re.I,
    )

    if not match:
        return None

    return match.group(1).strip() + " руб."




def _extract_teplocel_warehouse_stock(stock_text: str) -> str | None:
    text = str(stock_text or "")

    pairs: list[str] = []

    # Вариант 1: остатки в JS-строке с экранированным HTML
    escaped_pattern = re.compile(
        r'b-stores-list__col title\\">\\s*([^<]+?)\\s*<\\/div>\\s*<div class=\\"b-stores-list__col b-stores-list__amount\\">\\s*(\\d+)\\s*<\\/div>',
        flags=re.I | re.S,
    )

    for warehouse, qty in escaped_pattern.findall(text):
        warehouse = warehouse.strip()
        qty = qty.strip()

        if warehouse and qty != "0" and "запчасти" not in warehouse.lower():
            pairs.append(f"{warehouse}: {qty}")

    if pairs:
        return "; ".join(pairs)

    # Вариант 2: обычный HTML без экранирования
    html_pattern = re.compile(
        r'<div class="b-stores-list__col title">\s*([^<]+?)\s*</div>\s*<div class="b-stores-list__col b-stores-list__amount">\s*(\d+)\s*</div>',
        flags=re.I | re.S,
    )

    for warehouse, qty in html_pattern.findall(text):
        warehouse = warehouse.strip()
        qty = qty.strip()

        if warehouse and qty != "0" and "запчасти" not in warehouse.lower():
            pairs.append(f"{warehouse}: {qty}")

    if pairs:
        return "; ".join(pairs)

    # Вариант 3: текст после клика вкладки
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    warehouses = {
        "ростов-на-дону",
        "нижний новгород",
        "уфа",
        "липецк",
        "краснодар",
        "москва",
        "воронеж",
        "самара",
        "казань",
        "екатеринбург",
    }

    i = 0
    while i < len(lines) - 1:
        warehouse = lines[i].strip()
        qty = lines[i + 1].strip()

        if warehouse.lower().replace("ё", "е") in warehouses and re.fullmatch(r"\d+", qty):
            pairs.append(f"{warehouse}: {qty}")
            i += 2
            continue

        i += 1

    return "; ".join(pairs) if pairs else None


def _extract_teplocel_product_stock(raw_text: str) -> str | None:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # Ищем таб/секцию "Наличие" и собираем склады ниже.
    stock_lines: list[str] = []
    inside_stock = False

    warehouse_markers = [
        "ростов",
        "уфа",
        "краснодар",
        "москва",
        "воронеж",
        "самара",
        "казань",
        "екатеринбург",
        "склад",
    ]

    stop_markers = [
        "отзывы",
        "похожие товары",
        "характеристики",
        "файлы",
        "заказать звонок",
        "каталог товаров",
    ]

    for line in lines:
        clean = line.lower().replace("ё", "е")

        if clean == "наличие":
            inside_stock = True
            continue

        if inside_stock and any(x in clean for x in stop_markers):
            break

        if not inside_stock:
            continue

        # Примеры возможных строк:
        # Ростов-на-Дону много
        # Уфа 3
        # Склад Ростов: много
        # В наличии много
        has_warehouse = any(x in clean for x in warehouse_markers)
        has_qty = any(x in clean for x in ["много", "есть", "нет"]) or bool(re.search(r"\b\d+\b", clean))

        if has_warehouse or has_qty:
            stock_lines.append(line)

    if stock_lines:
        return "; ".join(stock_lines[:10])

    text = raw_text.lower().replace("ё", "е")

    if "в наличиимного" in text or "в наличии много" in text:
        return "много"

    match = re.search(r"в наличии\s*(\d+)", text)
    if match:
        return match.group(1)

    if "в наличии" in text:
        return "есть"

    return None


def _matches_supplier_query(query: str, raw_text: str) -> bool:
    query_clean = _norm(query)
    text = _norm(raw_text)

    # Если ищем 24F / 24 F, не пропускаем 1.24F.
    wants_24f = bool(
        re.search(r"\b24\s*f\b|\b24f\b", query_clean)
    )

    if wants_24f:
        if re.search(r"\b1\.24\s*f\b|\b1\.24f\b", text):
            return False

        if not re.search(r"\b24\s*f\b|\b24f\b", text):
            return False

    # Если ищем 1.24F, наоборот не пропускаем обычный 24F.
    wants_124f = bool(
        re.search(r"\b1\.24\s*f\b|\b1\.24f\b", query_clean)
    )

    if wants_124f:
        if not re.search(r"\b1\.24\s*f\b|\b1\.24f\b", text):
            return False

    return True

def _ensure_url(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value

    return "https://" + value


def _slugify(value: str) -> str:
    text = _norm(value)
    text = re.sub(r"[^a-zа-я0-9]+", "_", text)
    text = text.strip("_")
    return text or "supplier"


def _norm(value: object) -> str:
    return str(value or "").lower().replace("ё", "е").strip()



async def _handle_popups(page) -> None:
    # Generic popup handler.
    # НЕ кликаем "cookies" / "используем cookies", это может быть ссылка на policy page.
    for text in [
        "Верно",
        "Да",
        "Принято",
        "Понятно",
        "ОК",
        "Ok",
        "Закрыть",
    ]:
        try:
            body_url = page.url.lower()
            if "teplocel" in body_url and text != "Верно":
                continue

            await page.get_by_text(text, exact=True).first.click(timeout=FAST_ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
        except Exception:
            pass


def _build_supplier_query_variants(query: str) -> list[str]:
    raw = str(query or "").strip()
    clean = raw.lower().replace("ё", "е")

    variants = [raw]

    replacements = {
        "бакси": "BAXI",
        "эко": "ECO",
        "еко": "ECO",
        "4с": "4S",
        "4 c": "4S",
        "24ф": "24F",
        "24 ф": "24F",
        "24fi": "24Fi",
        "24 fi": "24Fi",
    }

    normalized = clean
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst.lower())

    normalized = normalized.upper()
    variants.append(normalized)

    # BAXI ECO 4S 24F -> более мягкие варианты
    soft = normalized.replace("-", " ")
    variants.append(soft)
    variants.append(soft.replace("24F", "24 F"))
    variants.append(soft.replace("ECO 4S", "ECO-4S"))
    variants.append(soft.replace("ECO 4S", "Эко 4S").replace("BAXI", "Бакси"))
    variants.append(soft.replace("BAXI ", ""))
    variants.append(" ".join([x for x in soft.split() if x not in {"КОТЕЛ", "ГАЗОВЫЙ", "НАСТЕННЫЙ"}]))

    result = []
    seen = set()

    for item in variants:
        item = " ".join(str(item).split())
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            result.append(item)

    return result



async def _looks_logged_in(page, supplier: SupplierWebsiteConfig) -> bool:
    try:
        text = (await page.locator("body").inner_text(timeout=FAST_ACTION_TIMEOUT_MS)).lower().replace("ё", "е")
    except Exception:
        return False

    if supplier.key == "terem":
        return any(x in text for x in ["выход", "личный кабинет", "размещение заказов", "заказы"])

    if supplier.key == "teplocel":
        return any(x in text for x in ["выход", "кабинет партнера", "личный кабинет", "профиль"])

    return any(x in text for x in ["выход", "личный кабинет", "профиль"])



async def _teplocel_prepare_page(page) -> None:
    # ВАЖНО:
    # Не трогаем cookie banner вообще.
    # На Теплоцели клик по cookies уводит на legacy-cookies-agreement.php.
    # Единственное, что можно нажимать безопасно — город "Верно".
    try:
        await page.get_by_text("Верно", exact=True).first.click(timeout=FAST_ACTION_TIMEOUT_MS)
        await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)
    except Exception:
        pass


async def _teplocel_open_login(page) -> None:
    await page.goto(
        "https://teplocel.ru/auth/",
        wait_until="domcontentloaded",
        timeout=FAST_NAV_TIMEOUT_MS,
    )
    await page.wait_for_timeout(FAST_SETTLE_TIMEOUT_MS)

