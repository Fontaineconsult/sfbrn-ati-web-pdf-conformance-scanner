"""Box.com share-link resolver.

Ported and generalized from the original ``box_handler.py``: a Box share page
(``https://<tenant>.box.com/s/<hash>``) embeds a ``Box.postStreamData = {...};``
JSON blob describing the shared item(s). This resolver locates that blob, finds a
downloadable PDF item, and builds the static download URL

    https://<tenant>.app.box.com/public/static/<share_hash>.pdf

where ``<tenant>`` is the subdomain of the share URL host (no longer hardcoded to
``sfsu``) and ``<share_hash>`` is the ``/s/<hash>`` token.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from pdfscan.resolvers.base import ResolverResult
from pdfscan.utils import http
from pdfscan.utils.logging import get_logger

_log = get_logger("pdfscan.resolvers.box")

# https://<tenant>.box.com/s/<hash>  (tenant = any subdomain label, e.g. sfsu, university)
_SHARE_RE = re.compile(r"^https?://([a-zA-Z0-9.-]+)\.box\.com/s/([a-zA-Z0-9]+)", re.IGNORECASE)

# Locate the Box.postStreamData assignment and pull the embedded items array.
_POSTSTREAM_RE = re.compile(r"Box\.postStreamData")
_ITEMS_RE = re.compile(r'"items":\s*\[\{.*\}\]', re.DOTALL)


class BoxResolver:
    """Resolve a Box.com share link to its direct static PDF download URL."""

    name = "box"

    def matches(self, url: str) -> bool:
        return bool(_SHARE_RE.match(url or ""))

    def resolve(self, url: str, html: str | None = None) -> ResolverResult:
        match = _SHARE_RE.match(url or "")
        if not match:
            return ResolverResult([], error="not a box share url")

        tenant = match.group(1).split(".")[0]
        share_hash = match.group(2)

        if html is None:
            html = http.get_text(url)
            if html is None:
                return ResolverResult([], error="could not fetch box page")

        try:
            item = self._find_pdf_item(html)
        except Exception as exc:  # never raise out of resolve()
            _log.warning("box parse error for %s: %s", url, exc)
            return ResolverResult([], error=f"box parse error: {exc}")

        if item is None:
            return ResolverResult([], error="no downloadable pdf item found")

        if item.get("canDownload") is False:
            return ResolverResult([], error="box file is not downloadable")

        download_url = f"https://{tenant}.app.box.com/public/static/{share_hash}.pdf"
        return ResolverResult(pdf_urls=[download_url], filename=item.get("name"))

    @staticmethod
    def _find_pdf_item(html: str) -> dict | None:
        """Parse the embedded ``Box.postStreamData`` blob and return the first PDF item.

        Isolated so any change to the Box page structure yields ``None`` (-> error
        result) rather than propagating an exception.
        """
        soup = BeautifulSoup(html, "lxml")
        for script in soup.find_all("script"):
            text = script.string or script.text or ""
            if not _POSTSTREAM_RE.search(text):
                continue

            # The original handler strips single quotes before regex-extracting the
            # items array, then wraps it in braces to form a valid JSON object.
            clean = text.replace("'", "")
            items_match = _ITEMS_RE.search(clean)
            if not items_match:
                continue

            raw = "{" + items_match.group() + "}"
            data = json.loads(raw)
            for item in data.get("items", []):
                if isinstance(item, dict) and str(item.get("extension", "")).lower() == "pdf":
                    return item
        return None
