"""ORM models package.

Import all models here so that ``Base.metadata`` discovers them
when Alembic autogenerates migrations.
"""

from app.db.models.bot_user import BotUser  # noqa: F401
from app.db.models.product import Product  # noqa: F401
from app.db.models.stock_snapshot import StockSnapshot  # noqa: F401
from app.db.models.supplier_price import SupplierPrice  # noqa: F401
