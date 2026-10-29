"""Scrapy settings — deliberately polite.

One request at a time, 3+ seconds between requests, AutoThrottle on top,
robots.txt always respected, and an honest User-Agent. A catalogue crawl of a
few hundred products takes ~30-60 minutes this way, which is fine: we run it
rarely and cache everything.
"""

BOT_NAME = "battery_catalog"

SPIDER_MODULES = ["battery_catalog.spiders"]
NEWSPIDER_MODULE = "battery_catalog.spiders"

# Honest identification (personal, non-commercial data-engineering project).
USER_AGENT = "battery-catalog-research/0.1 (personal portfolio project; contact: mmereu97 on GitHub)"

ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS = 1
DOWNLOAD_DELAY = 7.0            # base delay; raised after the site served
                                # 403s at 3s — we back off, not push harder
DOWNLOAD_DELAY_JITTER = 0.5     # ±50% random variation

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

RETRY_ENABLED = True
RETRY_TIMES = 2

HTTPCACHE_ENABLED = True       # local cache: re-runs don't re-hit the site
HTTPCACHE_EXPIRATION_SECS = 60 * 60 * 24 * 7
HTTPCACHE_DIR = "httpcache"
# Don't replay cached error responses: pages that returned 403/429/503 get
# retried (politely) on the next run instead of being treated as permanent.
HTTPCACHE_IGNORE_HTTP_CODES = [403, 429, 500, 503]

ITEM_PIPELINES = {
    "battery_catalog.pipelines.JsonlExportPipeline": 300,
}

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
