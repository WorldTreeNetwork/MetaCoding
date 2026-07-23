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
    "material": "material",
    "sensor": "sensor",
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
        elif bundle == "material" and descriptor:
            # material_type is OPTIONAL on a material asset (unlike plant/animal
            # types): a bare descriptor-less material asset is exactly the
            # quantity_presave fold's bail-out contrast, so no default is minted.
            term = self._ensure_term("material_type", descriptor)
            rels["material_type"] = {"data": {"type": "taxonomy_term--material_type",
                                              "id": term}}
        doc: dict[str, Any] = {"data": {"type": f"asset--{bundle}", "attributes": attrs}}
        if rels:
            doc["data"]["relationships"] = rels
        uid = self.client.request("POST", f"/api/asset/{bundle}", doc)["data"]["id"]
        return f"asset:{bundle}:{uid}"

    def create_plant_type_term(
        self, name: str, maturity_days: int | None = None,
        harvest_days: int | None = None, crop_family: str = "",
        companions: list[str] | None = None,
    ) -> Handle:
        """Create a plant_type term with its planning fields (MetaCoding plant-type).

        The two day counts are integer attributes farmOS delivers as JSON
        integers (validated live). crop_family is a single crop_family term
        reference and companions a multi-valued plant_type term reference; each
        field's own auto_create is false, so the referenced terms are ensured by
        NAME through :meth:`_ensure_term` (find-or-create, exactly the unit/lab
        form) and referenced by id — the fixture never carries a per-run UUID.
        """
        attrs: dict[str, Any] = {"name": name}
        if maturity_days is not None:
            attrs["maturity_days"] = maturity_days
        if harvest_days is not None:
            attrs["harvest_days"] = harvest_days
        rels: dict[str, Any] = {}
        if crop_family:
            cf_id = self._ensure_term("crop_family", crop_family)
            rels["crop_family"] = {
                "data": {"type": "taxonomy_term--crop_family", "id": cf_id}
            }
        if companions:
            comp_ids = [self._ensure_term("plant_type", c) for c in companions]
            rels["companions"] = {"data": [
                {"type": "taxonomy_term--plant_type", "id": cid} for cid in comp_ids
            ]}
        doc: dict[str, Any] = {
            "data": {"type": "taxonomy_term--plant_type", "attributes": attrs}
        }
        if rels:
            doc["data"]["relationships"] = rels
        uid = self.client.request(
            "POST", "/api/taxonomy_term/plant_type", doc
        )["data"]["id"]
        return f"taxonomy_term:plant_type:{uid}"

    def _ensure_data_stream(self, name: str) -> str:
        """Find-or-create a basic data_stream by NAME; return its uuid.

        The _ensure_term form lifted to a content entity (MetaCoding-ej0):
        the sensor's data_stream reference carries no auto_create, so the
        referenced streams must exist — ensured by name, never a per-run UUID
        in the fixture. Validated live: POST /api/data_stream/basic 201 with
        name-only attributes.
        """
        key = ("data_stream:basic", name)
        if key in self._type_term_cache:
            return self._type_term_cache[key]
        q = f"/api/data_stream/basic?filter[name]={urllib.parse.quote(name)}"
        data = self.client.request("GET", q).get("data") or []
        if data:
            uid = data[0]["id"]
        else:
            doc = {"data": {"type": "data_stream--basic",
                            "attributes": {"name": name}}}
            uid = self.client.request(
                "POST", "/api/data_stream/basic", doc
            )["data"]["id"]
        self._type_term_cache[key] = uid
        return uid

    def create_sensor_asset(
        self, name: str, data_streams: list[str] | None = None,
        private_key: str = "", public: bool | None = None,
    ) -> Handle:
        """Create a sensor asset with its bundle fields (MetaCoding-ej0).

        data_streams are basic data_stream NAMES ensured through
        :meth:`_ensure_data_stream` and referenced by id in stated order (the
        boundary preserves it — validated live). private_key rides only when
        stated: an unstated key is minted by farmOS (DataStream::createUniqueKey,
        validated live) and can never reproduce. public rides only when stated:
        the boundary's unset value is null, not the entity-level default false
        (validated live), and None here means unstated.
        """
        attrs: dict[str, Any] = {"name": name}
        if private_key:
            attrs["private_key"] = private_key
        if public is not None:
            attrs["public"] = public
        doc: dict[str, Any] = {
            "data": {"type": "asset--sensor", "attributes": attrs}
        }
        if data_streams:
            ds_ids = [self._ensure_data_stream(n) for n in data_streams]
            doc["data"]["relationships"] = {"data_stream": {"data": [
                {"type": "data_stream--basic", "id": did} for did in ds_ids
            ]}}
        uid = self.client.request("POST", "/api/asset/sensor", doc)["data"]["id"]
        return f"asset:sensor:{uid}"

    def _create_quantity(self, q: QuantitySpec) -> tuple[str, str]:
        """POST one quantity resource; returns ``(bundle, uuid)``. The bundle is
        the spec's classification ("material"/"test") or "standard" (MetaCoding-xdt:
        the DSL previously created only quantity--standard, so material_quantity's
        bound contrast could never observe 'material' itself)."""
        bundle = q.bundle or "standard"
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
        if q.inventory_asset:
            # Already a HANDLE here — steps.apply_when resolved the fixture's
            # alias (MetaCoding-5ln). The core-inventory field every quantity
            # carries; the material quantity_presave fold keys off it.
            _, abundle, aid = self._split(q.inventory_asset)
            rels["inventory_asset"] = {
                "data": [{"type": f"asset--{abundle}", "id": aid}]
            }
        if q.test_method:
            # The `test_method` entity_reference field on quantity--test
            # (TestQuantity.php), target taxonomy_term--test_method, auto_create.
            # A NAME resolved/minted like a unit, delivered as a single-valued
            # reference (validated live, MetaCoding-wgy).
            method_id = self._ensure_term("test_method", q.test_method)
            rels["test_method"] = {
                "data": {"type": "taxonomy_term--test_method", "id": method_id}
            }
        doc = {"data": {"type": f"quantity--{bundle}", "attributes": attrs}}
        if rels:
            doc["data"]["relationships"] = rels
        uid = self.client.request("POST", f"/api/quantity/{bundle}", doc)["data"]["id"]
        return bundle, uid

    def record_log(
        self,
        kind: str,
        name: str,
        status: str,
        asset_handles: list[Handle],
        quantities: list[QuantitySpec],
        lot_number: str = "",
        equipment_handles: list[Handle] | None = None,
        lab_received_date: str = "",
        lab_processed_date: str = "",
        lab_test_type: str = "",
        soil_texture: str = "",
        lab: str = "",
    ) -> Handle:
        assets = [self._split(h) for h in asset_handles]
        rels: dict[str, Any] = {}
        if assets:
            rels["asset"] = {"data": [
                {"type": f"asset--{b}", "id": u} for _, b, u in assets
            ]}
        if equipment_handles:
            # The multi-valued `equipment` base field farm_equipment adds to
            # every log (FieldHooks.php); references equipment assets only.
            eq = [self._split(h) for h in equipment_handles]
            rels["equipment"] = {"data": [
                {"type": f"asset--{b}", "id": u} for _, b, u in eq
            ]}
        if quantities:
            created = [self._create_quantity(q) for q in quantities]
            rels["quantity"] = {"data": [
                {"type": f"quantity--{b}", "id": qid} for b, qid in created
            ]}
        attrs: dict[str, Any] = {"name": name, "status": status or "done"}
        if lot_number:
            # The lot_number string field the harvest/input/seeding bundles
            # declare. Written only when stated; a bundle without the field will
            # refuse the write at the boundary, loudly.
            attrs["lot_number"] = lot_number
        # lab_test bundle fields (MetaCoding-wgy). Written only when stated; a
        # bundle without the field refuses the write at the boundary, loudly.
        # The date fields take an absolute ISO-8601 instant farmOS stores and
        # delivers verbatim (validated live); lab_test_type/soil_texture are
        # plain strings.
        if lab_received_date:
            attrs["lab_received_date"] = lab_received_date
        if lab_processed_date:
            attrs["lab_processed_date"] = lab_processed_date
        if lab_test_type:
            attrs["lab_test_type"] = lab_test_type
        if soil_texture:
            attrs["soil_texture"] = soil_texture
        if lab:
            # `lab` entity_reference (LabTestLog.php), target taxonomy_term--lab,
            # auto_create — a NAME resolved/minted like a unit, delivered as a
            # single-valued reference (validated live).
            lab_id = self._ensure_term("lab", lab)
            rels["lab"] = {"data": {"type": "taxonomy_term--lab", "id": lab_id}}
        doc: dict[str, Any] = {
            "data": {"type": f"log--{kind}", "attributes": attrs}
        }
        if rels:
            doc["data"]["relationships"] = rels
        uid = self.client.request("POST", f"/api/log/{kind}", doc)["data"]["id"]
        return f"log:{kind}:{uid}"

    def quantities_of(self, log_handle: Handle) -> list[Handle]:
        """The log's owned quantities as handles, in the log's stated order —
        a boundary readback of the ``quantity`` relationship, used only to bind
        flow-declared quantity aliases (MetaCoding-xdt)."""
        _, kind, uid = self._split(log_handle)
        doc = self.client.request("GET", f"/api/log/{kind}/{uid}")
        rel = ((doc["data"].get("relationships") or {}).get("quantity") or {})
        out: list[Handle] = []
        for row in rel.get("data") or []:
            rtype = row.get("type") or ""
            bundle = rtype.split("--", 1)[1] if "--" in rtype else "standard"
            out.append(f"quantity:{bundle}:{row['id']}")
        return out

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


    # --- lot_number (assertion, PROVISIONAL — MetaCoding-io6) --------------- #
    def lot_number(self, subject_handle: Handle) -> Any:
        """Deliver the recorded lot number value for the subject log, or "" when
        none was recorded.

        A boundary readback of the ``lot_number`` string field farmOS declares on
        the harvest / input / seeding log bundles (Harvest.php:fields.lot_number
        et al.). PROVISIONAL: the derivation carries no source-authority
        validation yet, so its values cannot score until a sealed recording binds
        the term.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/log/{kind}/{uid}")
        return doc["data"]["attributes"].get("lot_number") or ""

    # --- material_quantity (assertion, PROVISIONAL — MetaCoding-io6) -------- #
    def material_quantity(self, subject_handle: Handle) -> Any:
        """Deliver the classification of the quantity recorded on the subject log
        — the quantity resource's own bundle ("material", "standard", …) — so an
        assertion can determine whether that quantity is material; "" when the log
        carries no quantity.

        A boundary readback: farmOS states each quantity's classification as its
        JSON:API resource ``type`` (``quantity--material`` for an input log's
        default quantity type). The first delivered quantity's classification is
        returned. PROVISIONAL until a sealed recording binds the term.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET", f"/api/log/{kind}/{uid}?include=quantity"
        )
        for inc in doc.get("included") or []:
            itype = inc.get("type") or ""
            if itype.startswith("quantity--"):
                return itype.split("--", 1)[1]
        return ""

    # --- delete_log (action, PROVISIONAL — MetaCoding-io6) ------------------ #
    def delete_log(self, subject_handle: Handle) -> Any:
        """Delete the recorded log at the JSON:API write boundary
        (``DELETE /api/log/{bundle}/{uuid}``). farmOS cascades the delete to the
        quantities the log owns. No value is delivered.
        """
        _, kind, uid = self._split(subject_handle)
        self.client.request("DELETE", f"/api/log/{kind}/{uid}")

    # --- delete_quantity (action, PROVISIONAL — MetaCoding-io6) ------------- #
    def delete_quantity(self, subject_handle: Handle) -> Any:
        """Delete the recorded quantity at the JSON:API write boundary
        (``DELETE /api/quantity/{bundle}/{uuid}``). No value is delivered.

        The handle is ``"quantity:{bundle}:{uuid}"``. The flow DSL cannot yet mint
        a quantity alias (``record_log`` does not alias the quantities it owns), so
        this method is adapter-reachable but not yet flow-reachable — honest
        plumbing awaiting a quantity-aliasing follow-up.
        """
        _, bundle, uid = self._split(subject_handle)
        self.client.request("DELETE", f"/api/quantity/{bundle}/{uid}")

    # --- birth_mother (assertion, PROVISIONAL — birth_mother bind) --------- #
    def birth_mother(self, subject_handle: Handle, other_handle: Handle) -> bool:
        """Deliver whether ``other`` is the animal recorded as the mother on the
        birth log, so an assertion can confirm the recorded dam against an
        expected animal.

        The subject is a birth LOG. farmOS carries the birthing dam as the birth
        log's own ``mother`` relationship (Birth.php:fields.mother); this reads
        that reference off ``/api/log/birth/{uuid}`` and reports whether the
        referenced asset id equals ``other``'s id — the ``has_parent`` house form
        for an entity reference, chosen because a raw per-run asset UUID could
        never reproduce across runs or ports and so could never score. A birth
        with no recorded mother, or one whose mother is a different animal,
        delivers ``False``. PROVISIONAL: the derivation carries no
        source-authority validation yet, so its values cannot score until a
        sealed recording binds the term.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/log/{kind}/{uid}")
        rel = ((doc["data"].get("relationships") or {}).get("mother") or {}).get("data")
        mother_id = rel["id"] if isinstance(rel, dict) and rel else ""
        _, _, other_id = self._split(other_handle)
        return bool(mother_id) and mother_id == other_id

    # --- equipment_used (assertion, PROVISIONAL — MetaCoding-1cv) ----------- #
    def equipment_used(self, subject_handle: Handle, other_handle: Handle) -> bool:
        """Deliver whether ``other`` is among the equipment the subject log
        records as used, so an assertion can confirm the recorded 'Equipment
        used' reference against an expected asset.

        A boundary readback of the multi-valued ``equipment`` base field
        farm_equipment adds to every log (FieldHooks.php:entityBaseFieldInfo,
        target asset--equipment) — the ``has_parent`` house form for an entity
        reference: membership of the expected asset, never a raw per-run UUID,
        so the value can reproduce across runs and ports. A log with no
        recorded equipment, or whose equipment does not include ``other``,
        delivers ``False``. PROVISIONAL until a sealed recording binds the
        term.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/log/{kind}/{uid}")
        rel = ((doc["data"].get("relationships") or {}).get("equipment") or {})
        rows = rel.get("data") or []
        _, _, other_id = self._split(other_handle)
        return any(isinstance(r, dict) and r.get("id") == other_id for r in rows)

    # --- material_type_recorded (assertion, PROVISIONAL — MetaCoding-5ln) --- #
    def material_type_recorded(self, subject_handle: Handle) -> list[str]:
        """Deliver the ordered material_type term NAMES recorded on the first
        material-classified quantity of the subject log; [] when the log
        carries no material quantity or it records no material type.

        The observable of the quantity_presave denormalizing fold
        (farm_material EntityHooks.php): a material quantity referencing a
        material asset inherits the asset's material_type at save. A boundary
        readback: the log's own quantity relationship, the first
        quantity--material's own material_type relationship, and each term's
        own stated name — names, never per-run term UUIDs, so the value
        reproduces across runs and ports. PROVISIONAL until a sealed
        recording binds the term.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET",
            f"/api/log/{kind}/{uid}?include=quantity,quantity.material_type",
        )
        included = {(inc["type"], inc["id"]): inc for inc in doc.get("included") or []}
        for inc in doc.get("included") or []:
            if inc.get("type") != "quantity--material":
                continue
            rel = ((inc.get("relationships") or {}).get("material_type") or {})
            names: list[str] = []
            for row in rel.get("data") or []:
                term = included.get((row.get("type"), row.get("id")))
                if term is not None:
                    names.append(term["attributes"]["name"])
            return names
        return []

    # --- lab_test bundle-field readbacks (MetaCoding-wgy) ------------------- #
    # Each reads ONE field farm_lab_test declares on the lab_test log
    # (LabTestLog.php). The four attribute fields are BOUNDARY transcription —
    # the source states the value at its published interface and we read it
    # verbatim ("" when unset, delivered as JSON null). `laboratory` and
    # `lab_test_measurement` follow a stated reference to a term's own stated
    # NAME (never a per-run UUID), the material_type_recorded house form.
    def _lab_test_attr(self, subject_handle: Handle, attr: str) -> str:
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/log/{kind}/{uid}")
        return doc["data"]["attributes"].get(attr) or ""

    # --- lab_sample_type (assertion — MetaCoding-wgy) ----------------------- #
    def lab_sample_type(self, subject_handle: Handle) -> str:
        """The sample category recorded on the subject lab-test log — the
        `lab_test_type` list_string attribute farm_lab_test declares
        (LabTestLog.php:fields.lab_test_type), delivered verbatim ("soil",
        "tissue", "water"); "" when the log records none.

        Boundary transcription: the source states the category as an attribute
        on the log; reading it is not a computation of ours.
        """
        return self._lab_test_attr(subject_handle, "lab_test_type")

    # --- laboratory (assertion — MetaCoding-wgy) ---------------------------- #
    def laboratory(self, subject_handle: Handle) -> str:
        """The NAME of the laboratory recorded as having performed the subject
        lab test — the term the log's single-valued `lab` entity_reference
        points to (LabTestLog.php:fields.lab, target taxonomy_term--lab); ""
        when the log records none.

        A boundary readback that follows a source-stated reference to the
        term's own stated name (validated live: `lab` delivered as one
        reference, not a list) — the material_type_recorded house form for an
        entity reference. A raw per-run term UUID could never reproduce across
        runs or ports; the name can.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET", f"/api/log/{kind}/{uid}?include=lab"
        )
        rel = ((doc["data"].get("relationships") or {}).get("lab") or {}).get("data")
        if not isinstance(rel, dict) or not rel:
            return ""
        for inc in doc.get("included") or []:
            if inc.get("type") == rel.get("type") and inc.get("id") == rel.get("id"):
                return inc["attributes"].get("name") or ""
        return ""

    # --- lab_test_measurement (assertion — MetaCoding-wgy) ------------------ #
    def lab_test_measurement(self, subject_handle: Handle) -> list[str]:
        """The ordered `test_method` term NAMES recorded on the first
        test-classified quantity of the subject lab-test log; [] when the log
        carries no test measurement or the measurement records no method.

        The identity of a *lab test measurement*: a quantity--test carrying its
        test_method (TestQuantity.php:fields.test_method, the default quantity
        type of the lab_test log). A boundary readback — the log's own quantity
        relationship, the first quantity--test's own test_method relationship,
        and each term's own stated name (names, never per-run UUIDs, so the
        value reproduces). The material_type_recorded twin; the "first test
        quantity" selection is ours, sound while a flow carries at most one.
        """
        _, kind, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET",
            f"/api/log/{kind}/{uid}?include=quantity,quantity.test_method",
        )
        included = {(inc["type"], inc["id"]): inc for inc in doc.get("included") or []}
        for inc in doc.get("included") or []:
            if inc.get("type") != "quantity--test":
                continue
            rel = ((inc.get("relationships") or {}).get("test_method") or {})
            data = rel.get("data")
            # test_method is single-valued (validated live) but read defensively
            # for either shape — one object or a list.
            rows = data if isinstance(data, list) else ([data] if data else [])
            names: list[str] = []
            for row in rows:
                term = included.get((row.get("type"), row.get("id")))
                if term is not None:
                    names.append(term["attributes"]["name"])
            return names
        return []

    # --- lab_processing_date (assertion — MetaCoding-wgy) ------------------- #
    def lab_processing_date(self, subject_handle: Handle) -> str:
        """The date the laboratory processed the sample — the log's
        `lab_processed_date` timestamp attribute (LabTestLog.php), delivered
        verbatim as the ISO-8601 instant it was written with (validated live);
        "" when the log records none.

        Boundary transcription. The value is an absolute date authored as an
        input field, not the log's effective time and not wall-clock derived,
        so the MetaCoding-bdy relative-offset trap does not apply.
        """
        return self._lab_test_attr(subject_handle, "lab_processed_date")

    # --- sample_received_date (assertion — MetaCoding-wgy) ------------------ #
    def sample_received_date(self, subject_handle: Handle) -> str:
        """The date the laboratory received the sample — the log's
        `lab_received_date` timestamp attribute (LabTestLog.php), delivered
        verbatim as the ISO-8601 instant it was written with (validated live);
        "" when the log records none.

        Boundary transcription; the same absolute-authored-date reasoning as
        lab_processing_date.
        """
        return self._lab_test_attr(subject_handle, "lab_received_date")

    # --- soil_texture (assertion — MetaCoding-wgy) -------------------------- #
    def soil_texture(self, subject_handle: Handle) -> str:
        """The soil texture reported by the test — the log's `soil_texture`
        string attribute (LabTestLog.php), delivered verbatim (validated live:
        "Loam" delivered unchanged); "" when the log records none.

        Boundary transcription: a plain string the source states on the log.
        """
        return self._lab_test_attr(subject_handle, "soil_texture")

    # --- plant_type term planning-field readbacks (MetaCoding plant-type) --- #
    # The subject is a plant_type TERM handle ("taxonomy_term:plant_type:{uuid}").
    # Each reads a field OFF the term at the JSON:API boundary. The day counts
    # come back as JSON integers (validated live); an unset scalar delivers null,
    # read back as "" (the lot_number house form). The references deliver each
    # target term's own stated NAME — never a per-run UUID — so the value
    # reproduces across runs and ports. PROVISIONAL until a sealed recording
    # binds each term.
    def days_to_maturity(self, subject_handle: Handle) -> Any:
        """The integer maturity_days recorded on the plant_type term, or "" when none."""
        _, vocab, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/taxonomy_term/{vocab}/{uid}")
        v = doc["data"]["attributes"].get("maturity_days")
        return v if v is not None else ""

    def days_to_harvest(self, subject_handle: Handle) -> Any:
        """The integer harvest_days recorded on the plant_type term, or "" when none."""
        _, vocab, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/taxonomy_term/{vocab}/{uid}")
        v = doc["data"]["attributes"].get("harvest_days")
        return v if v is not None else ""

    def crop_family(self, subject_handle: Handle) -> Any:
        """The NAME of the single-valued crop_family term the plant_type term
        references, or "" when none. The referenced term's own name (validated
        live: the crop_family relationship delivers one object, not a list)."""
        _, vocab, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET", f"/api/taxonomy_term/{vocab}/{uid}?include=crop_family")
        rel = ((doc["data"].get("relationships") or {}).get("crop_family") or {}).get("data")
        if not isinstance(rel, dict) or not rel:
            return ""
        target = rel.get("id")
        for inc in doc.get("included") or []:
            if inc.get("id") == target:
                return inc["attributes"]["name"]
        return ""

    def companion_plants(self, subject_handle: Handle) -> list[str]:
        """The ordered NAMES of the plant_type terms the term references as
        companions, or [] when none. Names in the relationship's stated order
        (validated live: companions delivers a JSON array); each term's own
        name, never a per-run UUID."""
        _, vocab, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET", f"/api/taxonomy_term/{vocab}/{uid}?include=companions")
        rows = ((doc["data"].get("relationships") or {}).get("companions") or {}).get("data") or []
        names_by_id = {
            inc["id"]: inc["attributes"]["name"] for inc in (doc.get("included") or [])
        }
        return [names_by_id[r["id"]] for r in rows if r.get("id") in names_by_id]

    # --- sensor asset bundle-field readbacks (MetaCoding-ej0) --------------- #
    # The subject is a sensor ASSET handle ("asset:sensor:{uuid}"). Each reads
    # a field OFF the asset at the JSON:API boundary. private_key and public
    # come back verbatim (validated live; an unset public delivers null, read
    # back as "" — the lot_number house form). data_stream delivers each
    # referenced stream's own stated NAME in the relationship's stated order —
    # never a per-run UUID — so the value reproduces across runs and ports.
    # PROVISIONAL until a sealed recording binds each term.
    def sensor_data_stream(self, subject_handle: Handle) -> list[str]:
        """The ordered NAMES of the data_stream entities the sensor references,
        or [] when none. Names in the relationship's stated order (validated
        live: two streams referenced b,a read back in exactly that order)."""
        _, bundle, uid = self._split(subject_handle)
        doc = self.client.request(
            "GET", f"/api/asset/{bundle}/{uid}?include=data_stream")
        rows = ((doc["data"].get("relationships") or {}).get("data_stream") or {}).get("data") or []
        names_by_id = {
            inc["id"]: inc["attributes"]["name"] for inc in (doc.get("included") or [])
        }
        return [names_by_id[r["id"]] for r in rows if r.get("id") in names_by_id]

    def sensor_private_key(self, subject_handle: Handle) -> Any:
        """The sensor's private_key string verbatim. Only explicitly-recorded
        keys are scoreable: an unstated key is oracle-minted per instance
        (DataStream::createUniqueKey — validated live) and can never
        reproduce, so fixtures asserting on it always state it."""
        _, bundle, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/asset/{bundle}/{uid}")
        v = doc["data"]["attributes"].get("private_key")
        return v if v is not None else ""

    def publicly_readable(self, subject_handle: Handle) -> Any:
        """The sensor's public flag verbatim: true reads true, false reads
        false (a recorded value, distinct from absent), and an unstated flag
        delivers null at the boundary (validated live — NOT the entity-level
        default false), read back as ""."""
        _, bundle, uid = self._split(subject_handle)
        doc = self.client.request("GET", f"/api/asset/{bundle}/{uid}")
        v = doc["data"]["attributes"].get("public")
        return v if v is not None else ""

















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


