"""The OBSERVE bridge: flow-pack (de)serialization + the new adapter operations.

Two things are under test and they are deliberately kept apart:

1. :mod:`ctkr.oracle.flowspec_io` — a written scenario round-trips to JSON and
   back, and an illegal pack fails LOUDLY (unknown action / term / alias, a
   storage leak, a smuggled expected value). No adapter involved.

2. The stock and lineage operations added to the farmOS adapter, exercised
   against ``FakeFarmOS`` — an in-memory model of exactly the JSON:API subset
   the discovery reports verified against the live oracle, including its awkward
   parts (stock pairs reported at zero, the effective-time/creation-order
   tie-break, parentage that vetoes rather than overwrites). No Docker, no
   network: the transport is injected.

The values ``FakeFarmOS`` delivers are a model of the source, not an authority:
the acceptance test that matters is that a recorded flow **self-verifies** — the
value the recorder observed is the value a replay reads back.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime

import pytest

from ctkr.oracle.adapter import AdapterError
from ctkr.oracle.farmos_adapter import FarmOSAdapter
from ctkr.oracle.fixtures import (
    GivenStep,
    QuantitySpec,
    WhenStep,
    resolve_effective_time,
    validate_fixture,
)
from ctkr.oracle.flowspec_io import (
    FlowSpecError,
    dump_flows,
    flow_from_dict,
    flow_to_dict,
    load_flows,
)
from ctkr.oracle.recorder import (
    FlowSpec,
    Probe,
    RecordingClient,
    core_flows,
    hardening_flows,
    record_flow,
)
from ctkr.oracle.runner import run_fixtures


# --------------------------------------------------------------------------- #
# In-memory farmOS (stock + lineage)                                          #
# --------------------------------------------------------------------------- #
def _epoch(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


class FakeFarmOS:
    """The JSON:API subset the w0a/w0b discovery reports verified, in memory."""

    def __init__(self) -> None:
        self.assets: dict[str, dict] = {}
        self.logs: dict[str, dict] = {}
        self.quantities: dict[str, dict] = {}
        self.terms: dict[str, dict] = {}
        self._n = 0

    # ---- plumbing ---------------------------------------------------------- #
    def _id(self) -> str:
        self._n += 1
        return f"id-{self._n:06d}"  # lexicographic order == creation order

    def __call__(self, method, path, body, headers):
        if path == "/oauth/token":
            return json.dumps({"access_token": "faketoken", "expires_in": 3600})
        doc = json.loads(body) if body else None
        parsed = urllib.parse.urlparse(path)
        segs = [s for s in parsed.path.split("/") if s]
        qs = urllib.parse.parse_qs(parsed.query)
        if len(segs) == 1:
            # The resource index. Folds over "all logs" read the bundle set from
            # HERE, because the source states it and we must not type our own.
            return json.dumps({"links": {
                **{f"log--{b}": {"href": f"/api/log/{b}"}
                   for b in ("activity", "birth", "harvest", "input",
                             "observation", "seeding")},
                **{f"asset--{b}": {"href": f"/api/asset/{b}"}
                   for b in ("animal", "equipment", "group", "land", "plant",
                             "structure")},
            }})
        entity, bundle = segs[1], (segs[2] if len(segs) > 2 else None)
        rid = segs[3] if len(segs) > 3 else None
        if method == "POST":
            return self._create(entity, bundle, doc)
        if method == "PATCH":
            return self._patch(entity, bundle, rid, doc)
        if method == "GET":
            return self._get(entity, bundle, rid, qs)
        raise AssertionError(f"unexpected {method} {path}")

    def _store(self, entity):
        return {"asset": self.assets, "log": self.logs,
                "quantity": self.quantities, "taxonomy_term": self.terms}[entity]

    @staticmethod
    def _rel_ids(res, rel):
        data = (res.get("relationships") or {}).get(rel, {}).get("data")
        if not data:
            return []
        return [data["id"]] if isinstance(data, dict) else [d["id"] for d in data]

    # ---- writes ------------------------------------------------------------ #
    def _create(self, entity, bundle, doc):
        data = doc["data"]
        attrs = dict(data.get("attributes", {}))
        rels = dict(data.get("relationships", {}))
        if entity == "log" and bundle == "birth":
            self._reject_duplicate_birth(rels, exclude=None)
        rid = self._id()
        res = {"type": data["type"], "id": rid, "bundle": bundle,
               "attributes": attrs, "relationships": rels}
        res["attributes"]["drupal_internal__id"] = self._n
        if entity == "log":
            res["attributes"].setdefault("timestamp", _iso(1_700_000_000))
        if entity == "asset":
            res["attributes"].setdefault("nickname", [])
            res["relationships"].setdefault("parent", {"data": []})
        self._store(entity)[rid] = res
        if entity == "log" and bundle == "birth":
            self._sync_birth(res)
        return json.dumps({"data": res})

    def _patch(self, entity, bundle, rid, doc):
        res = self._store(entity)[rid]
        data = doc["data"]
        res["attributes"].update(data.get("attributes", {}))
        if data.get("relationships"):
            if entity == "log" and bundle == "birth":
                self._reject_duplicate_birth(data["relationships"], exclude=rid)
            res["relationships"].update(data["relationships"])
        if entity == "log" and bundle == "birth":
            self._sync_birth(res)
        return json.dumps({"data": res})

    # ---- lineage rules (as observed) --------------------------------------- #
    def _reject_duplicate_birth(self, rels, exclude):
        """Uniqueness is enforced on INSERT only — the update path is a hole."""
        if exclude is not None:
            return  # observed: the constraint early-returns for an existing record
        for cid in self._rel_ids({"relationships": rels}, "asset"):
            for lg in self.logs.values():
                if lg["bundle"] == "birth" and cid in self._rel_ids(lg, "asset"):
                    raise AdapterError(
                        "POST /api/log/birth -> 422: already has a birth log"
                    )

    def _sync_birth(self, log):
        mothers = self._rel_ids(log, "mother")
        for cid in self._rel_ids(log, "asset"):
            child = self.assets[cid]
            # birthdate follows the record's effective time, regardless of status
            child["attributes"]["birthdate"] = log["attributes"]["timestamp"]
            # parentage is APPEND-IF-EMPTY: a non-empty list is a complete veto
            if not self._rel_ids(child, "parent") and mothers:
                child["relationships"]["parent"] = {
                    "data": [{"type": "asset--animal", "id": mothers[0]}]
                }

    # ---- stock ------------------------------------------------------------- #
    def _unit_label(self, quantity):
        ids = self._rel_ids(quantity, "units")
        return self.terms[ids[0]]["attributes"]["name"] if ids else ""

    def _stock(self, aid):
        """farmOS's computed stock: pairs from quantities alone, values filtered."""
        mine = {qid: q for qid, q in self.quantities.items()
                if aid in self._rel_ids(q, "inventory_asset")}
        pairs = []
        for q in mine.values():
            pair = (q["attributes"].get("measure") or "", self._unit_label(q))
            if pair not in pairs:
                pairs.append(pair)

        # the ledger: (effective time, creation order) over DONE, not-future logs
        now = datetime.now(UTC).timestamp()
        ledger = []
        for lid, lg in sorted(self.logs.items()):
            if lg["attributes"].get("status") != "done":
                continue
            ts = _epoch(lg["attributes"]["timestamp"])
            if ts > now:
                continue
            for qid in self._rel_ids(lg, "quantity"):
                if qid in mine:
                    ledger.append((ts, lid, mine[qid]))
        ledger.sort(key=lambda row: (row[0], row[1]))

        out = []
        for measure, units in pairs:
            total = 0.0
            for _ts, _lid, q in ledger:
                a = q["attributes"]
                if (a.get("measure") or "") != measure:
                    continue
                if self._unit_label(q) != units:
                    continue
                adj = a.get("inventory_adjustment")
                val = float(a["value"]["numerator"]) / float(a["value"]["denominator"])
                if adj == "reset":
                    total = val
                elif adj == "increment":
                    total += val
                elif adj == "decrement":
                    total -= val
            out.append({"measure": measure, "value": str(total), "units": units})
        return out

    # ---- reads ------------------------------------------------------------- #
    def _render_asset(self, res):
        out = dict(res)
        out["attributes"] = dict(res["attributes"])
        out["attributes"]["inventory"] = self._stock(res["id"])
        return out

    def _get(self, entity, bundle, rid, qs):
        if entity == "taxonomy_term":
            want = qs.get("filter[name]", [None])[0]
            rows = [t for t in self.terms.values()
                    if t["bundle"] == bundle
                    and (want is None or t["attributes"].get("name") == want)]
            return json.dumps({"data": rows})
        if entity == "asset":
            return json.dumps({"data": self._render_asset(self.assets[rid])})
        if entity == "log":
            include = set()
            for inc in qs.get("include", []):
                include.update(inc.split(","))
            if rid:
                res = self.logs[rid]
                return json.dumps({"data": res,
                                   "included": self._included(res, include)})
            rows = [lg for lid, lg in sorted(self.logs.items())
                    if lg["bundle"] == bundle]
            aid = qs.get("filter[asset.id]", [None])[0]
            if aid is not None:
                rows = [r for r in rows if aid in self._rel_ids(r, "asset")]
            inv = qs.get("filter[quantity.inventory_asset.id]", [None])[0]
            if inv is not None:
                rows = [r for r in rows
                        if any(inv in self._rel_ids(self.quantities[q],
                                                    "inventory_asset")
                               for q in self._rel_ids(r, "quantity"))]
            status = qs.get("filter[status]", [None])[0]
            if status is not None:
                rows = [r for r in rows
                        if r["attributes"].get("status") == status]
            if qs.get("filter[is_group_assignment]", [None])[0] is not None:
                rows = [r for r in rows
                        if r["attributes"].get("is_group_assignment")]
            rows = self._conditions(rows, qs)
            rows = self._sorted(rows, qs)
            limit = qs.get("page[limit]", [None])[0]
            if limit is not None:
                rows = rows[: int(limit)]
            included = [i for r in rows for i in self._included(r, include)]
            return json.dumps({"data": rows, "included": included})
        raise AssertionError(f"unhandled GET {entity}/{bundle}/{rid}")

    # ---- the long-form JSON:API condition filter --------------------------- #
    # `filter[k][condition][path|operator|value]`. Needed because a membership
    # read must gate on `timestamp <= now`, and the short form cannot express an
    # operator. farmOS carries `timestamp` as integer unix seconds in filters.
    def _conditions(self, rows, qs):
        groups: dict = {}
        for key, vals in qs.items():
            if not key.startswith("filter[") or "][condition][" not in key:
                continue
            name = key.split("[", 2)[1].rstrip("]")
            part = key.rsplit("[", 1)[1].rstrip("]")
            groups.setdefault(name, {})[part] = vals[0]
        for cond in groups.values():
            field, op = cond.get("path", ""), cond.get("operator", "=")
            want = cond.get("value")
            kept = []
            for r in rows:
                if field == "asset.id":
                    if want in self._rel_ids(r, "asset"):
                        kept.append(r)
                    continue
                got = r["attributes"].get(field)
                if field == "timestamp":
                    got, want_n = _epoch(got), float(want)
                    if (op in ("<=", "%3C%3D") and got <= want_n) or \
                       (op == "=" and got == want_n):
                        kept.append(r)
                    continue
                if field == "is_group_assignment":
                    if bool(got) == (str(want) in ("1", "true", "True")):
                        kept.append(r)
                    continue
                if str(got) == str(want):
                    kept.append(r)
            rows = kept
        return rows

    @staticmethod
    def _sorted(rows, qs):
        spec = qs.get("sort", [None])[0]
        if not spec:
            return rows
        for key in reversed(spec.split(",")):
            desc = key.startswith("-")
            field = key.lstrip("-")
            rows = sorted(
                rows,
                key=lambda r: (_epoch(r["attributes"].get(field))
                               if field == "timestamp"
                               else (r["attributes"].get(field) or 0)),
                reverse=desc,
            )
        return rows

    def _included(self, log, include):
        out = []
        if "quantity" in include:
            for qid in self._rel_ids(log, "quantity"):
                q = self.quantities[qid]
                out.append(q)
                if "quantity.units" in include:
                    out.extend(self.terms[u] for u in self._rel_ids(q, "units"))
        if "group" in include:
            out.extend(self.assets[g] for g in self._rel_ids(log, "group"))
        return out


