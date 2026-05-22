import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv(".env")

LOGIN = os.getenv("SUPPLIER_1_LOGIN")
PASSWORD = os.getenv("SUPPLIER_1_PASSWORD")

SESSION_DIR = "data/browser_sessions/teplocel"
STATE_PATH = "data/browser_sessions/teplocel_state.json"
SNAP_DIR = Path("data/web_snapshots/suppliers/teplocel_login_once")
SNAP_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    if not LOGIN or not PASSWORD:
        raise RuntimeError("SUPPLIER_1_LOGIN / SUPPLIER_1_PASSWORD пустые в .env")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=True,
            viewport={"width": 1440, "height": 1000},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto("https://teplocel.ru/auth/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)

        await page.locator('input[name="USER_LOGIN"]').fill(LOGIN)
        await page.locator('input[name="USER_PASSWORD"]').fill(PASSWORD)

        await page.locator('input[name="USER_REMEMBER"]').evaluate(
            """el => {
                el.checked = true;
                el.setAttribute('checked', 'checked');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('click', { bubbles: true }));
            }"""
        )

        checked = await page.locator('input[name="USER_REMEMBER"]').is_checked()
        print("REMEMBER_CHECKED:", checked)

        await page.screenshot(path=str(SNAP_DIR / "01_filled_remember.png"), full_page=True)

        await page.locator('form:has(input[name="USER_LOGIN"]) button[type="submit"]').first.click(timeout=10000)
        await page.wait_for_timeout(7000)

        await page.screenshot(path=str(SNAP_DIR / "02_after_submit.png"), full_page=True)

        print("URL:", page.url)
        print("TITLE:", await page.title())

        body = (await page.locator("body").inner_text(timeout=10000)).lower().replace("ё", "е")

        if any(x in body for x in ["выход", "кабинет партнера", "личный кабинет", "профиль", "главная"]):
            await context.storage_state(path=STATE_PATH)
            print("LOGIN_OK")
            print("STATE_SAVED:", STATE_PATH)
        else:
            print("LOGIN_NOT_CONFIRMED")
            print(body[:2000])

        await context.close()


asyncio.run(main())
