from __future__ import annotations

from pdfscan.models import SiteConfig


def test_siteconfig_roundtrip():
    c = SiteConfig(
        seeds=["https://hr.sfsu.edu"],
        scope="subdomain",
        max_depth=3,
        render_js=True,
        include_external_pdfs=True,
    )
    assert SiteConfig.from_json(c.to_json()) == c


def test_siteconfig_ignores_unknown_keys():
    c = SiteConfig.from_json('{"seeds": ["u"], "bogus_future_key": 1}')
    assert c.seeds == ["u"]
    assert c.scope == "host"  # default


def test_siteconfig_defaults():
    c = SiteConfig(seeds=["u"])
    assert c.obey_robots is False
    assert c.include_external_pdfs is False
    assert c.resolvers is None
