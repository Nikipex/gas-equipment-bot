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

        await page.screenshot(
            path="data/web_snapshots/debug_selector_page.png",
            full_page=True,
        )

        html = await page.content()
        Path("data/web_snapshots/debug_selector_page.html").write_text(html, encoding="utf-8")

        print("URL:", page.url)
        print("TITLE:", await page.title())

        print("\nTEXT BLOCKS WITH FILTER WORDS:")
        blocks = await page.locator("body *").all()

        keywords = [
            "Бренды",
            "Тип",
            "Мощность",
            "Камера сгорания",
            "Количество контуров",
            "Подобрать",
        ]

        found = 0

        for i, el in enumerate(blocks):
            try:
                text = (await el.inner_text(timeout=300)).strip()
            except Exception:
                continue

            if not text:
                continue

            if any(k in text for k in keywords):
                try:
                    cls = await el.get_attribute("class")
                    tag = await el.evaluate("el => el.tagName")
                except Exception:
                    cls = None
                    tag = "?"

                print("\n--- BLOCK", i, "---")
                print("TAG:", tag)
                print("CLASS:", cls)
                print(text[:1000])
                found += 1

                if found >= 30:
                    break

        input("\nENTER to close browser...")
        await browser.close()


asyncio.run(main())
