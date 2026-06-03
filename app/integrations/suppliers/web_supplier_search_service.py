from __future__ import annotations

from app.services.supplier_product_candidate_ranker import rank_supplier_candidate

from app.services.ai.teplocel_ranker import rank_teplocel

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright


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

        for supplier in self.suppliers:
            try:
                supplier_results = await self.search_supplier(
                    supplier=supplier,
                    query=query,
                    limit=limit_per_supplier,
                    headless=headless,
                )
                results.extend(supplier_results)
            except Exception as exc:
                logger.exception(
                    "Supplier website search failed: supplier={} error={}",
                    supplier.key,
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

            url = _ensure_url(supplier.base_url)
            logger.info("Opening supplier site: {} {}", supplier.key, url)

            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(2500)

            await page.screenshot(
                path=str(snapshot_dir / "before_login.png"),
                full_page=True,
            )

            if not await _looks_logged_in(page, supplier):
                await _try_login(page, supplier)
            else:
                logger.info("Supplier already logged in: {}", supplier.key)

            await page.screenshot(
                path=str(snapshot_dir / "after_try_login.png"),
                full_page=True,
            )
            await page.wait_for_timeout(2000)

            await page.screenshot(
                path=str(snapshot_dir / "after_login.png"),
                full_page=True,
            )

            results = []

            for idx, search_query in enumerate(_build_supplier_query_variants(query), start=1):
                logger.info("Supplier search variant: {} {} -> {}", supplier.key, idx, search_query)

                try:
                    await _try_search(page, search_query)
                    await page.wait_for_timeout(3500)
                    await _handle_popups(page)

                    await page.screenshot(
                        path=str(snapshot_dir / f"search_results_{idx}.png"),
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
                await page.locator(selector).first.click(timeout=3000)
                await page.wait_for_timeout(2000)
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
            await page.locator('form button[type="submit"]:has-text("Войти")').first.click(timeout=5000)
            await page.wait_for_timeout(5000)
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
            await page.locator(selector).first.click(timeout=3000)
            await page.wait_for_timeout(5000)
            return
        except Exception:
            pass

    try:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)
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
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
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
            await loc.wait_for(state="visible", timeout=1200)
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

    cards = await page.locator(".sitem.catitem").all()

    for card in cards:
        if len(results) >= limit:
            break

        try:
            title = (await card.locator("a.nm").first.inner_text(timeout=700)).strip()
            href = await card.locator("a.nm").first.get_attribute("href", timeout=700)
        except Exception:
            continue

        if not title or not href or "/products/" not in href:
            continue

        desc = ""
        chain = ""

        try:
            desc = (await card.locator(".description").first.inner_text(timeout=500)).strip()
        except Exception:
            pass

        try:
            chain = (await card.locator(".chain").first.inner_text(timeout=500)).strip()
        except Exception:
            pass

        combo = f"{title} {desc} {chain} {href}"

        if not _teplocel_card_matches_query(query, combo):
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
                raw_text=combo,
            )
        )

    return results


