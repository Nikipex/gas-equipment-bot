from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

from app.services.catalog_snapshot_service import catalog_snapshot_service

rows = catalog_snapshot_service.build_snapshot()
print(f"Catalog snapshot refreshed: rows={rows}")
