import asyncio

from app.integrations.equipment_selector.selector_service import (
    BoilerSelectionRequest,
    EquipmentSelectorService,
)


async def main() -> None:
    service = EquipmentSelectorService()

    results = await service.select_boilers(
        BoilerSelectionRequest(
            brand="Baxi",
            boiler_type="настенный",
            chamber="турбо",
            circuits=2,
            power_min=20,
            power_max=28,
        ),
        limit=10,
        headless=False,
    )

    print("FOUND:", len(results))

    for item in results:
        print()
        print("TITLE:", item.title)
        print("URL:", item.url)
        if item.raw_text:
            print("RAW:", item.raw_text[:500])


asyncio.run(main())