def _teplocel_card_matches_query(query: str, combo: str) -> bool:
    q = _norm(query)
    t = _norm(combo)

    bad_parts = [
        "запчаст",
        "вентилятор",
        "плата",
        "бак расширительный",
        "расширительный",
        "датчик",
        "насос",
        "mvl",
        "ro/rus",
    ]

    if any(x in t for x in bad_parts):
        return False

    is_boiler_query = any(x in q for x in ["котел", "котёл", "baxi", "бакси", "luna", "eco"])
    if is_boiler_query:
        if not any(x in t for x in ["котел", "котёл", "газовый котел", "настенный"]):
            return False

    q_tokens = _model_tokens(q)
    t_tokens = _model_tokens(t)

    # Для запроса Luna-3 1.310 Fi:
    # обязательные токены должны сохранять Comfort как валидный вариант,
    # но отрезать 310Fi без 1.310, если в запросе было 1.310.
    if "luna" in q_tokens and "luna" not in t_tokens:
        return False

    if "fi" in q_tokens and "fi" not in t_tokens:
        return False

    if "1.310" in q_tokens and "1.310" not in t_tokens:
        return False

    # ВАЖНО: 24F и 1.24F — разные котлы.
    wants_24f = bool(re.search(r"\b24\s*f\b|\b24f\b", q))
    wants_124f = bool(re.search(r"\b1[\s\.-]*24\s*f\b|\b1[\s\.-]*24f\b", q))

    if wants_24f and not wants_124f:
        if re.search(r"\b1[\s\.-]*24\s*f\b|\b1[\s\.-]*24f\b", t):
            return False
        if not re.search(r"\b24\s*f\b|\b24f\b", t):
            return False

    if wants_124f:
        if not re.search(r"\b1[\s\.-]*24\s*f\b|\b1[\s\.-]*24f\b", t):
            return False

    if "24f" in q_tokens and "24f" not in t_tokens:
        return False

    matched = sum(1 for token in q_tokens if token in t_tokens)
    if not q_tokens:
        return True

    return matched / len(q_tokens) >= 0.55


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
            logger.info("TEPLOCEL HYDRATE START: {}", item.title)

            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            await page.wait_for_timeout(700)

            raw_text = await page.locator("body").inner_text(timeout=3000)
            page_html = await page.content()

            title = _extract_teplocel_product_title(raw_text) or item.title
            price = _extract_teplocel_lk_price(page_html) or _extract_teplocel_price_from_html(page_html) or _extract_teplocel_product_price(raw_text) or item.price
            stock = _extract_teplocel_warehouse_stock(page_html)

            if not stock:
                stock = _extract_teplocel_warehouse_stock(raw_text)

            if not stock:
                stock = _extract_teplocel_product_stock(raw_text) or item.stock

            # Card was already filtered on search page; hydrate is only for price/stock.

            logger.info("TEPLOCEL HYDRATE OK: {} price={} stock={}", title, price, stock)

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


def _extract_teplocel_lk_price(page_html: str) -> str | None:
    """Extract Teplocel LK/OPT price from product card HTML.

    Real structure:
    <span class="c-prices__price js-prices__price-code_OPT" data-pricecode="OPT">
        <span class="c-prices__value js-prices_pdv_OPT">33 184,71 руб.</span>
    </span>
    """
    import html as html_lib

    # 1) Direct class match: most reliable for Teplocel LK price.
    match = re.search(
        r'<span[^>]*class="[^"]*js-prices_pdv_OPT[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
        page_html,
        flags=re.I | re.S,
    )
    if match:
        value = html_lib.unescape(match.group(1)).strip()
        value = " ".join(value.split())
        if value:
            return value

    # 2) Fallback: isolate OPT price block first.
    block_match = re.search(
        r'<span[^>]*(?:data-pricecode="OPT"|class="[^"]*js-prices__price-code_OPT[^"]*")[^>]*>.*?</span>\s*</span>',
        page_html,
        flags=re.I | re.S,
    )
    if block_match:
        block = block_match.group(0)
        value_match = re.search(
            r'<span[^>]*class="[^"]*c-prices__value[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
            block,
            flags=re.I | re.S,
        )
        if value_match:
            value = html_lib.unescape(value_match.group(1)).strip()
            value = " ".join(value.split())
            if value:
                return value

    return None


