"""Watch supplier inbox and auto-ingest new price files."""

from __future__ import annotations

import time
import shutil
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.services.supplier_cache_service import SupplierCacheService
from app.services.supplier_parser_service import SupplierParserService
from scripts.rebuild_enriched_supplier_products import main as rebuild_enriched_supplier_products


INBOX_DIR = Path("data/supplier_prices/inbox")
PROCESSED_MARKER_DIR = Path("data/supplier_prices/.processed_markers")
ARCHIVE_DIR = Path("data/supplier_prices/_archive")
SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


@dataclass(frozen=True)
class IngestResult:
    file_path: Path
    saved_count: int
    parsed_rows: int
    supplier_key: str
    supplier_name: str


class SupplierInboxWatcher:
    def __init__(
        self,
        inbox_dir: Path = INBOX_DIR,
        marker_dir: Path = PROCESSED_MARKER_DIR,
    ) -> None:
        self.inbox_dir = inbox_dir
        self.marker_dir = marker_dir
        self.parser = SupplierParserService()
        self.cache = SupplierCacheService()

        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.marker_dir.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> list[IngestResult]:
        results: list[IngestResult] = []

        files = _latest_supplier_files(
            [
                file_path
                for file_path in sorted(self.inbox_dir.iterdir())
                if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
            ]
        )

        for file_path in files:
            if not file_path.is_file():
                continue

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            if self._is_processed(file_path):
                continue

            try:
                result = self._ingest_file(file_path)
                results.append(result)
                self._mark_processed(file_path)
                logger.info(
                    "Supplier file ingested: file={} supplier_key={} parsed={} saved={}",
                    file_path,
                    result.supplier_key,
                    result.parsed_rows,
                    result.saved_count,
                )

                try:
                    rebuild_enriched_supplier_products()
                    logger.info("Enriched supplier products rebuilt")
                except Exception as exc:
                    logger.exception("Failed to rebuild enriched supplier products: {}", exc)
            except Exception as exc:
                logger.exception("Supplier file ingest failed: file={} error={}", file_path, exc)

        return results

    def watch(self, interval_seconds: int = 10) -> None:
        logger.info("Supplier inbox watcher started: {}", self.inbox_dir)

        while True:
            self.run_once()
            time.sleep(interval_seconds)

    def _ingest_file(self, file_path: Path) -> IngestResult:
        parse_result = self.parser.parse_file(file_path, limit=100_000)
        saved_count = self.cache.save_parse_result(parse_result)

        return IngestResult(
            file_path=file_path,
            saved_count=saved_count,
            parsed_rows=parse_result.parsed_rows,
            supplier_key=parse_result.supplier_key,
            supplier_name=parse_result.supplier_name,
        )

    def _marker_path(self, file_path: Path) -> Path:
        stat = file_path.stat()
        marker_name = f"{file_path.name}.{stat.st_size}.{int(stat.st_mtime)}.done"
        return self.marker_dir / marker_name

    def _is_processed(self, file_path: Path) -> bool:
        return self._marker_path(file_path).exists()

    def _mark_processed(self, file_path: Path) -> None:
        self._marker_path(file_path).write_text("processed\n")



def _latest_supplier_files(files: list[Path]) -> list[Path]:
    """Keep latest file per supplier group.

    Важно:
    - нельзя выбирать только самый новый date-marker глобально;
    - Юлас 18_05 и большой прайс 25_05 должны жить вместе;
    - старые версии одного и того же поставщика можно архивировать.
    """
    if not files:
        return []

    grouped: dict[str, list[Path]] = defaultdict(list)

    for file_path in files:
        grouped[_supplier_group_key(file_path)].append(file_path)

    keep: list[Path] = []

    for _, group_files in grouped.items():
        latest = max(
            group_files,
            key=lambda path: (
                _extract_price_date_marker(path.name) or "",
                path.stat().st_mtime,
            ),
        )

        keep.append(latest)

        for old_file in group_files:
            if old_file == latest:
                continue

            try:
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                target = ARCHIVE_DIR / old_file.name
                if not target.exists():
                    shutil.move(str(old_file), str(target))
                    logger.info("Archived older supplier price: {} -> {}", old_file, target)
            except Exception as exc:
                logger.warning("Failed to archive old supplier price {}: {}", old_file, exc)

    return sorted(keep)


def _supplier_group_key(file_path: Path) -> str:
    name = file_path.name.lower().replace("ё", "е")

    # Юлас — отдельный поставщик/группа, не должен конкурировать с большим прайсом.
    if "юлас" in name or "yulas" in name:
        return "yulas"

    # Большой общий прайс брендов.
    brand_tokens = [
        "бакси",
        "baxi",
        "иммергаз",
        "immergas",
        "аристон",
        "ariston",
        "дражице",
        "drazice",
        "навьен",
        "navien",
        "термекс",
        "thermex",
        "бош",
        "bosch",
        "эван",
        "evan",
        "дакор",
        "dakor",
    ]

    if any(token in name for token in brand_tokens):
        return "main_brands"

    # fallback: убираем дату/технические хвосты, чтобы версии одного файла группировались.
    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", "", name)
    cleaned = re.sub(r"\d{1,2}_\d{1,2}", "", cleaned)
    cleaned = re.sub(r"\.(xlsx|xls|csv)$", "", cleaned)
    cleaned = re.sub(r"[^a-zа-я0-9]+", "_", cleaned).strip("_")

    return cleaned or "unknown"


def _extract_price_date_marker(name: str) -> str | None:
    match = re.search(r"(\d{1,2})_(\d{1,2})", name)
    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))

    return f"{month:02d}-{day:02d}"


def _archive_file(file_path: Path) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVE_DIR / file_path.name

    if dst.exists():
        file_path.unlink(missing_ok=True)
    else:
        shutil.move(str(file_path), str(dst))


def _price_marker(file_path: Path) -> tuple[int, int] | None:
    """Extract DD_MM marker from filename."""
    match = re.search(r"(?:^|_)(\d{1,2})_(\d{1,2})(?:_|$)", file_path.stem)

    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    return month, day


def _newest_price_marker(files: list[Path]) -> tuple[int, int] | None:
    markers = [marker for f in files if (marker := _price_marker(f)) is not None]
    return max(markers) if markers else None


def _supplier_group_key(file_path: Path) -> str:
    """Build stable key for same supplier price list across dates.

    Examples:
    - 2026-05-15_..._12_05_baxi... -> baxi...
    - 2026-05-20_..._18_05_baxi... -> baxi...
    """
    stem = file_path.stem.lower().replace("ё", "е")
    parts = stem.split("_")

    if len(parts) >= 4:
        tail = parts[3:]
    else:
        tail = parts

    # remove date markers inside supplier names
    cleaned: list[str] = []
    skip_next = False

    for i, part in enumerate(tail):
        if skip_next:
            skip_next = False
            continue

        if part.isdigit() and len(part) <= 2:
            next_part = tail[i + 1] if i + 1 < len(tail) else ""
            if next_part.isdigit() and len(next_part) <= 2:
                skip_next = True
                continue

        cleaned.append(part)

    key = "_".join(x for x in cleaned if x)
    return key or stem
