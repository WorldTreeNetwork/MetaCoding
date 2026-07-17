"""farmOS JSON:API adapter for the value-equivalence oracle (Phase 2).

Drives a **live** farmOS instance at its JSON:API boundary (``/api``), the same
contract farmOS.py / farmOS.js / the Aggregator all speak — so a fixture that
passes here is asserting against the *published* farmOS behavior, not an
internal Drupal detail. Authentication is OAuth2 password grant against the
default public ``farm`` consumer.

This is the only module in the oracle that knows farmOS's data model. It maps:

* glossary entity → ``asset--{bundle}`` (``land`` needs a ``land_type``; ``group``
  is bare; ``animal`` needs an ``animal_type`` taxonomy term, minted on demand);
* ``record_log`` → ``log--{kind}`` with ``asset`` + ``quantity`` relationships,
  quantities as ``quantity--standard`` resources with a ``taxonomy_term--unit``;
* ``assign_to_group`` → an ``is_group_assignment`` activity log;
* the read side → JSON:API filtered queries (sum quantities, count logs, read the
  latest group-assignment) — the derived VALUES, computed at the boundary.

Handles are encoded ``"{entity_type}:{bundle}:{uuid}"`` so status transitions and
reads can reconstruct the resource path. The runner never inspects them.

No third-party HTTP dependency — stdlib ``urllib`` only (matches ctkr's
dependency hygiene; the test suite mocks the transport, so no Docker in tests).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ctkr.oracle.adapter import AdapterError, Handle, ImplementationAdapter
from ctkr.oracle.fixtures import QuantitySpec

# glossary entity term -> farmOS asset bundle
_ASSET_BUNDLE = {
    "land": "land",
    "animal": "animal",
    "planting": "plant",
    "structure": "structure",
    "equipment": "equipment",
    "group": "group",
}


class FarmOSClient:
    """Minimal JSON:API + OAuth2 transport. Injectable for tests (see _transport)."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        client_id: str = "farm",
        client_secret: str = "",
        transport: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        # `transport` lets tests substitute request handling; None => real HTTP.
        self._transport = transport

    # ---- auth -------------------------------------------------------------- #
    def authenticate(self) -> None:
        form = {
            "grant_type": "password",
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
        }
        if self.client_secret:
            form["client_secret"] = self.client_secret
        body = urllib.parse.urlencode(form).encode()
        try:
            raw = self._raw(
                "POST", "/oauth/token", body,
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            raise AdapterError(
                f"OAuth token request failed: {exc.code} {exc.read().decode()[:200]}"
            ) from exc
        self._token = json.loads(raw)["access_token"]

    # ---- JSON:API ---------------------------------------------------------- #
    def _raw(
        self, method: str, path: str, body: bytes | None, headers: dict[str, str]
    ) -> str:
        if self._transport is not None:
            return self._transport(method, path, body, headers)
        req = urllib.request.Request(  # pragma: no cover - real HTTP
            self.base_url + path, data=body, method=method
        )
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode()

    def request(
        self, method: str, path: str, doc: dict | None = None
    ) -> dict[str, Any]:
        headers = {"Accept": "application/vnd.api+json"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        body = None
        if doc is not None:
            headers["Content-Type"] = "application/vnd.api+json"
            body = json.dumps(doc).encode()
        try:
            raw = self._raw(method, path, body, headers)
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode()[:400]
            raise AdapterError(
                f"{method} {path} -> {exc.code}: {detail}"
            ) from exc
        return json.loads(raw) if raw.strip() else {}


class FarmOSAdapter(ImplementationAdapter):
    """Value-equivalence adapter over a live farmOS JSON:API boundary."""

    name = "farmos"

    def __init__(self, client: FarmOSClient) -> None:
        self.client = client
        self._unit_cache: dict[str, str] = {}  # unit name -> term uuid
        self._type_term_cache: dict[tuple[str, str], str] = {}  # (vocab, name) -> uuid

    # ---- lifecycle --------------------------------------------------------- #
    def open(self) -> None:
        self.client.authenticate()

    # ---- helpers ----------------------------------------------------------- #
    @staticmethod
    def _split(handle: Handle) -> tuple[str, str, str]:
        etype, bundle, uid = handle.split(":", 2)
        return etype, bundle, uid

    def _ensure_term(self, vocab: str, name: str) -> str:
        key = (vocab, name)
        if key in self._type_term_cache:
            return self._type_term_cache[key]
        # try to find an existing term by name
        q = f"/api/taxonomy_term/{vocab}?filter[name]={urllib.parse.quote(name)}"
        found = self.client.request("GET", q)
        data = found.get("data") or []
        if data:
            uid = data[0]["id"]
        else:
            doc = {"data": {"type": f"taxonomy_term--{vocab}",
                            "attributes": {"name": name}}}
            uid = self.client.request(
                "POST", f"/api/taxonomy_term/{vocab}", doc
            )["data"]["id"]
        self._type_term_cache[key] = uid
        return uid

    def _ensure_unit(self, name: str) -> str:
        if name in self._unit_cache:
            return self._unit_cache[name]
        uid = self._ensure_term("unit", name)
        self._unit_cache[name] = uid
        return uid

    def _paged(self, path: str) -> list[dict[str, Any]]:
        """Follow JSON:API pagination, returning all `data` rows (+ track included)."""
        rows: list[dict[str, Any]] = []
        self._last_included: dict[tuple[str, str], dict[str, Any]] = {}
        url = path
        while url:
            doc = self.client.request("GET", url)
            rows.extend(doc.get("data") or [])
            for inc in doc.get("included") or []:
                self._last_included[(inc["type"], inc["id"])] = inc
            nxt = (doc.get("links") or {}).get("next", {})
            href = nxt.get("href") if isinstance(nxt, dict) else None
            url = href.replace(self.client.base_url, "") if href else None
        return rows

    # ---- given / when ------------------------------------------------------ #
    def create_asset(self, entity: str, name: str, descriptor: str = "") -> Handle:
        bundle = _ASSET_BUNDLE.get(entity)
        if bundle is None:
            raise AdapterError(f"farmOS has no asset bundle for entity {entity!r}")
        attrs: dict[str, Any] = {"name": name}
        rels: dict[str, Any] = {}
        if bundle == "land":
            # land_type is a required option; only "other" is guaranteed present
            # on a bare install, so a free descriptor falls back to it.
            attrs["land_type"] = descriptor or "other"
        elif bundle == "structure":
            attrs["structure_type"] = descriptor or "other"
        elif bundle == "animal":
            term = self._ensure_term("animal_type", descriptor or "Animal")
            rels["animal_type"] = {"data": {"type": "taxonomy_term--animal_type",
                                            "id": term}}
        elif bundle == "plant":
            term = self._ensure_term("plant_type", descriptor or "Crop")
            rels["plant_type"] = {"data": {"type": "taxonomy_term--plant_type",
                                           "id": term}}
        doc: dict[str, Any] = {"data": {"type": f"asset--{bundle}", "attributes": attrs}}
        if rels:
            doc["data"]["relationships"] = rels
        uid = self.client.request("POST", f"/api/asset/{bundle}", doc)["data"]["id"]
        return f"asset:{bundle}:{uid}"

    def _create_quantity(self, q: QuantitySpec) -> str:
        num, den = _as_fraction(q.value)
        attrs: dict[str, Any] = {
            "measure": q.measure,
            "value": {"numerator": num, "denominator": den},
        }
        if q.label:
            attrs["label"] = q.label
        rels: dict[str, Any] = {}
        if q.unit:
            unit_id = self._ensure_unit(q.unit)
            rels["units"] = {"data": {"type": "taxonomy_term--unit", "id": unit_id}}
        doc = {"data": {"type": "quantity--standard", "attributes": attrs}}
        if rels:
            doc["data"]["relationships"] = rels
        return self.client.request("POST", "/api/quantity/standard", doc)["data"]["id"]

    def record_log(
        self,
        kind: str,
        name: str,
        status: str,
        asset_handles: list[Handle],
        quantities: list[QuantitySpec],
    ) -> Handle:
        assets = [self._split(h) for h in asset_handles]
        rels: dict[str, Any] = {}
        if assets:
            rels["asset"] = {"data": [
                {"type": f"asset--{b}", "id": u} for _, b, u in assets
            ]}
        if quantities:
            qids = [self._create_quantity(q) for q in quantities]
            rels["quantity"] = {"data": [
                {"type": "quantity--standard", "id": qid} for qid in qids
            ]}
        doc: dict[str, Any] = {
            "data": {
                "type": f"log--{kind}",
                "attributes": {"name": name, "status": status or "done"},
            }
        }
        if rels:
            doc["data"]["relationships"] = rels
        uid = self.client.request("POST", f"/api/log/{kind}", doc)["data"]["id"]
        return f"log:{kind}:{uid}"

    def set_log_status(self, log_handle: Handle, status: str) -> None:
        _, kind, uid = self._split(log_handle)
        doc = {"data": {"type": f"log--{kind}", "id": uid,
                        "attributes": {"status": status}}}
        self.client.request("PATCH", f"/api/log/{kind}/{uid}", doc)

    def assign_to_group(self, asset_handle: Handle, group_handle: Handle) -> None:
        _, abundle, aid = self._split(asset_handle)
        _, _, gid = self._split(group_handle)
        doc = {
            "data": {
                "type": "log--activity",
                "attributes": {
                    "name": "group assignment",
                    "status": "done",
                    "is_group_assignment": True,
                },
                "relationships": {
                    "asset": {"data": [{"type": f"asset--{abundle}", "id": aid}]},
                    "group": {"data": [{"type": "asset--group", "id": gid}]},
                },
            }
        }
        self.client.request("POST", "/api/log/activity", doc)

    def archive_asset(self, asset_handle: Handle) -> None:
        _, bundle, uid = self._split(asset_handle)
        # farmOS marks an asset inactive via the `archived` timestamp.
        doc = {"data": {"type": f"asset--{bundle}", "id": uid,
                        "attributes": {"archived": _now_iso()}}}
        self.client.request("PATCH", f"/api/asset/{bundle}/{uid}", doc)

    # ---- then (reads) ------------------------------------------------------ #
    def asset_yield_total(
        self, asset_handle: Handle, measure: str, unit: str
    ) -> float:
        _, _, aid = self._split(asset_handle)
        total = 0.0
        for kind in ("harvest", "input", "activity", "observation", "seeding"):
            path = (
                f"/api/log/{kind}?filter[asset.id]={aid}"
                f"&include=quantity,quantity.units&page[limit]=50"
            )
            self._paged(path)
            for (itype, _iid), inc in self._last_included.items():
                if not itype.startswith("quantity--"):
                    continue
                attrs = inc["attributes"]
                if attrs.get("measure") != measure:
                    continue
                if unit and not self._unit_matches(inc, unit):
                    continue
                total += _quantity_value(attrs.get("value"))
        return total

    def _unit_matches(self, quantity_inc: dict[str, Any], unit: str) -> bool:
        rel = ((quantity_inc.get("relationships") or {}).get("units") or {}).get("data")
        if not rel:
            return False
        uid = rel["id"] if isinstance(rel, dict) else rel[0]["id"]
        term = self._last_included.get(("taxonomy_term--unit", uid))
        return bool(term) and term["attributes"].get("name") == unit

    def log_status(self, log_handle: Handle) -> str:
        _, kind, uid = self._split(log_handle)
        doc = self.client.request("GET", f"/api/log/{kind}/{uid}")
        return doc["data"]["attributes"].get("status", "")

    def log_count(self, asset_handle: Handle, kind: str) -> int:
        _, _, aid = self._split(asset_handle)
        rows = self._paged(
            f"/api/log/{kind}?filter[asset.id]={aid}&page[limit]=50"
        )
        return len(rows)

    def asset_active(self, asset_handle: Handle) -> bool:
        _, bundle, uid = self._split(asset_handle)
        doc = self.client.request("GET", f"/api/asset/{bundle}/{uid}")
        return doc["data"]["attributes"].get("archived") in (None, "")

    def group_member(self, asset_handle: Handle, group_handle: Handle) -> bool:
        _, abundle, aid = self._split(asset_handle)
        _, _, gid = self._split(group_handle)
        # Membership = the group referenced by the LATEST done group-assignment
        # log that includes the asset (farmOS's group-membership semantics).
        path = (
            "/api/log/activity"
            f"?filter[is_group_assignment]=1&filter[asset.id]={aid}"
            "&filter[status]=done&sort=-timestamp&page[limit]=1&include=group"
        )
        rows = self._paged(path)
        if not rows:
            return False
        grp = ((rows[0].get("relationships") or {}).get("group") or {}).get("data")
        if not grp:
            return False
        grp_ids = {grp["id"]} if isinstance(grp, dict) else {g["id"] for g in grp}
        return gid in grp_ids

    def quantity_recorded(
        self, log_handle: Handle, measure: str, unit: str
    ) -> float:
        _, kind, uid = self._split(log_handle)
        path = f"/api/log/{kind}/{uid}?include=quantity,quantity.units"
        doc = self.client.request("GET", path)
        included = {(i["type"], i["id"]): i for i in (doc.get("included") or [])}
        self._last_included = included
        total = 0.0
        for (itype, _iid), inc in included.items():
            if not itype.startswith("quantity--"):
                continue
            attrs = inc["attributes"]
            if attrs.get("measure") != measure:
                continue
            if unit and not self._unit_matches(inc, unit):
                continue
            total += _quantity_value(attrs.get("value"))
        return total


# --------------------------------------------------------------------------- #
# Value helpers                                                                #
# --------------------------------------------------------------------------- #
def _as_fraction(value: float) -> tuple[int, int]:
    """Represent a decimal as farmOS's (numerator, denominator) fraction field."""
    if float(value).is_integer():
        return int(value), 1
    # up to 6 decimal places is plenty for the value flows we record
    den = 1_000_000
    return int(round(value * den)), den


def _quantity_value(value: Any) -> float:
    """Read a farmOS fraction quantity value into a float."""
    if value is None:
        return 0.0
    if isinstance(value, dict):
        if value.get("decimal") is not None:
            return float(value["decimal"])
        num = value.get("numerator", 0)
        den = value.get("denominator", 1) or 1
        return float(num) / float(den)
    return float(value)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
