"""Spider for nkon.nl (SLA/UPS section) — intentionally the 'messy' source.

Voltage/capacity live only in the title ("Ultracell UL7-12 12V 7Ah Lead acid"),
dimensions come with tolerances ("151 mm +/- 2mm"), weight as "~2.05 kg".
We keep all of it RAW here; Spark normalizes later — that contrast is the
point of having a second shop.

Run:
    scrapy crawl nkon -a start_url="<SLA category URL>" -a limit=10
"""

from battery_catalog.items import ProductItem

from .base import ShopSpider, clean, now_iso, parse_price_eur


class NkonSpider(ShopSpider):
    name = "nkon"
    allowed_domains = ["nkon.nl"]
    # Magento-style product URLs end with .html and have no query string
    product_link_re = r"nkon\.nl/(?:en/)?[a-z0-9-]+\.html$"

    def parse_product(self, response):
        # listing pages also match .html — treat pages without an h1 price as listings
        specs, strategy = self.extract_specs(response)
        title = clean(response.css("h1::text").get())
        if not title:
            yield from self.parse(response)
            return
        self.logger.info("specs via %-6s (%d fields) %s", strategy, len(specs), response.url)

        price_raw = clean(" ".join(response.css('[class*="price"] ::text').getall())[:120])

        yield ProductItem(
            source=self.name,
            url=response.url,
            scraped_at=now_iso(),
            title=title,
            brand=None,                      # only in title -> normalized in Spark
            model=specs.get("Model number") or specs.get("Modelnummer"),
            price_raw=price_raw,
            price_eur=parse_price_eur(price_raw),
            availability=clean(
                response.xpath(
                    "//*[contains(text(),'In stock') or contains(text(),'Op voorraad')]/text()"
                ).get()
            ),
            specs_raw=specs,
            compat_breadcrumb=self.breadcrumb(response),
            replaced_numbers=None,
            datasheet_url=None,
        )
