from pprint import pprint

from dotenv import load_dotenv

from app.services.ai.ai_router_service import (
    AIRouterService,
)

load_dotenv(".env")

router = AIRouterService()

tests = [
    "найди baxi eco 4s 24",
    "прайс baxi eco 4s 24 скидка 5 до сотен",
    "найди fondital у поставщиков",
    "прайс navien deluxe plus для клиента",
]

for text in tests:
    print()
    print("=" * 60)
    print("INPUT:", text)

    result = router.parse(text)

    pprint(result)
