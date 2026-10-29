"""Export pipeline: one JSONL file per spider per run, timestamped.

Each run lands a new file in data/raw/<source>/ — exactly the layout the
Databricks Volume expects for incremental ingestion with COPY INTO/Auto
Loader (new file = new increment, old files never rewritten).
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class JsonlExportPipeline:
    def open_spider(self, spider):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path("data/raw") / spider.name
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / f"{spider.name}_{stamp}.jsonl"
        self.fh = self.path.open("w", encoding="utf-8")
        self.count = 0

    def close_spider(self, spider):
        self.fh.close()
        spider.logger.info("Wrote %d items to %s", self.count, self.path)

    def process_item(self, item, spider):
        self.fh.write(json.dumps(dict(item), ensure_ascii=False) + "\n")
        self.count += 1
        return item