def _adapter(world: FakeFarmOS | None = None) -> FarmOSAdapter:
    world = world or FakeFarmOS()
    client = RecordingClient("http://fake", "admin", "admin", transport=world)
    adapter = FarmOSAdapter(client)
    adapter.open()
    return adapter


def _q(measure, value, unit="kilogram"):
    return QuantitySpec(measure=measure, value=value, unit=unit)


# --------------------------------------------------------------------------- #
# 1. Serialization round-trip                                                 #
# --------------------------------------------------------------------------- #
def _sample_flow() -> FlowSpec:
    return FlowSpec(
        key="stock-reset-then-increment",
        title="A stock reset assigns a new base that later increments build on",
        feature="stock-adjustment",
        glossary_terms=["planting", "count", "stock_on_hand", "increment", "reset"],
        given=[GivenStep(entity="planting", alias="A", name="Seed Store")],
        when=[
            WhenStep(action="record_inventory_adjustment", alias="L1",
                     kind="increment", status="done", name="delivery",
                     against=["A"], quantities=[_q("count", 10)], at="-7200"),
            WhenStep(action="record_inventory_adjustment", alias="L2",
                     kind="reset", status="done", name="stocktake",
                     against=["A"], quantities=[_q("count", 100)], at="-3600"),
        ],
        probes=[
            Probe(assert_="stock_on_hand", subject="A", measure="count",
                  unit="kilogram"),
            Probe(assert_="stock_pair_count", subject="A"),
            Probe(assert_="adjustment_count", subject="A"),
        ],
    )


