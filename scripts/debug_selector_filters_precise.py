import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv(".env")

URL = os.getenv("EQUIPMENT_SELECTOR_BASE_URL")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})

        await page.goto(URL, wait_until="networkidle", timeout=120000)

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
        print("SIDEBAR COUNT:", await page.locator(".widget.filter").count())

        sections = await sidebar.locator(".category-filter.product-filter-section").all()
        print("SECTIONS:", len(sections))

        for idx, section in enumerate(sections):
            print("\n" + "=" * 70)
            print("SECTION", idx)

            try:
                title = (await section.locator(".param_lbl").first.inner_text()).strip()
            except Exception:
                title = "NO_TITLE"

            print("TITLE:", title)

            # Раскрываем секцию, если она закрыта
            try:
                await section.locator(".param_lbl").first.click(timeout=2000)
                await page.wait_for_timeout(500)
            except Exception as exc:
                print("CLICK ERR:", type(exc).__name__, exc)

            raw = ""
            try:
                raw = await section.inner_text(timeout=1000)
            except Exception:
                pass

            print("RAW:")
            print(raw[:2000])

            # Печатаем inputs/labels внутри секции
            inputs = await section.locator("input").all()
            print("INPUTS:", len(inputs))

            for i, inp in enumerate(inputs[:30]):
                try:
                    typ = await inp.get_attribute("type")
                    name = await inp.get_attribute("name")
                    value = await inp.get_attribute("value")
                    checked = await inp.is_checked()
                    visible = await inp.is_visible()
                    print(f"  input {i}: type={typ} name={name} value={value} checked={checked} visible={visible}")
                except Exception as exc:
                    print("  input err:", exc)

            labels = await section.locator("label").all()
            print("LABELS:", len(labels))

            for i, label in enumerate(labels[:30]):
                try:
                    text = (await label.inner_text()).strip()
                    if text:
                        print(f"  label {i}: {text}")
                except Exception:
                    pass

        html = await sidebar.inner_html()
        Path("data/web_snapshots/sidebar_filter.html").write_text(html, encoding="utf-8")

        await page.screenshot(path="data/web_snapshots/sidebar_filter.png", full_page=True)

        input("\nENTER to close...")
        await browser.close()


asyncio.run(main())
