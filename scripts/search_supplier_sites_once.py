import asyncio

from app.integrations.suppliers.web_supplier_search_service import WebSupplierSearchService


async def main():
    service = WebSupplierSearchService()

    results = await service.search_all(
        query="Baxi Eco 4s 24F",
        limit_per_supplier=10,
        headless=True,
    )

    print("RESULTS:", len(results))
    print("=" * 80)

    for item in results:
        print("SUPPLIER:", item.supplier_name)
        print("TITLE:", item.title)
        print("PRICE:", item.price)
        print("STOCK:", item.stock)
        print("URL:", item.url)
        print("RAW:", (item.raw_text or "")[:700])
        print("-" * 80)


asyncio.run(main())