def test_flow_round_trips_through_json(tmp_path):
    flow = _sample_flow()
    path = tmp_path / "pack.json"
    assert dump_flows([flow], path) == 1
    back = load_flows(path)
    assert len(back) == 1
    assert flow_to_dict(back[0]) == flow_to_dict(flow)


def test_builtin_packs_round_trip(tmp_path):
    """Every hardcoded flow survives the bridge — the packs are expressible."""
    flows = core_flows() + hardening_flows()
    path = tmp_path / "builtin.json"
    dump_flows(flows, path)
    back = load_flows(path)
    assert [flow_to_dict(f) for f in back] == [flow_to_dict(f) for f in flows]


def test_flow_carries_no_expected_value():
    """The structural guarantee: a probe has nowhere to put an expected value."""
    probe_fields = set(vars(_sample_flow().probes[0]))
    assert probe_fields.isdisjoint({"value", "expected", "result", "observed"})


# --------------------------------------------------------------------------- #
# 2. Loud failures                                                            #
# --------------------------------------------------------------------------- #
def _base_flow_dict(**over):
    d = flow_to_dict(_sample_flow())
    d.update(over)
    return d


def test_unknown_action_fails_loudly():
    d = _base_flow_dict()
    d["when"][0]["action"] = "teleport_asset"
    with pytest.raises(FlowSpecError, match="teleport_asset.*not a glossary action"):
        flow_from_dict(d)


