from __future__ import annotations

from pdfscan.models import SiteConfig
from pdfscan.utils.urls import (
    ensure_scheme,
    host_of,
    in_scope,
    is_pdf_url,
    normalize_url,
    registrable_domain,
    seed_hosts_from,
)


# --- ensure_scheme ------------------------------------------------------------
def test_ensure_scheme_adds_https_to_bare_host():
    assert ensure_scheme("dprc.sfsu.edu") == "https://dprc.sfsu.edu"
    assert ensure_scheme("dprc.sfsu.edu/path") == "https://dprc.sfsu.edu/path"


def test_ensure_scheme_preserves_existing_scheme():
    assert ensure_scheme("http://dprc.sfsu.edu") == "http://dprc.sfsu.edu"
    assert ensure_scheme("https://dprc.sfsu.edu/a") == "https://dprc.sfsu.edu/a"


def test_ensure_scheme_scheme_relative_and_blank():
    assert ensure_scheme("//dprc.sfsu.edu") == "https://dprc.sfsu.edu"
    assert ensure_scheme("  dprc.sfsu.edu  ") == "https://dprc.sfsu.edu"
    assert ensure_scheme("") == ""
    assert ensure_scheme("   ") == ""


def test_ensure_scheme_makes_host_parseable():
    # The original bug: host_of can't parse a scheme-less seed, yielding "".
    assert host_of("dprc.sfsu.edu") == ""
    assert host_of(ensure_scheme("dprc.sfsu.edu")) == "dprc.sfsu.edu"


# --- is_pdf_url ---------------------------------------------------------------
def test_is_pdf_url_plain():
    assert is_pdf_url("https://access.sfsu.edu/docs/a.pdf") is True


def test_is_pdf_url_with_query():
    assert is_pdf_url("https://access.sfsu.edu/docs/a.pdf?download=1") is True


def test_is_pdf_url_uppercase_extension():
    assert is_pdf_url("https://access.sfsu.edu/docs/A.PDF") is True


def test_is_pdf_url_non_pdf():
    assert is_pdf_url("https://access.sfsu.edu/docs/a.html") is False
    assert is_pdf_url("https://access.sfsu.edu/pdf/") is False


# --- host_of ------------------------------------------------------------------
def test_host_of():
    assert host_of("https://Access.SFSU.edu/x") == "access.sfsu.edu"
    assert host_of("https://access.sfsu.edu:8443/x") == "access.sfsu.edu"
    assert host_of("not a url") == ""


# --- registrable_domain -------------------------------------------------------
def test_registrable_domain_from_url():
    assert registrable_domain("https://hr.sfsu.edu/x") == "sfsu.edu"


def test_registrable_domain_from_host():
    assert registrable_domain("news.access.sfsu.edu") == "sfsu.edu"


# --- normalize_url ------------------------------------------------------------
def test_normalize_url_strips_fragment_keeps_query_and_path_case():
    out = normalize_url("HTTPS://Access.SFSU.edu/Docs/A.pdf?q=1#frag")
    assert out == "https://access.sfsu.edu/Docs/A.pdf?q=1"


# --- in_scope -----------------------------------------------------------------
SEEDS = ["access.sfsu.edu"]


def test_in_scope_host():
    assert in_scope("https://access.sfsu.edu/a", scope="host", seed_hosts=SEEDS) is True
    assert in_scope("https://hr.sfsu.edu/a", scope="host", seed_hosts=SEEDS) is False
    assert in_scope("https://news.sfsu.edu/a", scope="host", seed_hosts=SEEDS) is False


def test_in_scope_subdomain():
    assert in_scope("https://sub.access.sfsu.edu/a", scope="subdomain", seed_hosts=SEEDS) is True
    assert in_scope("https://access.sfsu.edu/a", scope="subdomain", seed_hosts=SEEDS) is True
    assert in_scope("https://hr.sfsu.edu/a", scope="subdomain", seed_hosts=SEEDS) is False


def test_in_scope_domain():
    assert in_scope("https://hr.sfsu.edu/a", scope="domain", seed_hosts=SEEDS) is True
    assert in_scope("https://example.com/a", scope="domain", seed_hosts=SEEDS) is False


def test_in_scope_path():
    assert (
        in_scope(
            "https://access.sfsu.edu/docs/a.pdf",
            scope="path",
            seed_hosts=SEEDS,
            path_prefix="/docs/",
        )
        is True
    )
    assert (
        in_scope(
            "https://access.sfsu.edu/other/a.pdf",
            scope="path",
            seed_hosts=SEEDS,
            path_prefix="/docs/",
        )
        is False
    )
    # path scope still requires the host to match
    assert (
        in_scope(
            "https://hr.sfsu.edu/docs/a.pdf",
            scope="path",
            seed_hosts=SEEDS,
            path_prefix="/docs/",
        )
        is False
    )


def test_in_scope_unknown_scope_treated_as_host():
    assert in_scope("https://access.sfsu.edu/a", scope="bogus", seed_hosts=SEEDS) is True
    assert in_scope("https://hr.sfsu.edu/a", scope="bogus", seed_hosts=SEEDS) is False


# --- seed_hosts_from ----------------------------------------------------------
def test_seed_hosts_from_seeds():
    cfg = SiteConfig(seeds=["https://access.sfsu.edu/x"])
    assert seed_hosts_from(cfg) == ["access.sfsu.edu"]


def test_seed_hosts_from_allowed_hosts_precedence_and_dedup():
    cfg = SiteConfig(
        seeds=["https://access.sfsu.edu/x"],
        allowed_hosts=["HR.sfsu.edu", "hr.sfsu.edu", "news.sfsu.edu"],
    )
    assert seed_hosts_from(cfg) == ["hr.sfsu.edu", "news.sfsu.edu"]
