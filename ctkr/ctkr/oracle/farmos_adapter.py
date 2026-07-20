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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
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
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Never inherit urllib's no-timeout default: an oracle that dies mid-run
        # must fail in seconds, not hang the fan-out (MetaCoding-9h5.28).
        self.timeout = timeout
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
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
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
        self._log_bundles: tuple[str, ...] | None = None

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

    def log_bundles(self) -> tuple[str, ...]:
        """Every log bundle **the source's own resource index publishes**.

        A fold over "all logs" must fold over the set the SOURCE says exists,
        not a list we typed. The hard-coded five-kind list this replaces omitted
        ``birth`` — so `yield_total` and `adjustment_count` were silently blind
        to a whole bundle, which is `group_member`'s defect one level up: an
        adapter-authored enumeration standing in for a source-stated one.
        """
        if self._log_bundles is None:
            links = self.client.request("GET", "/api").get("links") or {}
            self._log_bundles = tuple(sorted(
                k.split("--", 1)[1] for k in links if k.startswith("log--")
            ))
        return self._log_bundles

    # ---- given / when ------------------------------------------------------ #
    def create_asset(
        self, entity: str, name: str, descriptor: str = "", sex: str = ""
    ) -> Handle:
        bundle = _ASSET_BUNDLE.get(entity)
        if bundle is None:
            raise AdapterError(f"farmOS has no asset bundle for entity {entity!r}")
        attrs: dict[str, Any] = {"name": name}
        if sex:
            attrs["sex"] = sex
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
        # No adapter-minted timestamp. The previous code stamped a strictly
        # increasing per-instance timestamp so "latest wins" would be
        # well-defined under a sort=-timestamp read — i.e. the adapter SHAPED
        # the observation to suit its own query. farmOS breaks the tie itself
        # (`lfd2.timestamp = lfd.timestamp AND lfd2.id > lfd.id`), and
        # `group_member` now reads it that way, so the source orders its own
        # events and we record what it did.
        doc = {
            "data": {
                "type": "log--activity",
                "attributes": {
                    "name": "group assignment",
                    "status": "done",
                    "is_group_assignment": True,
                    "timestamp": int(time.time()),
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
        # farmOS marks an asset inactive via the boolean `archived` flag.
        doc = {"data": {"type": f"asset--{bundle}", "id": uid,
                        "attributes": {"archived": True}}}
        self.client.request("PATCH", f"/api/asset/{bundle}/{uid}", doc)

    # ---- then (reads) ------------------------------------------------------ #
    def asset_yield_total(
        self, asset_handle: Handle, measure: str, unit: str
    ) -> float:
        _, _, aid = self._split(asset_handle)
        total = 0.0
        for kind in self.log_bundles():
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
        # farmOS: `archived` is a boolean; an active asset is not archived.
        return not doc["data"]["attributes"].get("archived")

    #: farmOS's own membership authority, quoted so the derivation and the thing
    #: it is validated against sit next to each other in the file that computes it:
    #:
    #:   web/profiles/farm/modules/asset/group/src/GroupMembership.php
    #:     public function getGroupMembers(array $groups, bool $recurse = TRUE,
    #:                                     $timestamp = NULL)
    #:
    #: Three facts this code MUST honour, each of which the previous
    #: implementation did not, and each of which was measured to invert an
    #: acceptance verdict:
    #:   1. RECURSION IS THE DEFAULT. A member of a member-group is a member.
    #:   2. EFFECTIVE TIME GATES. `lfd.timestamp <= :timestamp` (default: now).
    #:      A not-yet-effective assignment does not confer membership.
    #:   3. THE TIE-BREAK IS THE SOURCE'S. `lfd2.timestamp = lfd.timestamp AND
    #:      lfd2.id > lfd.id` — larger internal id wins an equal-time tie.
    def _direct_group_ids(self, asset_uuid: str, as_of: int) -> set[str]:
        """The group(s) the newest effective done assignment puts an asset in."""
        path = (
            "/api/log/activity"
            "?filter[ga][condition][path]=is_group_assignment"
            "&filter[ga][condition][value]=1"
            "&filter[st][condition][path]=status"
            "&filter[st][condition][value]=done"
            f"&filter[as][condition][path]=asset.id"
            f"&filter[as][condition][value]={asset_uuid}"
            "&filter[ts][condition][path]=timestamp"
            "&filter[ts][condition][operator]=%3C%3D"
            f"&filter[ts][condition][value]={as_of}"
            "&sort=-timestamp,-drupal_internal__id&page[limit]=1&include=group"
        )
        rows = self._paged(path)
        if not rows:
            return set()
        grp = ((rows[0].get("relationships") or {}).get("group") or {}).get("data")
        if not grp:
            return set()
        return {grp["id"]} if isinstance(grp, dict) else {g["id"] for g in grp}

    def group_member(self, asset_handle: Handle, group_handle: Handle) -> bool:
        _, _, aid = self._split(asset_handle)
        _, _, gid = self._split(group_handle)
        as_of = int(time.time())
        # Walk the membership chain upward. `getGroupMembers(recurse=TRUE)` says
        # a group's members include the members of its member-groups; read from
        # the asset's side that is exactly the transitive closure of "the group
        # my newest effective assignment names".
        seen: set[str] = set()
        frontier = self._direct_group_ids(aid, as_of)
        while frontier:
            if gid in frontier:
                return True
            seen |= frontier
            nxt: set[str] = set()
            for g in frontier:
                nxt |= self._direct_group_ids(g, as_of)
            frontier = nxt - seen  # a membership cycle terminates, it does not hang
        return False

    # ---- stock / inventory (w0a) ------------------------------------------- #
    # farmOS keeps the adjustment on the QUANTITY (`inventory_adjustment` +
    # `inventory_asset`); the LOG supplies the status and the effective time.
    # Two writes per adjustment, therefore. Both fields only exist once the
    # farm_inventory module is installed — a missing module is reported with the
    # fix rather than silently producing an empty stock reading.
    # The oracle is SHARED. A remedy that tells an agent to run docker/drush
    # against it is a remedy that tells one agent to break every sibling's run,
    # and the previous wording did exactly that. If the write was REFUSED rather
    # than unsupported, the refusal is the finding — record it.
    _SHARED_ORACLE_RULE = (
        "Do NOT run docker, drush, or bring-up.sh against this oracle: it is "
        "shared by every concurrent run. Report the missing surface instead."
    )
    _INVENTORY_REMEDY = (
        "the stock surface is absent at the boundary. If the source REFUSED the "
        "write, that refusal is the semantic — set expect_refusal on the flow. "
        "If the surface is genuinely absent, this feature cannot be recorded "
        "here. " + _SHARED_ORACLE_RULE
    )
    _BIRTH_REMEDY = (
        "the birth-record surface is absent at the boundary. If the source "
        "REFUSED the write, that refusal is the semantic — set expect_refusal on "
        "the flow. If the surface is genuinely absent, this feature cannot be "
        "recorded here. " + _SHARED_ORACLE_RULE
    )

    def _create_adjustment_quantity(
        self, q: QuantitySpec, adjustment: str, asset: tuple[str, str, str]
    ) -> str:
        num, den = _as_fraction(q.value)
        attrs: dict[str, Any] = {
            "value": {"numerator": num, "denominator": den},
            "inventory_adjustment": adjustment,
        }
        # Omitting `measure`/`units` is meaningful: farmOS files the adjustment in
        # a distinct unnamed bucket rather than merging it into a named one.
        if q.measure:
            attrs["measure"] = q.measure
        if q.label:
            attrs["label"] = q.label
        _, abundle, aid = asset
        rels: dict[str, Any] = {
            "inventory_asset": {"data": {"type": f"asset--{abundle}", "id": aid}},
        }
        if q.unit:
            rels["units"] = {"data": {"type": "taxonomy_term--unit",
                                      "id": self._ensure_unit(q.unit)}}
        doc = {"data": {"type": "quantity--standard", "attributes": attrs,
                        "relationships": rels}}
        try:
            return self.client.request(
                "POST", "/api/quantity/standard", doc
            )["data"]["id"]
        except AdapterError as exc:
            raise AdapterError(f"{exc}\n  {self._INVENTORY_REMEDY}") from exc

    def record_inventory_adjustment(
        self,
        adjustment: str,
        name: str,
        status: str,
        asset_handles: list[Handle],
        quantities: list[QuantitySpec],
        effective_time: Any = None,
    ) -> Handle:
        assets = [self._split(h) for h in asset_handles]
        qids: list[str] = []
        for asset in assets:
            for q in quantities:
                qids.append(self._create_adjustment_quantity(q, adjustment, asset))
        attrs: dict[str, Any] = {"name": name, "status": status or "done"}
        if effective_time is not None:
            attrs["timestamp"] = _iso(effective_time)
        rels: dict[str, Any] = {
            "quantity": {"data": [{"type": "quantity--standard", "id": qid}
                                  for qid in qids]},
        }
        if assets:
            rels["asset"] = {"data": [{"type": f"asset--{b}", "id": u}
                                      for _, b, u in assets]}
        doc = {"data": {"type": "log--activity", "attributes": attrs,
                        "relationships": rels}}
        uid = self.client.request("POST", "/api/log/activity", doc)["data"]["id"]
        return f"log:activity:{uid}"

    def set_effective_time(self, log_handle: Handle, effective_time: Any) -> None:
        _, kind, uid = self._split(log_handle)
        doc = {"data": {"type": f"log--{kind}", "id": uid,
                        "attributes": {"timestamp": _iso(effective_time)}}}
        self.client.request("PATCH", f"/api/log/{kind}/{uid}", doc)

    def _stock_rows(self, asset_handle: Handle) -> list[dict[str, Any]]:
        """The per-(measure, unit) stock rows farmOS computes for an asset.

        Read verbatim from the boundary: ``units`` is the unit's NAME and
        ``value`` a decimal string, both exactly as delivered.
        """
        _, bundle, uid = self._split(asset_handle)
        doc = self.client.request("GET", f"/api/asset/{bundle}/{uid}")
        rows = doc["data"]["attributes"].get("inventory")
        if rows is None:
            raise AdapterError(
                f"no stock is delivered for asset {bundle}: {self._INVENTORY_REMEDY}"
            )
        return list(rows)

    def stock_on_hand(self, asset_handle: Handle, measure: str, unit: str) -> float:
        """Stock for one (measure, unit) pair; 0.0 when the pair is not delivered.

        The absent-pair case is deliberately NOT conflated with a delivered zero —
        :meth:`stock_pair_count` is the probe that tells them apart.
        """
        for row in self._stock_rows(asset_handle):
            if (row.get("measure") or "") != measure:
                continue
            if (row.get("units") or "") != unit:
                continue
            return float(row.get("value") or 0)
        return 0.0

    def stock_pair_count(self, asset_handle: Handle) -> int:
        return len(self._stock_rows(asset_handle))

    def adjustment_count(self, asset_handle: Handle) -> int:
        """How many recorded events carry a stock adjustment against the asset.

        There is no cross-kind event collection at this boundary, so the ledger
        query is issued once per bundle THE SOURCE PUBLISHES and the rows summed.
        """
        _, _, aid = self._split(asset_handle)
        total = 0
        for kind in self.log_bundles():
            total += len(self._paged(
                f"/api/log/{kind}?filter[quantity.inventory_asset.id]={aid}"
                "&sort=timestamp,drupal_internal__id&page[limit]=50"
            ))
        return total

    # ---- lineage (w0b) ------------------------------------------------------ #
    def record_birth(
        self,
        child_handle: Handle,
        parent_handles: list[Handle],
        name: str,
        status: str,
        effective_time: Any = None,
    ) -> Handle:
        _, cbundle, cid = self._split(child_handle)
        attrs: dict[str, Any] = {"name": name, "status": status or "done"}
        if effective_time is not None:
            attrs["timestamp"] = _iso(effective_time)
        rels: dict[str, Any] = {
            "asset": {"data": [{"type": f"asset--{cbundle}", "id": cid}]},
        }
        if parent_handles:
            # farmOS carries a single birthing parent on the birth record.
            _, pbundle, pid = self._split(parent_handles[0])
            rels["mother"] = {"data": {"type": f"asset--{pbundle}", "id": pid}}
        doc = {"data": {"type": "log--birth", "attributes": attrs,
                        "relationships": rels}}
        try:
            uid = self.client.request("POST", "/api/log/birth", doc)["data"]["id"]
        except AdapterError as exc:
            raise AdapterError(f"{exc}\n  {self._BIRTH_REMEDY}") from exc
        return f"log:birth:{uid}"

    def correct_birth(
        self,
        birth_handle: Handle,
        parent_handles: list[Handle] | None = None,
        effective_time: Any = None,
    ) -> None:
        _, kind, uid = self._split(birth_handle)
        data: dict[str, Any] = {"type": f"log--{kind}", "id": uid}
        if effective_time is not None:
            data["attributes"] = {"timestamp": _iso(effective_time)}
        if parent_handles is not None:
            if parent_handles:
                _, pbundle, pid = self._split(parent_handles[0])
                ref: Any = {"type": f"asset--{pbundle}", "id": pid}
            else:
                ref = None
            data["relationships"] = {"mother": {"data": ref}}
        self.client.request("PATCH", f"/api/log/{kind}/{uid}", {"data": data})

    def set_parents(
        self, animal_handle: Handle, parent_handles: list[Handle]
    ) -> None:
        _, bundle, uid = self._split(animal_handle)
        parents = [self._split(h) for h in parent_handles]
        doc = {"data": {"type": f"asset--{bundle}", "id": uid,
                        "relationships": {"parent": {"data": [
                            {"type": f"asset--{b}", "id": u} for _, b, u in parents
                        ]}}}}
        self.client.request("PATCH", f"/api/asset/{bundle}/{uid}", doc)

    def set_nicknames(self, animal_handle: Handle, names: list[str]) -> None:
        _, bundle, uid = self._split(animal_handle)
        doc = {"data": {"type": f"asset--{bundle}", "id": uid,
                        "attributes": {"nickname": list(names)}}}
        self.client.request("PATCH", f"/api/asset/{bundle}/{uid}", doc)

    def _animal(self, animal_handle: Handle) -> dict[str, Any]:
        _, bundle, uid = self._split(animal_handle)
        return self.client.request("GET", f"/api/asset/{bundle}/{uid}")["data"]

    def animal_sex(self, animal_handle: Handle) -> str:
        return self._animal(animal_handle)["attributes"].get("sex") or ""

    def nicknames(self, animal_handle: Handle) -> list[str]:
        return list(self._animal(animal_handle)["attributes"].get("nickname") or [])

    def birth_date(self, animal_handle: Handle) -> str:
        return self._animal(animal_handle)["attributes"].get("birthdate") or ""

    @staticmethod
    def _parent_ids(animal: dict[str, Any]) -> list[str]:
        data = ((animal.get("relationships") or {}).get("parent") or {}).get("data")
        if not data:
            return []
        return [data["id"]] if isinstance(data, dict) else [d["id"] for d in data]

    def parent_count(self, animal_handle: Handle) -> int:
        return len(self._parent_ids(self._animal(animal_handle)))

    def has_parent(self, animal_handle: Handle, parent_handle: Handle) -> bool:
        _, _, pid = self._split(parent_handle)
        return pid in self._parent_ids(self._animal(animal_handle))

    def birth_record_count(self, animal_handle: Handle) -> int:
        _, _, aid = self._split(animal_handle)
        try:
            return len(self._paged(
                f"/api/log/birth?filter[asset.id]={aid}&page[limit]=50"
            ))
        except AdapterError as exc:
            raise AdapterError(f"{exc}\n  {self._BIRTH_REMEDY}") from exc

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
def _iso(effective_time: Any) -> str:
    """Render an effective time as the ISO-8601 instant farmOS accepts on write.

    Whole seconds only: farmOS rejects a fractional-second instant outright
    ("not in an accepted format"), and its effective-time resolution is one
    second anyway — which is exactly what makes an equal-time tie observable.
    """
    if isinstance(effective_time, str):
        return effective_time
    if isinstance(effective_time, (int, float)):
        dt = datetime.fromtimestamp(float(effective_time), tz=UTC)
    else:
        dt = effective_time
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


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