def test_unknown_glossary_term_fails_loudly():
    d = _base_flow_dict(glossary_terms=["planting", "shrinkage"])
    with pytest.raises(FlowSpecError, match="'shrinkage' is not in the domain glossary"):
        flow_from_dict(d)


def test_unknown_probe_assertion_fails_loudly():
    d = _base_flow_dict()
    d["probes"][0]["assert"] = "profit_margin"
    with pytest.raises(FlowSpecError, match="profit_margin.*not a glossary assertion"):
        flow_from_dict(d)


def test_unknown_adjustment_kind_fails_loudly():
    d = _base_flow_dict()
    d["when"][0]["kind"] = "sideways"
    with pytest.raises(FlowSpecError, match="sideways.*stock adjustment kind"):
        flow_from_dict(d)


def test_unbound_alias_fails_loudly():
    d = _base_flow_dict()
    d["when"][0]["against"] = ["ZZ"]
    with pytest.raises(FlowSpecError, match="unknown entity alias 'ZZ'"):
        flow_from_dict(d)


def test_probe_on_unbound_alias_fails_loudly():
    d = _base_flow_dict()
    d["probes"][0]["subject"] = "QQ"
    with pytest.raises(FlowSpecError, match="unknown alias 'QQ'"):
        flow_from_dict(d)


def test_storage_leak_in_a_flow_is_rejected():
    d = _base_flow_dict()
    d["given"][0]["name"] = "row in the inventory table"
    with pytest.raises(FlowSpecError, match="storage word 'table' leaked"):
        flow_from_dict(d)


def test_representation_leak_in_a_flow_is_rejected():
    d = _base_flow_dict(title="stock read from /api/asset/plant")
    with pytest.raises(FlowSpecError, match="representation term"):
        flow_from_dict(d)


def test_smuggled_expected_value_is_rejected_by_name():
    d = _base_flow_dict()
    d["probes"][0]["value"] = 105
    with pytest.raises(FlowSpecError, match="hand-authored expected value"):
        flow_from_dict(d)


def test_smuggled_then_clause_is_rejected():
    d = _base_flow_dict()
    d["then"] = [{"assert": "stock_on_hand", "subject": "A", "value": 3}]
    with pytest.raises(FlowSpecError, match="hand-authored expected value"):
        flow_from_dict(d)


def test_typo_in_a_key_is_an_error_not_a_silent_drop():
    d = _base_flow_dict()
    d["when"][0]["quantites"] = []
    with pytest.raises(FlowSpecError, match="unknown key"):
        flow_from_dict(d)


def test_missing_required_field_fails_loudly():
    d = _base_flow_dict()
    del d["when"][0]["against"]
    with pytest.raises(FlowSpecError, match="requires 'against'"):
        flow_from_dict(d)


def test_flow_without_probes_fails_loudly():
    d = _base_flow_dict(probes=[])
    with pytest.raises(FlowSpecError, match="observes nothing"):
        flow_from_dict(d)


def test_bad_effective_time_fails_loudly():
    d = _base_flow_dict()
    d["when"][0]["at"] = "yesterday afternoon"
    with pytest.raises(FlowSpecError, match="neither an ISO-8601 instant"):
        flow_from_dict(d)


def test_duplicate_flow_key_fails_loudly(tmp_path):
    d = flow_to_dict(_sample_flow())
    path = tmp_path / "dupe.json"
    path.write_text(json.dumps({"version": 1, "flows": [d, d]}), encoding="utf-8")
    with pytest.raises(FlowSpecError, match="duplicate flow key"):
        load_flows(path)


def test_missing_pack_and_bad_json_fail_loudly(tmp_path):
    with pytest.raises(FlowSpecError, match="no such flow pack"):
        load_flows(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(FlowSpecError, match="not valid JSON"):
        load_flows(bad)


def test_empty_pack_fails_loudly(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"version": 1, "flows": []}), encoding="utf-8")
    with pytest.raises(FlowSpecError, match="nothing to observe"):
        load_flows(p)


def test_unsupported_pack_version_fails_loudly(tmp_path):
    p = tmp_path / "v9.json"
    p.write_text(json.dumps({"version": 9, "flows": []}), encoding="utf-8")
    with pytest.raises(FlowSpecError, match="not the supported pack version"):
        load_flows(p)


