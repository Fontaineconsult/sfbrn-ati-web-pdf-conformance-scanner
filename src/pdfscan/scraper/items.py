from __future__ import annotations

import scrapy


class PdfItem(scrapy.Item):
    """A discovered PDF, or a resolver link to be resolved into PDF URLs."""

    pdf_url = scrapy.Field()  # set for direct PDFs
    html_url = scrapy.Field()  # set for resolver links (needs_resolution=True)
    parent_url = scrapy.Field()
    needs_resolution = scrapy.Field()
    offsite = scrapy.Field()
    via_resolver = scrapy.Field()
    filename = scrapy.Field()
