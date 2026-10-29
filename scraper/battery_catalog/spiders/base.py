"""Shared parsing helpers for shop spiders.

We cannot rely on one brittle CSS class per shop, so spec extraction tries
strategies in order and logs which one fired:
  1. JSON-LD Product blocks (schema.org) — best when present
  2. <table> rows (th/td or td/td pairs)
  3. <dl> definition lists (dt/dd pairs)
  4. "Label: value" lines in text blocks (regex fallback)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import scrapy


LABEL_VALUE_RE = re.compile(r"^\s*([A-Za-zÀ-ž0-9 ().&/+'-]{2,40}?)\s*:\s*(.+?)\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(text: str | None) -> str | None:
    if text is None:
        return None
    t = re.sub(r"\s+", " ", text).strip()
    return t or None


def parse_price_eur(text: str | None) -> float | None:
    """'€ 18,95' / '€14.45' / '18,95 EUR' -> 18.95 (None when ambiguous)."""
    if not text:
        return None
    m = re.search(r"(\d{1,4})[.,](\d{2})(?!\d)", text)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


class ShopSpider(scrapy.Spider):
    """Base: takes -a start_url=<category url>, paginates, parses products.

    Subclasses define `product_link_re` (regex on hrefs that are product
    pages) and may override parse_product extras.
    """

    product_link_re: str = ""
    # sub-category/brand pages to descend into (e.g. brand hubs under "UPS accu")
    category_link_re: str = ""
    max_products: int | None = None  # set via -a limit=10 for test runs

    def __init__(self, start_url=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not start_url:
            raise ValueError(
                f"Usage: scrapy crawl {self.name} -a start_url=<category URL> [-a limit=10]"
            )
        self.start_urls = [start_url]
        self.max_products = int(limit) if limit else None
        self._seen = 0

    def _done(self) -> bool:
        return self.max_products is not None and self._seen >= self.max_products

    # ---------- listing pages ----------

    def parse(self, response):
        hrefs = [h for h in response.css("a::attr(href)").getall() if h]

        product_links = {
            response.urljoin(h) for h in hrefs if re.search(self.product_link_re, h)
        }
        category_links = (
            {
                response.urljoin(h)
                for h in hrefs
                if re.search(self.category_link_re, h)
                and not re.search(self.product_link_re, h)
            }
            if self.category_link_re
            else set()
        )
        self.logger.info(
            "Listing %s -> %d product links, %d sub-category links",
            response.url, len(product_links), len(category_links),
        )
        if not product_links and not category_links:
            sample = ", ".join(sorted(hrefs)[:15])
            self.logger.warning("No links matched on %s. Sample hrefs: %s", response.url, sample)

        # hook: let subclasses emit data found on listing pages themselves
        # (e.g. device -> compatible-battery edges)
        yield from self.parse_listing_extras(response, sorted(product_links))

        for url in sorted(product_links):
            if self._done():
                return
            self._seen += 1
            yield response.follow(url, callback=self.parse_product)

        # descend into sub-categories (Scrapy dedups already-visited URLs)
        for url in sorted(category_links):
            if self._done():
                return
            yield response.follow(url, callback=self.parse)

        # generic pagination: rel=next, or link text that means "next"
        next_url = response.css('a[rel="next"]::attr(href)').get()
        if not next_url:
            for a in response.css("a"):
                text = clean(" ".join(a.css("::text").getall())) or ""
                if text.lower() in {"volgende", "next", "»", ">", "volgende »"}:
                    next_url = a.attrib.get("href")
                    break
        if next_url and not self._done():
            yield response.follow(next_url, callback=self.parse)

    # ---------- spec extraction strategies ----------

    def extract_specs(self, response) -> tuple[dict, str]:
        for strategy, fn in (
            ("jsonld", self._specs_from_jsonld),
            ("table", self._specs_from_tables),
            ("dl", self._specs_from_dl),
            ("lines", self._specs_from_lines),
        ):
            specs = fn(response)
            if specs:
                return specs, strategy
        return {}, "none"

    def _specs_from_jsonld(self, response) -> dict:
        for raw in response.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if isinstance(node, dict) and node.get("@type") == "Product":
                    specs = {
                        k: str(v)
                        for k, v in node.items()
                        if isinstance(v, (str, int, float)) and not k.startswith("@")
                    }
                    props = node.get("additionalProperty") or []
                    for p in props:
                        if isinstance(p, dict) and p.get("name"):
                            specs[str(p["name"])] = str(p.get("value", ""))
                    if specs:
                        return specs
        return {}

    def _specs_from_tables(self, response) -> dict:
        specs: dict = {}
        for row in response.css("table tr"):
            cells = [clean(" ".join(c.css("::text").getall())) for c in row.css("th, td")]
            cells = [c for c in cells if c]
            if len(cells) == 2 and len(cells[0]) <= 40:
                specs[cells[0].rstrip(":")] = cells[1]
        return specs if len(specs) >= 3 else {}

    def _specs_from_dl(self, response) -> dict:
        specs: dict = {}
        for dl in response.css("dl"):
            dts = [clean(" ".join(dt.css("::text").getall())) for dt in dl.css("dt")]
            dds = [clean(" ".join(dd.css("::text").getall())) for dd in dl.css("dd")]
            for k, v in zip(dts, dds):
                if k and v:
                    specs[k.rstrip(":")] = v
        return specs if len(specs) >= 3 else {}

    def _specs_from_lines(self, response) -> dict:
        specs: dict = {}
        for raw_line in response.css("body ::text").getall():
            line = clean(raw_line)
            if not line:
                continue
            m = LABEL_VALUE_RE.match(line)
            if m:
                k, v = m.group(1).rstrip(":"), m.group(2)
                if len(v) <= 80 and k not in specs:
                    specs[k] = v
        return specs if len(specs) >= 4 else {}

    def parse_listing_extras(self, response, product_links):
        """Override to yield items derived from a listing page itself."""
        return
        yield  # pragma: no cover — makes this a generator

    # ---------- misc shared helpers ----------

    def breadcrumb(self, response) -> list[str]:
        for sel in ('[class*="breadcrumb"] a::text', "nav a::text"):
            crumbs = [clean(t) for t in response.css(sel).getall()]
            crumbs = [c for c in crumbs if c and c.lower() not in {"home", "homepage"}]
            if crumbs:
                return crumbs[:6]
        return []
