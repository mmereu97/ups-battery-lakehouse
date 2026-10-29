import scrapy


class ProductItem(scrapy.Item):
    """One raw product observation from one shop at one moment.

    Raw by design (Bronze philosophy): `specs_raw` keeps the shop's own
    label->value pairs untouched; normalization happens later, in Spark.
    """

    record_type = scrapy.Field()   # "product"
    source = scrapy.Field()        # "123accu" | "nkon" | ...
    url = scrapy.Field()
    scraped_at = scrapy.Field()    # ISO timestamp
    title = scrapy.Field()
    brand = scrapy.Field()         # when the shop exposes it; else None
    model = scrapy.Field()
    price_raw = scrapy.Field()     # raw price text, e.g. "€ 18,95"
    price_eur = scrapy.Field()     # parsed float when unambiguous
    availability = scrapy.Field()
    specs_raw = scrapy.Field()     # dict: label -> value, exactly as shown
    compat_breadcrumb = scrapy.Field()  # e.g. ["UPS accu", "APC", "RBC2"]
    replaced_numbers = scrapy.Field()   # list of equivalent part numbers
    datasheet_url = scrapy.Field()


class DeviceCompatItem(scrapy.Item):
    """One edge set of the UPS -> battery compatibility graph.

    A shop device page ("batteries for Tripp-Lite Touchmaster 420") links to
    the batteries that fit that device. Hundreds of device pages point to the
    same few hundred batteries, so these edges are emitted from the listing
    pages themselves — the product rows alone cannot carry a many-to-many
    mapping.
    """

    record_type = scrapy.Field()   # "device_compat"
    source = scrapy.Field()
    url = scrapy.Field()           # the device page
    scraped_at = scrapy.Field()
    device_title = scrapy.Field()  # e.g. "Tripp-Lite Touchmaster 420"
    device_breadcrumb = scrapy.Field()
    product_urls = scrapy.Field()  # battery product pages linked from it