def test_effective_time_offset_resolves_relative_to_now():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert resolve_effective_time("-3600", now).hour == 23
    assert resolve_effective_time("+86400", now).day == 2
    assert resolve_effective_time("2026-03-01T12:00:00+00:00", now).month == 3


# --------------------------------------------------------------------------- #
# 3. Stock operations                                                         #
# --------------------------------------------------------------------------- #
def _stock_asset(adapter, name="Store"):
    return adapter.create_asset("planting", name, "Crop")


def test_reset_assigns_and_adjustments_accumulate():
    adapter = _adapter()
    a = _stock_asset(adapter)
    for i, (kind, val) in enumerate(
        [("increment", 10), ("decrement", 4), ("reset", 100), ("increment", 5)]
    ):
        adapter.record_inventory_adjustment(
            kind, f"step {i}", "done", [a], [_q("count", val)],
            resolve_effective_time(f"-{4000 - i * 100}"),
        )
    assert adapter.stock_on_hand(a, "count", "kilogram") == 105


def test_only_effective_adjustments_count():
    """A not-yet-confirmed record, and one dated in the future, both sit out."""
    adapter = _adapter()
    a = _stock_asset(adapter)
    adapter.record_inventory_adjustment(
        "increment", "confirmed", "done", [a], [_q("count", 2)],
        resolve_effective_time("-3600"))
    adapter.record_inventory_adjustment(
        "increment", "unconfirmed", "pending", [a], [_q("count", 3)],
        resolve_effective_time("-1800"))
    adapter.record_inventory_adjustment(
        "increment", "future", "done", [a], [_q("count", 5)],
        resolve_effective_time("+86400"))
    assert adapter.stock_on_hand(a, "count", "kilogram") == 2
    # all three are readable as ledger input even though only one takes effect
    assert adapter.adjustment_count(a) == 3


def test_equal_effective_time_is_broken_by_creation_order():
    at = resolve_effective_time("-3600")
    for order, expected in ((("reset", "increment"), 57), (("increment", "reset"), 50)):
        adapter = _adapter()
        a = _stock_asset(adapter)
        for kind in order:
            adapter.record_inventory_adjustment(
                kind, kind, "done", [a],
                [_q("count", 50 if kind == "reset" else 7)], at)
        assert adapter.stock_on_hand(a, "count", "kilogram") == expected


def test_pairs_are_independent_and_decrements_go_negative():
    adapter = _adapter()
    a = _stock_asset(adapter)
    adapter.record_inventory_adjustment(
        "decrement", "d", "done", [a], [_q("count", 7)],
        resolve_effective_time("-3600"))
    adapter.record_inventory_adjustment(
        "increment", "i", "done", [a], [_q("volume", 2, "liter")],
        resolve_effective_time("-3500"))
    assert adapter.stock_on_hand(a, "count", "kilogram") == -7
    assert adapter.stock_on_hand(a, "volume", "liter") == 2
    assert adapter.stock_pair_count(a) == 2


def test_fractional_adjustment_survives_the_boundary():
    adapter = _adapter()
    a = _stock_asset(adapter)
    adapter.record_inventory_adjustment(
        "increment", "half", "done", [a], [_q("weight", 3.5)],
        resolve_effective_time("-60"))
    assert adapter.stock_on_hand(a, "weight", "kilogram") == 3.5


def test_retracting_a_record_keeps_the_pair_reported_at_zero():
    """Observed: the pair PERSISTS at zero rather than disappearing."""
    adapter = _adapter()
    a = _stock_asset(adapter)
    h = adapter.record_inventory_adjustment(
        "increment", "i", "done", [a], [_q("count", 9)],
        resolve_effective_time("-3600"))
    assert adapter.stock_on_hand(a, "count", "kilogram") == 9
    adapter.set_log_status(h, "pending")
    assert adapter.stock_on_hand(a, "count", "kilogram") == 0
    assert adapter.stock_pair_count(a) == 1  # still reported, at zero


def test_set_effective_time_moves_a_record_out_of_effect():
    adapter = _adapter()
    a = _stock_asset(adapter)
    h = adapter.record_inventory_adjustment(
        "increment", "i", "done", [a], [_q("count", 4)],
        resolve_effective_time("-3600"))
    assert adapter.stock_on_hand(a, "count", "kilogram") == 4
    adapter.set_effective_time(h, resolve_effective_time("+86400"))
    assert adapter.stock_on_hand(a, "count", "kilogram") == 0


def test_stock_is_keyed_on_the_adjusted_asset_not_the_referenced_one():
    adapter = _adapter()
    x = _stock_asset(adapter, "X")
    y = _stock_asset(adapter, "Y")
    adapter.record_inventory_adjustment(
        "increment", "i", "done", [y], [_q("count", 4)],
        resolve_effective_time("-3600"))
    assert adapter.stock_pair_count(x) == 0
    assert adapter.stock_on_hand(y, "count", "kilogram") == 4


