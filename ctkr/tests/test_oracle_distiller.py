"""Recorder/distiller + farmOS-adapter tests over a canned in-memory JSON:API.

``FakeFarmOSTransport`` simulates exactly the JSON:API subset the FarmOS adapter
speaks (asset/log/quantity/term create, status PATCH, filtered queries with
``include``), so the whole record → distil → verify pipeline runs with **no
Docker**. This is the offline acceptance test of the adapter's request shapes
and the distiller's value extraction.
"""

from __future__ import annotations

import json
import urllib.parse

from ctkr.oracle.farmos_adapter import FarmOSAdapter
from ctkr.oracle.fixtures import validate_fixture
from ctkr.oracle.recorder import (
    RecordingClient,
    core_flows,
    record_flow,
    record_session,
)
from ctkr.oracle.runner import run_fixtures


class FakeFarmOSTransport:
    """In-memory farmOS JSON:API — enough of it for the oracle's value-flows."""

    def __init__(self) -> None:
        self.assets: dict[str, dict] = {}
        self.logs: dict[str, dict] = {}
        self.quantities: dict[str, dict] = {}
        self.terms: dict[str, dict] = {}
        self._n = 0

    def _id(self) -> str:
        self._n += 1
        return f"id-{self._n:04d}"

    def __call__(self, method, path, body, headers):
        doc = json.loads(body) if body and path != "/oauth/token" else None
        parsed = urllib.parse.urlparse(path)
        segs = [s for s in parsed.path.split("/") if s]
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/oauth/token":
            return json.dumps({"access_token": "faketoken", "expires_in": 3600})

        # /api/<entity>/<bundle>[/<id>]
        entity = segs[1]
        bundle = segs[2] if len(segs) > 2 else None
        rid = segs[3] if len(segs) > 3 else None

        if method == "POST":
            return self._create(entity, bundle, doc)
        if method == "PATCH":
            return self._patch(entity, bundle, rid, doc)
        if method == "GET":
            return self._get(entity, bundle, rid, qs)
        raise AssertionError(f"unexpected {method} {path}")

    # ---- writes ------------------------------------------------------------ #
    def _create(self, entity, bundle, doc):
        rid = self._id()
        data = doc["data"]
        attrs = data.get("attributes", {})
        rels = data.get("relationships", {})
        store = getattr(self, {"asset": "assets", "log": "logs",
                               "quantity": "quantities",
                               "taxonomy_term": "terms"}[entity])
        store[rid] = {"type": data["type"], "id": rid, "bundle": bundle,
                      "attributes": attrs, "relationships": rels}
        return json.dumps({"data": store[rid]})

    def _patch(self, entity, bundle, rid, doc):
        store = getattr(self, {"asset": "assets", "log": "logs"}[entity])
        store[rid]["attributes"].update(doc["data"].get("attributes", {}))
        return json.dumps({"data": store[rid]})

    # ---- reads ------------------------------------------------------------- #
    def _rel_ids(self, resource, rel):
        data = (resource["relationships"].get(rel) or {}).get("data")
        if not data:
            return []
        return [data["id"]] if isinstance(data, dict) else [d["id"] for d in data]

    def _term_find(self, bundle, qs):
        want = qs.get("filter[name]", [None])[0]
        rows = [t for t in self.terms.values()
                if t["bundle"] == bundle and (want is None
                                              or t["attributes"].get("name") == want)]
        return json.dumps({"data": rows})

    def _get(self, entity, bundle, rid, qs):
        if entity == "taxonomy_term" and rid is None:
            return self._term_find(bundle, qs)

        include = set()
        for inc in qs.get("include", []):
            include.update(inc.split(","))

        if entity == "asset":
            if rid:
                return json.dumps({"data": self.assets[rid]})
        if entity == "log":
            if rid:
                res = self.logs[rid]
                return json.dumps({"data": res,
                                   "included": self._included(res, include)})
            rows = self._filter_logs(bundle, qs)
            included = []
            for r in rows:
                included.extend(self._included(r, include))
            return json.dumps({"data": rows, "included": included})
        raise AssertionError(f"unhandled GET {entity}/{bundle}/{rid}")

    def _filter_logs(self, bundle, qs):
        rows = [lg for lg in self.logs.values() if lg["bundle"] == bundle]
        aid = qs.get("filter[asset.id]", [None])[0]
        if aid is not None:
            rows = [r for r in rows if aid in self._rel_ids(r, "asset")]
        status = qs.get("filter[status]", [None])[0]
        if status is not None:
            rows = [r for r in rows if r["attributes"].get("status") == status]
        if qs.get("filter[is_group_assignment]", [None])[0] is not None:
            rows = [r for r in rows
                    if r["attributes"].get("is_group_assignment")]
        return rows

    def _included(self, log, include):
        out = []
        if "quantity" in include:
            for qid in self._rel_ids(log, "quantity"):
                q = self.quantities[qid]
                out.append(q)
                if "quantity.units" in include:
                    for uid in self._rel_ids(q, "units"):
                        out.append(self.terms[uid])
        if "group" in include:
            for gid in self._rel_ids(log, "group"):
                out.append(self.assets[gid])
        return out


def _adapter():
    client = RecordingClient("http://fake", "admin", "admin",
                             transport=FakeFarmOSTransport())
    return FarmOSAdapter(client)


def test_full_record_verify_pipeline_self_verifies():
    # Record against the fake farmOS ...
    adapter = _adapter()
    fixtures, observations = record_session(adapter)
    assert len(fixtures) == len(core_flows())
    assert observations, "expected recorded observations (provenance)"

    # ... every distilled fixture is valid + storage-free ...
    for fx in fixtures:
        assert validate_fixture(fx) == [], fx.title
        assert fx.provenance.observation_refs, "fixture must cite its observations"

    # ... and self-verifies against a fresh instance of the same system.
    verify_adapter = _adapter()
    summary = run_fixtures(verify_adapter, fixtures)
    assert summary.pass_rate == 1.0, [
        (r.title, r.error, [(a.assertion, a.expected, a.actual)
                            for a in r.assertions if not a.passed])
        for r in summary.results if not r.passed
    ]


def test_distilled_values_come_from_observation():
    adapter = _adapter()
    flow = next(f for f in core_flows() if f.key == "harvest-yield-single")
    adapter.open()
    fx, obs = record_flow(adapter, flow)
    yt = next(t for t in fx.then if t.assert_ == "yield_total")
    assert yt.value == 5  # observed from the fake boundary, not hand-authored
    lc = next(t for t in fx.then if t.assert_ == "log_count")
    assert lc.value == 1
    assert obs  # request/response pairs captured


def test_yield_accumulates_flow():
    adapter = _adapter()
    flow = next(f for f in core_flows() if f.key == "harvest-yield-accumulates")
    adapter.open()
    fx, _ = record_flow(adapter, flow)
    yt = next(t for t in fx.then if t.assert_ == "yield_total")
    assert yt.value == 7  # 3 + 4 summed at the boundary


def test_status_transition_flow():
    adapter = _adapter()
    flow = next(f for f in core_flows() if f.key == "log-status-transition")
    adapter.open()
    fx, _ = record_flow(adapter, flow)
    st = next(t for t in fx.then if t.assert_ == "log_status")
    assert st.value == "done"
