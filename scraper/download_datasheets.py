"""Download the datasheet PDFs referenced by crawled products — politely.

Reads every data/raw/<source>/*.jsonl produced by the spiders, collects the
distinct `datasheet_url` values, and downloads each PDF into
data/datasheets/ with a 3+ second pause between requests. Files that are
already present are skipped, so re-runs only fetch what is new — the same
incremental, cache-friendly behaviour as the spiders.

Usage:
    python download_datasheets.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/datasheets")
USER_AGENT = "battery-catalog-research/0.1 (personal portfolio project; contact: mmereu97 on GitHub)"
DELAY_S = 3.0


def collect_urls() -> list[str]:
    urls: set[str] = set()
    for path in RAW_DIR.glob("*/*.jsonl"):
        for line in path.open(encoding="utf-8"):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = item.get("datasheet_url")
            if url and url.lower().endswith(".pdf"):
                urls.add(url)
    return sorted(urls)


def safe_name(url: str) -> str:
    name = Path(urlparse(url).path).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "datasheet.pdf"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    urls = collect_urls()
    if args.limit:
        urls = urls[: args.limit]
    print(f"{len(urls)} distinct datasheet URLs found")

    done = skipped = failed = 0
    for url in urls:
        target = OUT_DIR / safe_name(url)
        if target.exists():
            skipped += 1
            continue
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=30) as resp:
                target.write_bytes(resp.read())
            done += 1
            print(f"ok   {target.name}")
        except Exception as exc:  # noqa: BLE001 — log and move on
            failed += 1
            print(f"FAIL {url} ({exc})")
        time.sleep(DELAY_S + random.uniform(0, 1.5))

    print(f"downloaded={done} skipped(existing)={skipped} failed={failed}")


if __name__ == "__main__":
    main()