def test_missing_surface_never_tells_an_agent_to_destroy_the_shared_oracle():
    """No stock delivered => a named remedy, never a silent zero."""

    class NoInventory(FakeFarmOS):
        def _render_asset(self, res):
            return res  # the module is not installed: no `inventory` at all

    adapter = _adapter(NoInventory())
    a = _stock_asset(adapter)
    # The remedy used to read `docker exec … drush en farm_inventory -y`. The
    # oracle is SHARED: an agent following that instruction takes down every
    # sibling's run. A missing surface is reported, never remediated in place.
    with pytest.raises(AdapterError, match="stock surface is absent") as exc:
        adapter.stock_on_hand(a, "count", "kilogram")
    for destructive in ("drush", "docker exec", "bring-up.sh"):
        assert f"`{destructive}" not in str(exc.value)
    assert "Do NOT run docker" in str(exc.value)


# --------------------------------------------------------------------------- #
# 4. Lineage operations                                                       #
# --------------------------------------------------------------------------- #
def _animal(adapter, name, sex=""):
    return adapter.create_asset("animal", name, "Cattle", sex)


def test_registering_an_animal_carries_its_sex():
    adapter = _adapter()
    m = _animal(adapter, "Mother1", "F")
    assert adapter.animal_sex(m) == "F"
    assert adapter.nicknames(m) == []


def test_birth_sets_the_date_of_birth_and_appends_the_parent():
    adapter = _adapter()
    mother = _animal(adapter, "Mother1", "F")
    calf = _animal(adapter, "Calf1")
    adapter.record_birth(calf, [mother], "birth of Calf1", "done",
                         resolve_effective_time("2026-03-01T12:00:00+00:00"))
    assert adapter.birth_date(calf).startswith("2026-03-01T12:00")
    assert adapter.parent_count(calf) == 1
    assert adapter.has_parent(calf, mother) is True


def test_correcting_a_birth_moves_the_date_but_vetoes_the_parentage():
    """The observed source rule: birth-derived parentage appends only if empty."""
    adapter = _adapter()
    m1 = _animal(adapter, "Mother1", "F")
    m2 = _animal(adapter, "Mother2", "F")
    calf = _animal(adapter, "Calf1")
    birth = adapter.record_birth(calf, [m1], "birth", "done",
                                 resolve_effective_time("2026-03-01T12:00:00+00:00"))
    adapter.correct_birth(birth, [m2],
                          resolve_effective_time("2026-03-02T09:00:00+00:00"))
    assert adapter.birth_date(calf).startswith("2026-03-02T09:00")
    assert adapter.has_parent(calf, m1) is True   # NOT overwritten
    assert adapter.has_parent(calf, m2) is False


def test_stating_parentage_directly_fully_replaces_it():
    adapter = _adapter()
    m1 = _animal(adapter, "Mother1", "F")
    m2 = _animal(adapter, "Mother2", "F")
    calf = _animal(adapter, "Calf1")
    adapter.set_parents(calf, [m1])
    assert adapter.has_parent(calf, m1) is True
    adapter.set_parents(calf, [m2])
    assert (adapter.has_parent(calf, m1), adapter.has_parent(calf, m2)) == (False, True)
    adapter.set_parents(calf, [])
    assert adapter.parent_count(calf) == 0
    adapter.set_parents(calf, [m1, m2])
    assert adapter.parent_count(calf) == 2


def test_a_cleared_parentage_then_accepts_the_corrected_parent():
    adapter = _adapter()
    m1 = _animal(adapter, "Mother1", "F")
    m2 = _animal(adapter, "Mother2", "F")
    calf = _animal(adapter, "Calf1")
    birth = adapter.record_birth(calf, [m1], "birth", "done",
                                 resolve_effective_time("2026-03-01T12:00:00+00:00"))
    adapter.correct_birth(birth, [m2])
    adapter.set_parents(calf, [])
    adapter.correct_birth(birth, [m2])
    assert adapter.has_parent(calf, m2) is True


def test_nicknames_keep_order_and_duplicates_and_fully_replace():
    adapter = _adapter()
    a = _animal(adapter, "Bessie", "F")
    adapter.set_nicknames(a, ["Bessie", "Bess", "Bessie", "Bess"])
    assert adapter.nicknames(a) == ["Bessie", "Bess", "Bessie", "Bess"]
    adapter.set_nicknames(a, ["Zed", "Ace", "Zed"])
    assert adapter.nicknames(a) == ["Zed", "Ace", "Zed"]
    adapter.set_nicknames(a, [])
    assert adapter.nicknames(a) == []


