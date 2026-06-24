"""Thin :mod:`requests` wrappers used by resolvers and downloaders."""

from __future__ import annotations

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pdfscan.utils.logging import get_logger

_log = get_logger("pdfscan.http")

DEFAULT_USER_AGENT = "pdfscan/0.1"


def build_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    """Return a :class:`requests.Session` with a small retry policy and a UA header."""
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": user_agent})
    return session


def _session_or_default(session: requests.Session | None) -> tuple[requests.Session, bool]:
    """Return ``(session, owns)`` -- ``owns`` is True when we created a throwaway session."""
    if session is not None:
        return session, False
    return build_session(), True


def get_text(
    url: str,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> str | None:
    """GET ``url`` and return ``resp.text``; return ``None`` on any error."""
    sess, owns = _session_or_default(session)
    try:
        resp = sess.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as exc:
        _log.warning("get_text failed for %s: %s", url, exc)
        return None
    finally:
        if owns:
            sess.close()


def get_with_ssl_retry(
    url: str,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> bytes | None:
    """GET ``url`` returning bytes.

    On :class:`requests.exceptions.SSLError`, retry once with ``verify=False``
    (suppressing only :class:`urllib3.exceptions.InsecureRequestWarning`). Returns
    ``None`` on other errors.
    """
    sess, owns = _session_or_default(session)
    try:
        try:
            resp = sess.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.SSLError as exc:
            _log.warning("SSL error for %s, retrying without verification: %s", url, exc)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            try:
                resp = sess.get(url, timeout=timeout, verify=False)
                resp.raise_for_status()
                return resp.content
            except requests.exceptions.RequestException as exc2:
                _log.warning("insecure retry failed for %s: %s", url, exc2)
                return None
        except requests.exceptions.RequestException as exc:
            _log.warning("get_with_ssl_retry failed for %s: %s", url, exc)
            return None
    finally:
        if owns:
            sess.close()


def head_status(
    url: str,
    timeout: int = 10,
    session: requests.Session | None = None,
) -> int | None:
    """HEAD ``url`` (following redirects); return the status code or ``None`` on error."""
    sess, owns = _session_or_default(session)
    try:
        resp = sess.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code
    except requests.exceptions.RequestException as exc:
        _log.warning("head_status failed for %s: %s", url, exc)
        return None
    finally:
        if owns:
            sess.close()
