from pprint import pprint

from dotenv import load_dotenv

from app.services.ai.yandex_gpt_service import (
    YandexGPTService,
)

load_dotenv(".env")

service = YandexGPTService()

result = service.extract_intent(
    (
        "найди baxi eco 4s 24 "
        "у поставщиков "
        "скидка 5 "
        "до сотен "
        "для клиента"
    )
)

pprint(result)
