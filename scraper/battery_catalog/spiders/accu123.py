"""Spider for 123accu.nl — structured 'Specificaties' + UPS compatibility tree.

Selectors verified against a saved product page (2026-10-28):
  * specs:      <table class="specifications"> with label/value td pairs,
                two spec pairs per <tr>; the value's title="" attribute holds
                the clean text (e.g. "151 x 65 x 93 mm")
  * OEM list:   <span class="c-product-oem__item"> under "Dit product
                vervangt partnummers" — equivalent part numbers
  * breadcrumb: schema.org BreadcrumbList (device path, e.g.
                UPS accu > APC > ... > RBC2)
  * price:      <dr-price primary-price="€ 18,95" secondary-price="€ 15,66">
                inside .c-product-details-price (incl. / excl. 21% BTW)

Run:
    scrapy crawl accu123 -a start_url="https://www.123accu.nl/UPS-accu-p1089458.html" [-a limit=10]
"""

import re

from battery_catalog.items import DeviceCompatItem, ProductItem

from .base import ShopSpider, clean, now_iso, parse_price_eur


class Accu123Spider(ShopSpider):
    name = "accu123"
    allowed_domains = ["123accu.nl"]
    # product pages look like .../Some-Product-Name-i25434.html
    # (exclude the site's own info pages under /spec-info/)
    product_link_re = r"^(?!.*/spec-info/).*-i\d+\.html?$"
    # descend only into UPS-related sub-pages: brand hubs and device pages
    # live under the /UPS-accu/ path; never follow the site-wide menu
    category_link_re = r"(?i)(/ups-accu/|rbc|accunummer).*-p\d+\.html?$"

    # device pages like /UPS-accu/Tripp-Lite-Touchmaster-420-p1115171.html
    # (brand hubs and "Zoek op ..." index pages are navigation, not devices)
    DEVICE_PAGE_RE = re.compile(r"(?i)/ups-accu/(?!zoek-op)[^/]+-p\d+\.html?$")

    def parse_listing_extras(self, response, product_links):
        if not product_links or not self.DEVICE_PAGE_RE.search(response.url):
            return
        if "zoek-op" in response.url.lower():
            return
        yield DeviceCompatItem(
            record_type="device_compat",
            source=self.name,
            url=response.url,
            scraped_at=now_iso(),
            device_title=clean(response.css("h1::text").get())
            or clean(response.css("title::text").get()),
            device_breadcrumb=[
                c for c in (
                    clean(t)
                    for t in response.css(
                        '[itemtype*="BreadcrumbList"] [itemprop="name"]::text, '
                        '[itemtype*="BreadcrumbList"] a::text'
                    ).getall()
                )
                if c and c.lower() not in {"home", "homepage"}
            ][:8] or None,
            product_urls=product_links,
        )

    def parse_product(self, response):
        # --- specs: label cell + value cell (clean text in title="") ---
        specs: dict = {}
        for row in response.css("table.specifications tr.specification"):
            cells = row.css("td")
            label = None
            for td in cells:
                cls = td.attrib.get("class", "")
                if "label" in cls:
                    label = (clean(" ".join(td.css("::text").getall())) or "").rstrip(":")
                elif "value" in cls and label:
                    value = clean(td.attrib.get("title")) or clean(
                        " ".join(td.css("::text").getall())
                    )
                    if value:
                        specs[label] = value
                    label = None
        strategy = "site"
        if not specs:  # site redesign fallback
            specs, strategy = self.extract_specs(response)
        self.logger.info("specs via %-6s (%d fields) %s", strategy, len(specs), response.url)

        # --- equivalent part numbers ("Dit product vervangt partnummers") ---
        replaced = []
        for t in response.css(
            'span.c-product-oem__item::text, [data-test="product-oem"]::text'
        ).getall():
            v = (clean(t) or "").lstrip("- ").strip()
            if v and 2 <= len(v) <= 40:
                replaced.append(v)

        # --- breadcrumb: the real schema.org one (device path) ---
        crumbs = [
            c for c in (
                clean(t)
                for t in response.css(
                    '[itemtype*="BreadcrumbList"] [itemprop="name"]::text, '
                    '[itemtype*="BreadcrumbList"] a::text'
                ).getall()
            )
            if c and c.lower() not in {"home", "homepage"}
        ]

        # --- price: the product's own dr-price, not related items ---
        price_incl = response.css(
            ".c-product-details-price dr-price::attr(primary-price)"
        ).get() or response.css("dr-price::attr(primary-price)").get()
        price_excl = response.css(
            ".c-product-details-price dr-price::attr(secondary-price)"
        ).get() or response.css("dr-price::attr(secondary-price)").get()

        yield ProductItem(
            record_type="product",
            source=self.name,
            url=response.url,
            scraped_at=now_iso(),
            title=clean(response.css("h1::text").get())
            or clean(response.css("title::text").get()),
            brand=specs.get("Merk"),
            model=specs.get("Model"),
            price_raw=clean(f"{price_incl or ''} | excl: {price_excl or ''}"),
            price_eur=parse_price_eur(price_incl),
            availability=clean(
                response.xpath(
                    "//*[contains(text(),'leverbaar') or contains(text(),'voorraad')"
                    " or contains(text(),'uitverkocht')]/text()"
                ).get()
            ),
            specs_raw=specs,
            compat_breadcrumb=list(dict.fromkeys(crumbs))[:8] or None,
            replaced_numbers=sorted(set(replaced)) or None,
            datasheet_url=next(
                (response.urljoin(h) for h in response.css("a::attr(href)").getall()
                 if h and h.lower().endswith(".pdf")),
                None,
            ),
        )
