"""Oracle health preflight — fail fast, never hang (bead MetaCoding-9h5.28).

WHY THIS EXISTS. During the wave-0 pilot (2026-07-20) the farmOS oracle went down
mid-run. Every call inherited urllib's default behavior — no timeout — so each
attempt hung for ~29s before failing, and the failure surfaced as an opaque socket
error rather than "the oracle is down, here is how to bring it back". A wave that
fans out over 100+ features cannot afford either the wall-clock or the ambiguity.

The contract: **before** any command that needs the live instance does real work,
probe it with a short timeout and, on failure, raise a message that names the cause
and the fix. Two probes, in order of cheapness:

  1. ``/api`` reachable            — is anything serving HTTP at all?
  2. ``POST /oauth/token`` 200     — is the farm profile installed, are the OAuth
                                     keys generated, do the credentials work?

Probe 2 is what distinguishes "container is up" from "oracle is usable": a fresh
``farmos/farmos:4.x`` container answers ``/api`` long before the site is installed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

#: Seconds to wait on a preflight probe. Deliberately short — this is a liveness
#: check, not a workload; a healthy local oracle answers in well under a second.
DEFAULT_TIMEOUT = 5.0

#: How to get the oracle back. Quoted verbatim in the failure message so an agent
#: mid-fan-out does not have to go find the runbook.
REMEDY = (
    "Bring it up with `ctkr/ctkr/oracle/bring-up.sh` (~2 min with images cached), "
    "then confirm with `ctkr oracle-verify ctkr/oracle/data/farmos_core_fixtures.jsonl "
    "--adapter farmos` (must be 7/7)."
)


class OracleDown(RuntimeError):
    """The live oracle is unreachable or unusable. Carries the remedy."""

    def __init__(self, reason: str, base_url: str) -> None:
        super().__init__(
            f"ORACLE DOWN at {base_url}: {reason}\n  {REMEDY}\n"
            "  Do NOT substitute intuited values for observation — a build judged "
            "without the oracle is a conformance claim, never a value claim "
            "(see docs/design/no-oracle-fallback.md)."
        )
        self.reason = reason
        self.base_url = base_url


@dataclass(frozen=True)
class OracleHealth:
    """Outcome of a preflight probe."""

    base_url: str
    reachable: bool
    authenticated: bool
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.reachable and self.authenticated


def probe(
    base_url: str,
    *,
    username: str = "admin",
    password: str = "admin",
    client_id: str = "farm",
    client_secret: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    opener=None,
) -> OracleHealth:
    """Probe the oracle without raising. `opener` is injectable for tests."""
    base = base_url.rstrip("/")
    _open = opener or urllib.request.urlopen

    try:
        req = urllib.request.Request(base + "/api", method="GET")
        req.add_header("Accept", "application/vnd.api+json")
        with _open(req, timeout=timeout) as resp:
            if resp.status >= 500:
                return OracleHealth(base, False, False, f"/api -> {resp.status}")
    except Exception as exc:  # noqa: BLE001 - any transport failure means down
        return OracleHealth(base, False, False, f"/api unreachable: {exc}")

    form = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
    }
    if client_secret:
        form["client_secret"] = client_secret
    try:
        req = urllib.request.Request(
            base + "/oauth/token",
            data=urllib.parse.urlencode(form).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with _open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode() or "{}")
        if not payload.get("access_token"):
            return OracleHealth(base, True, False, "token response carried no access_token")
    except Exception as exc:  # noqa: BLE001
        return OracleHealth(
            base, True, False,
            f"OAuth token request failed ({exc}) — site installed? keys generated?",
        )

    return OracleHealth(base, True, True, "ok")


def require_oracle(base_url: str, **kw) -> OracleHealth:
    """Preflight gate: probe and raise :class:`OracleDown` unless usable."""
    health = probe(base_url, **kw)
    if not health.usable:
        raise OracleDown(health.detail, health.base_url)
    return health
