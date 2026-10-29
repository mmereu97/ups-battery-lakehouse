"""Surgically remove error responses (403/429/5xx) from Scrapy's HTTP cache.

The first crawl got rate-limited near the end; those 403 pages were stored
in the cache before HTTPCACHE_IGNORE_HTTP_CODES was configured, so re-runs
keep replaying them. This script deletes ONLY the cached error entries —
the ~2k good pages stay cached — so the next crawl re-fetches just the
blocked pages, politely, and everything else comes from disk.

Usage:
    python purge_cache_errors.py [cache_dir]      # default: httpcache
"""

from __future__ import annotations

import pickle
import shutil
import sys
from pathlib import Path

BAD_STATUSES = {403, 429, 500, 503}


def main() -> None:
    cache_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("httpcache")
    if not cache_dir.exists():
        sys.exit(f"Cache dir not found: {cache_dir.resolve()}")

    purged = kept = broken = 0
    for meta_path in cache_dir.glob("*/*/*/pickled_meta"):
        entry_dir = meta_path.parent
        try:
            meta = pickle.loads(meta_path.read_bytes())
            status = int(meta.get("status", 0))
        except Exception:  # noqa: BLE001 — unreadable entry: drop it too
            shutil.rmtree(entry_dir, ignore_errors=True)
            broken += 1
            continue
        if status in BAD_STATUSES:
            shutil.rmtree(entry_dir, ignore_errors=True)
            purged += 1
        else:
            kept += 1

    print(f"purged={purged} error entries, kept={kept} good pages, broken={broken}")


if __name__ == "__main__":
    main()
