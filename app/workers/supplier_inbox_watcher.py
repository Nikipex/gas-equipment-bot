"""Watch supplier inbox and auto-ingest new price files."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.services.supplier_cache_service import SupplierCacheService
from app.services.supplier_parser_service import SupplierParserService


INBOX_DIR = Path("data/supplier_prices/inbox")
PROCESSED_MARKER_DIR = Path("data/supplier_prices/.processed_markers")
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

        for file_path in sorted(self.inbox_dir.iterdir()):
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
