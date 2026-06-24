from __future__ import annotations

from pdfscan.resolvers import BoxResolver, ResolverResult, default_registry

# Realistic Box share page: the page embeds a `Box.postStreamData = {...};` blob whose
# `items` array describes the shared file(s). Field names mirror what the original
# box_handler.py parses: extension, canDownload, name.
FIXTURE_HTML = """
<html><head>
<script type="text/javascript">
  window.Box = window.Box || {};
  Box.postStreamData = {
    "/app-api/enduserapp/shared-item": {
      "currentFolderName": "Shared",
      "items": [{
        "typedID": "f_123456789",
        "name": "Annual Report 2025.pdf",
        "extension": "pdf",
        "size": 204800,
        "canDownload": true,
        "isDownloadable": true
      }]
    }
  };
</script>
</head><body></body></html>
"""

NON_DOWNLOADABLE_HTML = """
<html><head>
<script>
  Box.postStreamData = {
    "x": { "items": [{ "name": "Locked.pdf", "extension": "pdf", "canDownload": false }] }
  };
</script>
</head><body></body></html>
"""


# --- matches ------------------------------------------------------------------
def test_matches_sfsu_tenant():
    assert BoxResolver().matches("https://sfsu.box.com/s/abc123") is True


def test_matches_other_tenant():
    assert BoxResolver().matches("https://university.box.com/s/xyz") is True


def test_matches_non_box():
    assert BoxResolver().matches("https://example.com/x") is False


# --- resolve ------------------------------------------------------------------
def test_resolve_with_html_fixture():
    url = "https://sfsu.box.com/s/abc123"
    result = BoxResolver().resolve(url, html=FIXTURE_HTML)
    assert isinstance(result, ResolverResult)
    assert result.error is None
    assert result.pdf_urls == ["https://sfsu.app.box.com/public/static/abc123.pdf"]
    assert result.filename == "Annual Report 2025.pdf"


def test_resolve_derives_tenant_from_host():
    url = "https://university.box.com/s/xyz"
    result = BoxResolver().resolve(url, html=FIXTURE_HTML)
    assert result.pdf_urls == ["https://university.app.box.com/public/static/xyz.pdf"]


def test_resolve_no_blob_returns_error():
    result = BoxResolver().resolve("https://sfsu.box.com/s/abc123", html="<html>nothing</html>")
    assert result.pdf_urls == []
    assert result.error is not None


def test_resolve_not_downloadable_returns_error():
    result = BoxResolver().resolve(
        "https://sfsu.box.com/s/abc123", html=NON_DOWNLOADABLE_HTML
    )
    assert result.pdf_urls == []
    assert result.error is not None


def test_resolve_non_box_url_returns_error_without_network():
    # html provided so no network is attempted; non-box URL should error.
    result = BoxResolver().resolve("https://example.com/x", html=FIXTURE_HTML)
    assert result.pdf_urls == []
    assert result.error is not None


# --- registry -----------------------------------------------------------------
def test_registry_matches_box():
    resolver = default_registry(["box"]).match("https://sfsu.box.com/s/abc")
    assert isinstance(resolver, BoxResolver)


def test_registry_no_match_for_non_box():
    assert default_registry().match("https://example.com/x") is None


def test_registry_resolve_no_resolver():
    result = default_registry().resolve("https://example.com/x", html="<html></html>")
    assert result.pdf_urls == []
    assert result.error == "no resolver"
