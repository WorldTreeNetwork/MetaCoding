"""Oracle preflight probe (MetaCoding-9h5.28) — hermetic, no Docker, no network.

The probe's whole job is to distinguish three states fast: nothing serving,
serving-but-not-installed, and usable. Each is asserted below through an injected
opener, so these tests run identically on a machine with no oracle at all.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from ctkr.oracle.health import OracleDown, probe, require_oracle

BASE = "http://localhost:8095"


class _Resp:
    def __init__(self, status: int = 200, body: str = "") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _opener(handler):
    """Build an injectable opener; `handler` maps (method, url) -> _Resp."""

    def _open(req, timeout=None):  # noqa: ARG001 - timeout asserted separately
        return handler(req.get_method(), req.full_url)

    return _open


def _token_body() -> str:
    return json.dumps({"access_token": "tok", "token_type": "Bearer"})


def test_usable_oracle_passes_both_probes() -> None:
    def handler(method, url):
        if url.endswith("/api"):
            return _Resp(200, "{}")
        return _Resp(200, _token_body())

    health = probe(BASE, opener=_opener(handler))
    assert health.usable
    assert health.reachable and health.authenticated


def test_nothing_serving_is_unreachable_not_a_hang() -> None:
    def handler(method, url):
        raise OSError("Connection refused")

    health = probe(BASE, opener=_opener(handler))
    assert not health.reachable
    assert not health.usable
    assert "unreachable" in health.detail


def test_container_up_but_site_not_installed_is_reachable_but_unusable() -> None:
    """The dangerous middle state: HTTP answers, but the oracle cannot be used."""

    def handler(method, url):
        if url.endswith("/api"):
            return _Resp(200, "{}")
        raise OSError("404 Not Found")

    health = probe(BASE, opener=_opener(handler))
    assert health.reachable
    assert not health.authenticated
    assert not health.usable


def test_token_response_without_access_token_is_unusable() -> None:
    def handler(method, url):
        if url.endswith("/api"):
            return _Resp(200, "{}")
        return _Resp(200, json.dumps({"error": "invalid_grant"}))

    health = probe(BASE, opener=_opener(handler))
    assert not health.usable
    assert "access_token" in health.detail


def test_require_oracle_raises_with_the_remedy_and_the_no_intuition_rule() -> None:
    def handler(method, url):
        raise OSError("Connection refused")

    with pytest.raises(OracleDown) as excinfo:
        require_oracle(BASE, opener=_opener(handler))
    message = str(excinfo.value)
    assert "ORACLE NOT ANSWERING" in message
    assert "Do NOT run bring-up.sh" in message
    # the fallback discipline must travel with the failure, not live only in a doc
    assert "never a value claim" in message


def test_probe_passes_a_timeout_to_every_request() -> None:
    """The 29s-hang regression: no probe may inherit urllib's no-timeout default."""
    seen: list[float | None] = []

    def _open(req, timeout=None):
        seen.append(timeout)
        if req.full_url.endswith("/api"):
            return _Resp(200, "{}")
        return _Resp(200, _token_body())

    probe(BASE, timeout=1.5, opener=_open)
    assert seen == [1.5, 1.5]


def test_require_oracle_returns_health_when_usable() -> None:
    def handler(method, url):
        if url.endswith("/api"):
            return _Resp(200, "{}")
        return _Resp(200, _token_body())

    health = require_oracle(BASE, opener=_opener(handler))
    assert health.usable
    assert health.base_url == BASE
