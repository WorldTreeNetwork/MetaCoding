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

#: Seconds to wait on a preflight probe. The 5s default failed a wave-sized
#: fan-out — a measured sweep of concurrent recorders got 12/12 at 90s and 6/12
#: at 5s, every failure the OAuth token under contention. A liveness check that
#: reports CONTENTION as DEATH sends an agent to the remedy below, which is the
#: one action that would actually kill the oracle for its 11 siblings.
DEFAULT_TIMEOUT = 90.0

#: What to do when the oracle does not answer. The oracle is SHARED: the previous
#: text told whoever hit a slow token endpoint to run `bring-up.sh`, i.e. to
#: destroy the instance every concurrent sibling was using. Bringing it up is an
#: operator action, taken once, by a human who knows nobody else is running.
REMEDY = (
    "The oracle is SHARED by every concurrent run. Do NOT run bring-up.sh, "
    "docker, or drush against it — that destroys every sibling's run, and the "
    "usual cause of this message is CONTENTION, not death. First retry with a "
    "longer --preflight-timeout. If it is still silent, STOP and report it: "
    "restarting the shared oracle is an operator decision, not an agent's."
)


class OracleDown(RuntimeError):
    """The live oracle is unreachable or unusable. Carries the remedy."""

    def __init__(self, reason: str, base_url: str) -> None:
        super().__init__(
            f"ORACLE NOT ANSWERING at {base_url}: {reason}\n  {REMEDY}\n"
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