def _extract_teplocel_price_from_html(page_html: str) -> str | None:
    import html as html_lib

    patterns = [
        r'class="[^"]*js-prices_pdv_OPT[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
        r'class="[^"]*c-prices__value[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
    ]

    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.I | re.S)
        if not match:
            continue

        value = html_lib.unescape(match.group(1)).strip()
        value = " ".join(value.split())

        if value:
            return value

    return None



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

    # Режем не модели, а типовой мусор: запчасти/комплектующие не должны проходить как котлы.
    bad_parts = [
        "запчаст",
        "вентилятор",
        "mvl",
        "плата",
        "датчик",
        "насос",
        "термостат",
    ]

    if any(x in text for x in bad_parts):
        return False

    # Старое важное правило: 24F и 1.24F — разные сущности.
    wants_24f = bool(re.search(r"\b24\s*f\b|\b24f\b", query_clean))

    if wants_24f:
        if re.search(r"\b1\.24\s*f\b|\b1\.24f\b", text):
            return False

        if not re.search(r"\b24\s*f\b|\b24f\b", text):
            return False

    wants_124f = bool(re.search(r"\b1\.24\s*f\b|\b1\.24f\b", query_clean))

    if wants_124f:
        if not re.search(r"\b1\.24\s*f\b|\b1\.24f\b", text):
            return False

    # Универсальный скоринг по токенам модели.
    query_tokens = _model_tokens(query_clean)
    text_tokens = _model_tokens(text)

    if not query_tokens:
        return True

    matched = sum(1 for token in query_tokens if token in text_tokens)

    # Для коротких запросов требуем почти полное совпадение.
    if len(query_tokens) <= 3:
        return matched >= max(1, len(query_tokens) - 1)

    # Для длинных запросов достаточно ~70%, чтобы не убивать Comfort/варианты комплектации.
    return matched / len(query_tokens) >= 0.7


def _model_tokens(value: str) -> set[str]:
    value = value.lower().replace("ё", "е")
    value = value.replace("-", " ")
    value = value.replace("/", " ")

    raw_tokens = re.findall(r"[a-zа-я]+|\d+(?:\.\d+)?", value)

    stop = {
        "котел",
        "котёл",
        "газовый",
        "настенный",
        "напольный",
        "турбо",
        "турбированный",
        "одноконтурный",
        "двухконтурный",
        "с",
        "без",
        "комплектом",
        "комплекта",
        "приводом",
        "датчиком",
        "температуры",
        "бойлера",
    }

    tokens: set[str] = set()

    for token in raw_tokens:
        if len(token) < 2:
            continue

        if token in stop:
            continue

        tokens.add(token)

        # 1.310 должно также матчиться с 310, но не наоборот как единственный критерий.
        if re.fullmatch(r"\d+\.\d+", token):
            tokens.add(token.split(".")[-1])

    # Склейки типа 310fi / 24f
    compact = re.sub(r"[^a-zа-я0-9]", "", value)
    for token in re.findall(r"\d+[a-z]+", compact):
        tokens.add(token)

    # Форматы типа "24 F" / "24-F" / "24.F" тоже считаем как "24f"
    for num, letter in re.findall(r"\b(\d+)\s*([a-z])\b", value):
        tokens.add(f"{num}{letter}")

    return tokens

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

            await page.get_by_text(text, exact=True).first.click(timeout=1500)
            await page.wait_for_timeout(700)
        except Exception:
            pass


def _teplocel_prepare_query(query: str) -> str | None:
    q = str(query or "").strip()
    low = q.lower().replace("ё", "е")

    # ТеплоЦель не продаёт Navien/Drazice — не тратим 20-40 сек на пустой поиск.
    blocked = [
        "navien",
        "навьен",
        "drazice",
        "dražice",
        "дражице",
    ]

    if any(x in low for x in blocked):
        return None

    # На ТеплоЦели слово Ariston в поиске часто убивает выдачу.
    # Ищем по модели.
    ariston_words = [
        "ariston",
        "аристон",
    ]

    for word in ariston_words:
        q = q.replace(word, "")
        q = q.replace(word.upper(), "")
        q = q.replace(word.capitalize(), "")

    q = " ".join(q.split())
    return q or query


def _build_supplier_query_variants(query: str) -> list[str]:
    prepared = _teplocel_prepare_query(query)
    if prepared is None:
        return []
    query = prepared
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
        text = (await page.locator("body").inner_text(timeout=5000)).lower().replace("ё", "е")
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
        await page.get_by_text("Верно", exact=True).first.click(timeout=2500)
        await page.wait_for_timeout(1000)
    except Exception:
        pass


async def _teplocel_open_login(page) -> None:
    await page.goto(
        "https://teplocel.ru/auth/",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    await page.wait_for_timeout(2500)

