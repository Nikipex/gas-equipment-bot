"""Run supplier inbox watcher."""

from __future__ import annotations

import argparse

from app.core.logging import setup_logging
from app.workers.supplier_inbox_watcher import SupplierInboxWatcher


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process inbox once and exit")
    parser.add_argument("--interval", type=int, default=10, help="Watch interval in seconds")
    args = parser.parse_args()

    setup_logging()

    watcher = SupplierInboxWatcher()

    if args.once:
        results = watcher.run_once()
        print(f"Processed files: {len(results)}")
        for result in results:
            print(
                f"- {result.file_path.name}: "
                f"supplier={result.supplier_key}, "
                f"parsed={result.parsed_rows}, "
                f"saved={result.saved_count}"
            )
        return

    watcher.watch(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
