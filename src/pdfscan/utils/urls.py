"""Pure URL helpers (no network access)."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import tldextract

from pdfscan.models import SiteConfig

# tldextract instance that does not hit the network for the public-suffix list;
# the bundled snapshot is sufficient for scope decisions.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


def normalize_url(url: str) -> str:
    """Strip the fragment, keep the query; lowercase scheme + host, leave path case intact."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    # netloc may include userinfo/port; lowercasing the host portion is enough for
    # our purposes and keeps any (rare) credentials intact case-wise where possible.
    netloc = parts.netloc.lower()
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


def host_of(url: str) -> str:
    """Return the lowercased hostname (no port); "" if there is none."""
    return (urlsplit(url).hostname or "").lower()


def registrable_domain(url_or_host: str) -> str:
    """Return the registrable ``domain.suffix`` (e.g. ``sfsu.edu``) for a URL or bare host."""
    value = url_or_host
    # Accept either a full URL or a bare host.
    if "://" in value:
        value = host_of(value)
    ext = _EXTRACT(value)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    # Fall back to whatever registered_domain produces (may be "").
    return (ext.registered_domain or "").lower()


def is_pdf_url(url: str) -> bool:
    """True if the URL path (ignoring query/fragment) ends with ``.pdf`` (case-insensitive)."""
    path = urlsplit(url).path
    return path.lower().endswith(".pdf")


def in_scope(
    url: str,
    *,
    scope: str,
    seed_hosts: list[str],
    path_prefix: str | None = None,
) -> bool:
    """Decide whether ``url`` is in crawl scope relative to ``seed_hosts``.

    Scopes:
      - ``host``:      host equals one of the seed hosts exactly.
      - ``subdomain``: host equals a seed host or ends with ``"." + seed_host``.
      - ``domain``:    registrable domain equals that of some seed host.
      - ``path``:      same as ``host`` AND path starts with ``path_prefix`` (if given).
    Unknown scopes are treated as ``host``.
    """
    host = host_of(url)
    hosts = [h.lower() for h in seed_hosts]

    if scope == "subdomain":
        return any(host == seed or host.endswith("." + seed) for seed in hosts)

    if scope == "domain":
        target = registrable_domain(url)
        return bool(target) and any(target == registrable_domain(seed) for seed in hosts)

    if scope == "path":
        if host not in hosts:
            return False
        if path_prefix is None:
            return True
        return urlsplit(url).path.startswith(path_prefix)

    # "host" and any unknown scope.
    return host in hosts


def seed_hosts_from(config: SiteConfig) -> list[str]:
    """Hosts from ``config.allowed_hosts`` if set, else parsed from ``config.seeds``.

    Returns lowercased, de-duplicated host names (insertion order preserved).
    """
    raw = config.allowed_hosts if config.allowed_hosts else config.seeds
    hosts: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        host = host_of(entry) if "://" in entry else entry.lower()
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    return hosts
