"""Stock snapshot ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockSnapshot(Base):
    """Point-in-time stock level for a product at a warehouse."""

    __tablename__ = "stock_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    warehouse: Mapped[str] = mapped_column(String(200), default="main")
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    snapshot_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<StockSnapshot product={self.product_id} qty={self.quantity}>"
