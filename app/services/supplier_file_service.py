"""Supplier price file storage service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SUPPLIER_INBOX_DIR = Path("data/supplier_prices/inbox")
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


@dataclass(frozen=True)
class SavedSupplierFile:
    original_filename: str
    saved_path: Path
    supplier_name: str | None


class SupplierFileService:
    def __init__(self, inbox_dir: Path = SUPPLIER_INBOX_DIR) -> None:
        self.inbox_dir = inbox_dir
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def build_save_path(
        self,
        filename: str,
        supplier_name: str | None = None,
    ) -> Path:
        suffix = Path(filename).suffix.lower()

        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {suffix}")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_supplier = _slugify(supplier_name or "unknown_supplier")
        safe_filename = _slugify(Path(filename).stem)
        return self.inbox_dir / f"{timestamp}_{safe_supplier}_{safe_filename}{suffix}"


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-zа-я0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "file"