def test_birth_uniqueness_holds_on_registration_but_not_on_correction():
    adapter = _adapter()
    m = _animal(adapter, "Mother1", "F")
    calf = _animal(adapter, "Calf1")
    adapter.record_birth(calf, [m], "birth", "done",
                         resolve_effective_time("2026-03-01T12:00:00+00:00"))
    assert adapter.birth_record_count(calf) == 1
    with pytest.raises(AdapterError):
        adapter.record_birth(calf, [m], "second birth", "done",
                             resolve_effective_time("2026-03-05T12:00:00+00:00"))
    assert adapter.birth_record_count(calf) == 1


def test_missing_birth_surface_is_reported_with_the_fix():
    class NoBirth(FakeFarmOS):
        def _create(self, entity, bundle, doc):
            if entity == "log" and bundle == "birth":
                raise AdapterError("POST /api/log/birth -> 404")
            return super()._create(entity, bundle, doc)

    adapter = _adapter(NoBirth())
    calf = _animal(adapter, "Calf1")
    with pytest.raises(AdapterError, match="birth-record surface is absent") as exc:
        adapter.record_birth(calf, [], "birth", "done", None)
    for destructive in ("drush", "docker", "bring-up.sh"):
        assert f"`{destructive}" not in str(exc.value)
    assert "expect_refusal" in str(exc.value)
    assert "Do NOT run docker" in str(exc.value)


# --------------------------------------------------------------------------- #
# 5. End to end: a supplied pack records, distils, validates, self-verifies    #
# --------------------------------------------------------------------------- #
_PACK = {
    "version": 1,
    "flows": [
        {
            "key": "stock-reset-then-increment",
            "title": "A stock reset assigns a base that a later increment builds on",
            "feature": "stock-adjustment",
            "glossary_terms": ["planting", "count", "stock_on_hand", "reset",
                               "increment", "record_inventory_adjustment"],
            "given": [{"entity": "planting", "alias": "A", "name": "Seed Store",
                       "descriptor": "Crop"}],
            "when": [
                {"action": "record_inventory_adjustment", "alias": "L1",
                 "kind": "increment", "status": "done", "name": "delivery",
                 "against": ["A"], "at": "-7200",
                 "quantities": [{"measure": "count", "value": 10,
                                 "unit": "kilogram"}]},
                {"action": "record_inventory_adjustment", "alias": "L2",
                 "kind": "reset", "status": "done", "name": "stocktake",
                 "against": ["A"], "at": "-3600",
                 "quantities": [{"measure": "count", "value": 100,
                                 "unit": "kilogram"}]},
                {"action": "record_inventory_adjustment", "alias": "L3",
                 "kind": "increment", "status": "done", "name": "top up",
                 "against": ["A"], "at": "-1800",
                 "quantities": [{"measure": "count", "value": 5,
                                 "unit": "kilogram"}]},
            ],
            "probes": [
                {"assert": "stock_on_hand", "subject": "A", "measure": "count",
                 "unit": "kilogram"},
                {"assert": "stock_pair_count", "subject": "A"},
                {"assert": "adjustment_count", "subject": "A"},
                {"assert": "log_status", "subject": "L2"},
            ],
        },
        {
            "key": "birth-correction-vetoes-parentage",
            "title": "Correcting a birth moves the date of birth but not the parent",
            "feature": "lineage",
            "glossary_terms": ["animal", "birth", "birth_date", "has_parent",
                               "parent_count", "record_birth", "correct_birth"],
            "given": [
                {"entity": "animal", "alias": "M1", "name": "Mother1",
                 "descriptor": "Cattle", "sex": "F"},
                {"entity": "animal", "alias": "M2", "name": "Mother2",
                 "descriptor": "Cattle", "sex": "F"},
                {"entity": "animal", "alias": "C", "name": "Calf1",
                 "descriptor": "Cattle"},
            ],
            "when": [
                {"action": "record_birth", "alias": "B", "ref": "C",
                 "parents": ["M1"], "name": "birth of Calf1", "status": "done",
                 "at": "2026-03-01T12:00:00+00:00"},
                {"action": "correct_birth", "ref": "B", "parents": ["M2"],
                 "at": "2026-03-02T09:00:00+00:00"},
                {"action": "set_nicknames", "ref": "C",
                 "names": ["Spot", "Spotty", "Spot"]},
            ],
            "probes": [
                {"assert": "birth_date", "subject": "C"},
                {"assert": "has_parent", "subject": "C", "other": "M1"},
                {"assert": "has_parent", "subject": "C", "other": "M2"},
                {"assert": "parent_count", "subject": "C"},
                {"assert": "nicknames", "subject": "C"},
                {"assert": "animal_sex", "subject": "M1"},
                {"assert": "birth_record_count", "subject": "C"},
            ],
        },
    ],
}


def test_supplied_pack_records_distils_and_self_verifies(tmp_path):
    path = tmp_path / "w0.json"
    path.write_text(json.dumps(_PACK), encoding="utf-8")
    flows = load_flows(path)
    assert [f.key for f in flows] == ["stock-reset-then-increment",
                                      "birth-correction-vetoes-parentage"]

    fixtures = []
    for flow in flows:
        fx, obs = record_flow(_adapter(), flow)
        assert obs, "a recorded flow must cite its observations"
        assert validate_fixture(fx) == [], fx.title
        fixtures.append(fx)

    # Every expected value was FILLED FROM OBSERVATION, and it is the value the
    # modelled boundary actually delivers.
    stock = {t.assert_: t.value for t in fixtures[0].then}
    assert stock["stock_on_hand"] == 105
    assert stock["stock_pair_count"] == 1
    assert stock["adjustment_count"] == 3
    assert stock["log_status"] == "done"

    lineage = fixtures[1].then
    assert next(t.value for t in lineage if t.assert_ == "birth_date").startswith(
        "2026-03-02T09:00")
    parents = {t.other: t.value for t in lineage if t.assert_ == "has_parent"}
    assert parents == {"M1": True, "M2": False}
    assert next(t.value for t in lineage if t.assert_ == "nicknames") == [
        "Spot", "Spotty", "Spot"]
    assert next(t.value for t in lineage if t.assert_ == "animal_sex") == "F"

    # ... and a replay against a fresh instance of the same system reproduces them.
    summary = run_fixtures(_adapter(), fixtures)
    assert summary.pass_rate == 1.0, [
        (r.title, r.error, [(a.assertion, a.expected, a.actual)
                            for a in r.assertions if not a.passed])
        for r in summary.results if not r.passed
    ]


def test_unsupported_operation_raises_rather_than_returning_a_value():
    """An adapter without a capability must say so — never deliver a default."""
    from ctkr.oracle.adapter import ImplementationAdapter

    class Bare(ImplementationAdapter):
        name = "bare"
        create_asset = record_log = set_log_status = None  # type: ignore[assignment]
        assign_to_group = archive_asset = asset_yield_total = None  # type: ignore
        log_status = log_count = asset_active = None  # type: ignore[assignment]
        group_member = quantity_recorded = None  # type: ignore[assignment]

    bare = Bare()
    for op in ("stock_on_hand", "stock_pair_count", "adjustment_count",
               "animal_sex", "nicknames", "birth_date", "parent_count",
               "birth_record_count"):
        with pytest.raises(AdapterError, match=op):
            getattr(bare, op)("handle") if op != "stock_on_hand" else \
                bare.stock_on_hand("handle", "count", "kilogram")


# --------------------------------------------------------------------------- #
# 6. The shipped w0 reference pack                                            #
# --------------------------------------------------------------------------- #
def _w0_pack_path():
    from pathlib import Path

    import ctkr.oracle

    return Path(ctkr.oracle.__file__).parent / "data" / "w0_flows.json"


def test_shipped_w0_pack_loads_records_and_self_verifies():
    """The pack the wave-0 fan-out starts from must survive the whole loop."""
    flows = load_flows(_w0_pack_path())
    assert len(flows) >= 10
    fixtures = []
    for flow in flows:
        fx, _obs = record_flow(_adapter(), flow)
        assert validate_fixture(fx) == [], fx.title
        assert fx.then, f"{flow.key} distilled no assertion"
        fixtures.append(fx)
    summary = run_fixtures(_adapter(), fixtures)
    assert summary.pass_rate == 1.0, [
        (r.title, r.error, [(a.assertion, a.expected, a.actual)
                            for a in r.assertions if not a.passed])
        for r in summary.results if not r.passed
    ]


def test_cli_flow_selection_covers_every_pack(tmp_path):
    import argparse

    from ctkr.commands.oracle_record import _select_flows

    def ns(**kw):
        return argparse.Namespace(flows="", pack="core", **kw)

    assert len(_select_flows(ns())[0]) == len(core_flows())
    assert len(_select_flows(argparse.Namespace(flows="", pack="hardening"))[0]) == \
        len(hardening_flows())
    assert len(_select_flows(argparse.Namespace(flows="", pack="all"))[0]) == \
        len(core_flows()) + len(hardening_flows())
    supplied = tmp_path / "p.json"
    supplied.write_text(json.dumps(_PACK), encoding="utf-8")
    flows, origin = _select_flows(
        argparse.Namespace(flows=str(supplied), pack="core"))
    assert len(flows) == 2 and str(supplied) in origin


def test_cli_rejects_a_bad_pack_before_touching_the_oracle(tmp_path, capsys):
    import argparse

    from ctkr.commands.oracle_record import run

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 1, "flows": [
        {"key": "k", "title": "t", "given": [], "when": [],
         "probes": [{"assert": "teleported", "subject": "A"}]}]}), encoding="utf-8")
    args = argparse.Namespace(
        flows=str(bad), pack="core", base_url="http://unreachable.invalid",
        username="admin", password="admin", client_id="farm", client_secret="",
        out_dir=str(tmp_path), preflight_timeout=0.1, skip_preflight=False,
    )
    assert run(args) == 2
    assert "INVALID FLOW PACK" in capsys.readouterr().err
