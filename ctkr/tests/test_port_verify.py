"""Hermetic tests for ``ctkr port-verify`` — no Docker, no oracle, no network.

Every test drives a FAKE in-process bridge, so what is under test is the judge
and its honesty rules, not a port and not a live system.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ctkr.oracle import glossary
from ctkr.oracle.adapter import ImplementationAdapter
from ctkr.oracle.fixtures import SemanticFixture
from ctkr.oracle.port_adapter import PortAdapter, Unanswerable
from ctkr.oracle.pack import Pack, PackSeal
from ctkr.oracle.port_contract import ContractError, Divergence, PortManifest
from ctkr.oracle.port_verify import (
    AssertionStatus,
    PortScore,
    PortVerifyReport,
    score_verdicts,
    verify_port,
)
from ctkr.oracle.probes import (
    OPERATION_CONTRACT,
    PROBE_CONTRACT,
    contract_gaps,
    methods_for_action,
)


# --------------------------------------------------------------------------- #
# A fake port: an in-memory running balance with a configurable probe surface  #
# --------------------------------------------------------------------------- #
class FakeBridge:
    """Answers the bridge protocol in-process. ``values`` overrides any probe."""

    def __init__(
        self,
        operations: list[str],
        probes: list[str],
        overrides: dict[str, Any] | None = None,
        refuse: set[str] | None = None,
    ) -> None:
        self.operations = operations
        self.probes = probes
        self.overrides = overrides or {}
        self.refuse = refuse or set()
        self.calls: list[str] = []
        self._assets: list[str] = []
        self._adj: list[dict[str, Any]] = []

    def start(self) -> None:  # pragma: no cover — protocol parity
        pass

    def stop(self) -> None:
        pass

    def call(self, op: str, **payload: Any) -> Any:
        self.calls.append(op)
        if op in self.refuse:
            raise _Unsupported(op)
        if op == "describe":
            return {"operations": self.operations, "probes": self.probes}
        if op == "reset":
            self._assets, self._adj = [], []
            return True
        if op == "create_asset":
            h = f"A{len(self._assets) + 1}"
            self._assets.append(h)
            return h
        if op == "record_inventory_adjustment":
            for asset in payload["assets"]:
                for q in payload["quantities"]:
                    self._adj.append({
                        "asset": asset, "kind": payload["adjustment"],
                        "status": payload["status"], "measure": q["measure"],
                        "unit": q["unit"], "value": q["value"],
                    })
            return f"L{len(self._adj)}"
        if op in self.overrides:
            return self.overrides[op]
        if op == "stock_on_hand":
            total = 0.0
            for a in self._adj:
                if (a["asset"], a["measure"], a["unit"]) != (
                    payload["asset"], payload["measure"], payload["unit"]
                ) or a["status"] != "done":
                    continue
                if a["kind"] == "reset":
                    total = a["value"]
                elif a["kind"] == "increment":
                    total += a["value"]
                else:
                    total -= a["value"]
            return total
        if op == "stock_pair_count":
            return len({(a["measure"], a["unit"]) for a in self._adj
                        if a["asset"] == payload["asset"]})
        if op == "adjustment_count":
            return sum(1 for a in self._adj if a["asset"] == payload["asset"])
        if op == "close":
            return True
        raise _Unsupported(op)


class _Unsupported(Exception):
    def __init__(self, op: str) -> None:
        super().__init__(op)


#: An override that makes the fake decline ONE call while still declaring the
#: probe — mirrors a real bridge answering {"unanswerable": "..."}.
_PER_CALL_GAP = {"unanswerable": "no holding row for this (measure, unit) pair"}


def _bridge_call_wrapper(bridge: FakeBridge) -> FakeBridge:
    """Translate the fake's refusals into the adapter's FalseDeclaration, and its
    per-call declines into Unanswerable — the same two channels the real bridge
    protocol distinguishes."""
    from ctkr.oracle.port_adapter import FalseDeclaration

    raw = bridge.call

    def call(op: str, **payload: Any) -> Any:
        try:
            value = raw(op, **payload)
            if isinstance(value, dict) and "unanswerable" in value:
                raise Unanswerable(f"{op}: {value['unanswerable']}")
            return value
        except _Unsupported as exc:
            raise FalseDeclaration(
                f"port declared {op!r} but its bridge refuses it: {exc}"
            ) from exc

    bridge.call = call  # type: ignore[method-assign]
    return bridge


def make_manifest(
    operations: list[str],
    probes: list[str],
    divergences: list[Divergence] | None = None,
) -> PortManifest:
    return PortManifest(
        port="fake",
        bridge={"command": ["true"]},
        capabilities={"operations": operations, "probes": probes},
        divergences=divergences or [],
    )


def pack(fixtures, invalid=()) -> Pack:
    """An in-memory sealed pack. `verify_port` takes NOTHING else that can move
    the score, which is the point: there is no `marks` argument to pass."""
    return Pack(path=Path("t/fixtures.jsonl"),
                seal=PackSeal(fixture_ids=[f.fixture_id for f in fixtures]).sealed(),
                fixtures=list(fixtures), invalid=list(invalid))


def make_adapter(
    operations: list[str],
    probes: list[str],
    manifest: PortManifest | None = None,
    overrides: dict[str, Any] | None = None,
    refuse: set[str] | None = None,
) -> PortAdapter:
    manifest = manifest or make_manifest(operations, probes)
    bridge = _bridge_call_wrapper(FakeBridge(operations, probes, overrides, refuse))
    return PortAdapter(manifest, bridge=bridge)


# --------------------------------------------------------------------------- #
# Fixture builders                                                            #
# --------------------------------------------------------------------------- #
def fixture(
    fid: str,
    then: list[dict[str, Any]],
    when: list[dict[str, Any]] | None = None,
    title: str = "a scenario",
) -> SemanticFixture:
    return SemanticFixture.model_validate({
        "fixture_id": fid,
        "title": title,
        "feature": "core.inventory",
        "given": [{"entity": "equipment", "alias": "bin", "name": "feed bin"}],
        "when": when if when is not None else [{
            "action": "record_inventory_adjustment", "alias": "adj",
            "kind": "increment", "status": "done", "against": ["bin"],
            "quantities": [{"measure": "weight", "value": 4.0,
                            "unit": "kilograms"}],
        }],
        "then": then,
        "provenance": {"source_system": "farmOS", "flow": "t"},
    })


def soh(value: float) -> dict[str, Any]:
    return {"assert": "stock_on_hand", "subject": "bin", "measure": "weight",
            "unit": "kilograms", "op": "==", "value": value}


def adjcount(value: int) -> dict[str, Any]:
    return {"assert": "adjustment_count", "subject": "bin", "op": "==",
            "value": value}


ALL_OPS = ["record_inventory_adjustment"]


# --------------------------------------------------------------------------- #
# 1. The probe-surface contract itself                                         #
# --------------------------------------------------------------------------- #
def test_contract_covers_the_glossary_exactly() -> None:
    assert contract_gaps() == []
    assert set(PROBE_CONTRACT) == set(glossary.ASSERTION_TERMS)
    assert set(OPERATION_CONTRACT) == set(glossary.ACTION_TERMS)


def test_every_contract_method_exists_on_the_adapter_abc() -> None:
    for spec in PROBE_CONTRACT.values():
        if spec.subject_kind == "attempt":
            # Answered by whether the write was refused, not by a read-back call.
            assert spec.method == "", spec
            continue
        assert hasattr(ImplementationAdapter, spec.method), spec
    for action in OPERATION_CONTRACT:
        for method in methods_for_action(action, timed=True):
            assert hasattr(ImplementationAdapter, method), (action, method)


def test_probe_params_name_real_assertion_fields() -> None:
    from ctkr.oracle.fixtures import ThenAssertion

    for spec in PROBE_CONTRACT.values():
        for p in spec.params:
            assert p.field_name in ThenAssertion.model_fields, (spec, p)


def test_timed_record_log_needs_the_restatement_verb() -> None:
    assert methods_for_action("record_log") == ("record_log",)
    assert methods_for_action("record_log", timed=True) == (
        "record_log", "set_effective_time",
    )


def test_adapter_never_calls_an_undeclared_probe() -> None:
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"])
    with pytest.raises(Unanswerable):
        adapter.adjustment_count("A1")
    assert "adjustment_count" not in adapter._bridge.calls  # noqa: SLF001


# --------------------------------------------------------------------------- #
# 2. An unanswerable assertion is a declared gap                               #
# --------------------------------------------------------------------------- #
def test_unanswerable_probe_is_a_gap_not_a_pass() -> None:
    fx = fixture("f1", [soh(4.0), adjcount(1)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)

    statuses = [o.status for o in report.verdicts[0].outcomes]
    assert statuses == [AssertionStatus.PASSED, AssertionStatus.NO_VERDICT]
    # Reported, not dropped: the assertion is still in the output.
    assert len(report.verdicts[0].outcomes) == 2
    s = report.score
    assert (s.assertions_total, s.answered, s.no_verdict) == (2, 1, 1)
    assert s.scored_answered == 1 and s.scored_passed == 1
    # The value score's denominator is never the pack size.
    assert s.value_score == 1.0
    assert s.coverage == 0.5
    assert not report.clean  # a gap is never a green


def test_an_undeclared_operation_makes_the_whole_fixture_unanswerable() -> None:
    fx = fixture(
        "f2", [soh(4.0)],
        when=[{"action": "set_log_status", "ref": "adj", "status": "done"}],
    )
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)
    v = report.verdicts[0]
    assert v.ran is False
    assert [o.status for o in v.outcomes] == [AssertionStatus.NO_VERDICT]
    assert "set_log_status" in v.error
    assert report.score.scored_answered == 0


def test_headline_cannot_be_quoted_as_one_number() -> None:
    fx = fixture("f1", [soh(4.0), adjcount(1)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)
    headline = report.score.headline()
    assert "1/1" in headline and "1/2 NO VERDICT" in headline
    dumped = json.loads(report.model_dump_json())
    assert "pass_rate" not in json.dumps(dumped)


# --------------------------------------------------------------------------- #
# 3. Divergences: declared up front, never inferred                            #
# --------------------------------------------------------------------------- #
def _diverging_setup(port_value: float, declared: list[Divergence]):
    fx = fixture("f3", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=declared)
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": port_value})
    return verify_port(adapter, pack([fx]), manifest)


def test_declared_divergence_is_accepted() -> None:
    report = _diverging_setup(9.0, [Divergence.model_validate({
        "fixture_id": "f3", "assert": "stock_on_hand", "subject": "bin",
        "port_value": 9.0, "reason": "pending-bearing numerics, kernel v1.2",
        "decision_id": "kernel-v1.2",
    })])
    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.DIVERGED
    assert o.decision_id == "kernel-v1.2"
    assert report.score.scored_failed == 0
    assert report.score.scored_diverged == 1
    assert report.score.scored_passed == 0  # counted apart from real passes
    assert report.declaration_problems == []


def test_undeclared_mismatch_fails() -> None:
    report = _diverging_setup(9.0, [])
    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.FAILED
    assert o.detail == "undeclared mismatch"
    assert report.score.scored_failed == 1


def test_a_divergence_covers_one_stated_value_only() -> None:
    report = _diverging_setup(11.0, [Divergence.model_validate({
        "fixture_id": "f3", "assert": "stock_on_hand", "subject": "bin",
        "port_value": 9.0, "reason": "pending-bearing numerics", "decision_id": "pending-status-gates",
    })])
    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.FAILED
    assert "declared divergence expects 9.0" in o.detail


def test_a_divergence_cannot_launder_an_unanswerable_assertion() -> None:
    fx = fixture("f4", [adjcount(1)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=[
        Divergence.model_validate({
            "fixture_id": "f4", "assert": "adjustment_count", "subject": "bin",
            "port_value": 99, "reason": "we would differ here if we had it", "decision_id": "pending-status-gates",
        })
    ])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)
    assert report.verdicts[0].outcomes[0].status == AssertionStatus.NO_VERDICT
    assert report.score.scored_diverged == 0


def test_a_divergence_that_did_not_fire_is_a_declaration_problem() -> None:
    report = _diverging_setup(4.0, [Divergence.model_validate({
        "fixture_id": "f3", "assert": "stock_on_hand", "subject": "bin",
        "port_value": 9.0, "reason": "stale sanction", "decision_id": "pending-status-gates",
    })])
    assert report.verdicts[0].outcomes[0].status == AssertionStatus.PASSED
    assert any("stale" in p for p in report.declaration_problems)
    assert not report.clean


def test_a_divergence_for_a_fixture_outside_the_pack_is_reported() -> None:
    fx = fixture("f3", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=[
        Divergence.model_validate({
            "fixture_id": "not-in-pack", "assert": "stock_on_hand",
            "port_value": 1.0, "reason": "wrong pack", "decision_id": "pending-status-gates",
        })
    ])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)
    assert any("not in this pack" in p for p in report.declaration_problems)


def test_a_divergence_needs_a_reason_and_a_port_value() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Divergence.model_validate({"fixture_id": "f", "assert": "stock_on_hand",
                                   "reason": "no port_value given", "decision_id": "d"})
    m = PortManifest(port="p", bridge={"command": ["true"]},
                     capabilities={"operations": [], "probes": []})
    m.divergences = [Divergence.model_validate({
        "fixture_id": "f", "assert": "stock_on_hand", "port_value": 1.0,
        "reason": "   ", "decision_id": "d",
    })]
    with pytest.raises(ContractError):
        m.check()


# --------------------------------------------------------------------------- #
# 4. Corroboration-only fixtures are reported but never scored                 #
# --------------------------------------------------------------------------- #
def corroboration(fid: str, then, title="order-sensitive"):
    """A fixture the RECORDER classified as corroboration-only, inside the pack.

    This is now the ONLY way a fixture can be excluded from the value score, and
    the port has no hand in it: the class travels in the sealed pack's provenance.
    """
    fx = fixture(fid, then, title=title)
    fx.provenance.evidence_class = "corroboration-only"
    fx.provenance.evidence_note = "value encodes source insertion order"
    return fx


def test_corroboration_only_fixture_is_reported_but_excluded() -> None:
    ok = fixture("keep", [soh(4.0)])
    corr = corroboration("order", [soh(999.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([ok, corr]), manifest)

    excluded = report.verdicts[1]
    assert excluded.scored is False
    # Still executed and still reported — with its real (failing) comparison.
    assert len(excluded.outcomes) == 1
    assert excluded.outcomes[0].status == AssertionStatus.FAILED
    assert excluded.outcomes[0].scored is False

    s = report.score
    assert s.assertions_total == 2
    assert s.answered == 2
    assert s.excluded_corroboration == 1
    assert s.scored_answered == 1
    assert s.scored_failed == 0  # the order-sensitive value condemns nothing
    assert s.value_score == 1.0
    assert s.fixtures_excluded == 1


def test_an_order_sensitive_fixture_cannot_pass_for_the_wrong_reason() -> None:
    """Even when it MATCHES, an excluded fixture adds nothing to the score."""
    fx = corroboration("order", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)
    assert report.verdicts[0].outcomes[0].status == AssertionStatus.PASSED
    assert report.score.scored_answered == 0
    assert report.score.scored_passed == 0


# ---- INVARIANT 2: the defendant holds no pen that touches the verdict ------- #
def test_a_port_manifest_cannot_carry_fixture_marks() -> None:
    """C2. The attack, in full: a deliberately-broken port scored
    `passed 25 / failed 5 / reproduced 83.3% / EXIT=1`. Adding five
    `corroboration_only` marks with a plausible reason to the port's OWN
    manifest produced `scored 18 (12 excluded) / failed 0 / reproduced 100.0% /
    clean=true / EXIT=0`, with the five FAILs still printed in the body.

    The fix is not a check. The field does not exist, so the manifest that
    carries it does not load at all.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PortManifest.model_validate({
            "port": "liar",
            "bridge": {"command": ["true"]},
            "capabilities": {"operations": ALL_OPS, "probes": ["stock_on_hand"]},
            "fixture_marks": [{"fixture_id": "f1", "corroboration_only": True,
                               "reason": "order-sensitive, honest"}],
        })


def test_there_is_no_marks_parameter_to_verify_port() -> None:
    """A5/C2, structurally: no caller — port author, agent, or CLI — can hand
    the judge a list of fixtures that do not count."""
    import inspect

    params = set(inspect.signature(verify_port).parameters)
    assert params == {"adapter", "pack", "manifest", "decisions"}
    assert "marks" not in json.dumps(sorted(params))


def test_a_port_cannot_choose_a_subset_of_the_pack() -> None:
    """A5. `sed -n '4,7p'` of a pack gave `coverage 10/10 = 100.0%, clean`.

    A pack now states its own extent, in a seal its recorder wrote; judging is
    against the whole artifact, and `load_pack` is the only door in.
    """
    import inspect

    from ctkr.oracle import pack as pack_mod

    src = inspect.getsource(pack_mod.load_pack)
    assert "is judged whole" in src
    assert "does not match its seal" in src


# --------------------------------------------------------------------------- #
# 5. Declarations must be true                                                 #
# --------------------------------------------------------------------------- #
def test_manifest_and_bridge_must_agree_about_the_surface() -> None:
    manifest = make_manifest(ALL_OPS, ["stock_on_hand", "adjustment_count"])
    adapter = PortAdapter(
        manifest,
        bridge=_bridge_call_wrapper(FakeBridge(ALL_OPS, ["stock_on_hand"])),
    )
    with pytest.raises(Exception) as exc:
        adapter.open()
    assert "disagree about the probe surface" in str(exc.value)


def test_a_declared_but_refused_probe_fails_and_is_not_a_gap() -> None:
    fx = fixture("f5", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           refuse={"stock_on_hand"})
    report = verify_port(adapter, pack([fx]), manifest)
    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.FAILED
    assert report.score.no_verdict == 0
    assert any("refuses it" in p for p in report.declaration_problems)


def test_capabilities_must_use_glossary_terms() -> None:
    with pytest.raises(ContractError):
        make_manifest(["teleport_asset"], ["stock_on_hand"]).check()
    with pytest.raises(ContractError):
        make_manifest(ALL_OPS, ["vibes"]).check()


def test_missing_manifest_is_a_contract_error(tmp_path) -> None:
    with pytest.raises(ContractError) as exc:
        PortManifest.load(tmp_path)
    assert "must DECLARE its probe surface" in str(exc.value)


# --------------------------------------------------------------------------- #
# 6. Scoring arithmetic                                                        #
# --------------------------------------------------------------------------- #
def test_score_buckets_never_overlap() -> None:
    fx_pass = fixture("a", [soh(4.0), adjcount(1)])
    fx_fail = fixture("b", [soh(1.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=[])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest)
    report = verify_port(adapter, pack([fx_pass, fx_fail]), manifest)
    s = score_verdicts(report.verdicts)
    assert s.answered + s.no_verdict == s.assertions_total
    assert (s.scored_passed + s.scored_diverged + s.scored_failed
            == s.scored_answered)
    assert s.scored_answered + s.excluded_corroboration == s.answered


# --------------------------------------------------------------------------- #
# Honesty regressions — each was a live attack that produced a green verdict    #
# the port had not earned (adversarial review, 2026-07-20).                     #
# --------------------------------------------------------------------------- #
def test_a_divergence_must_name_a_decision_id() -> None:
    """A sanction with only free text is an unbounded blank cheque.

    The attack: a port answering 999 to everything declared one divergence per
    assertion, reason='kernel v1.2 sanctions this', no decision_id — and scored
    100%, clean, exit 0.
    """
    with pytest.raises(Exception):
        Divergence.model_validate({
            "fixture_id": "f", "assert": "stock_on_hand",
            "port_value": 1.0, "reason": "sanctioned, trust me",
        })


def test_an_unresolvable_decision_id_is_a_declaration_problem() -> None:
    """A sanction must point at a decision some registry actually knows."""
    fx = fixture("f3", [soh(4.0)])
    declared = [Divergence.model_validate({
        "fixture_id": fx.fixture_id, "assert": "stock_on_hand",
        "port_value": 9.0, "reason": "sanctioned",
        "decision_id": "no-such-decision-anywhere",
    })]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=declared)
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": 9.0})
    report = verify_port(adapter, pack([fx]), manifest,
                         decisions={"pending-status-gates": "stock_on_hand"})
    assert any("no-such-decision-anywhere" in p for p in report.declaration_problems)
    assert not report.clean


def test_a_fabricated_warrant_is_never_softer_than_a_real_one() -> None:
    """A divergence citing an id no registry resolves must FAIL the assertion.

    The inversion (MetaCoding-8x0): `decision_covers` ran only for ids that
    RESOLVE, so a real-but-off-topic decision failed the assertion while a
    fabricated id skipped the check and scored DIVERGED — the milder bucket,
    exit 3 instead of 1. Property: for the same wrong value, the fabricated
    warrant's outcome is at least as severe as the real one's.
    """
    def outcome_for(decision_id: str) -> AssertionStatus:
        fx = fixture("f8", [soh(4.0)])
        declared = [Divergence.model_validate({
            "fixture_id": fx.fixture_id, "assert": "stock_on_hand",
            "port_value": 9.0, "reason": "sanctioned",
            "decision_id": decision_id,
        })]
        manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=declared)
        adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                               overrides={"stock_on_hand": 9.0})
        report = verify_port(adapter, pack([fx]), manifest,
                             decisions={"birth-uniqueness": "about birth logs"})
        (verdict,) = [v for v in report.verdicts if v.fixture_id == fx.fixture_id]
        (out,) = verdict.outcomes
        return out.status

    fabricated = outcome_for("no-such-decision-anywhere")
    off_topic = outcome_for("birth-uniqueness")
    assert off_topic == AssertionStatus.FAILED
    assert fabricated == AssertionStatus.FAILED  # was DIVERGED — the inversion


# --------------------------------------------------------------------------- #
# MetaCoding-n9o: sanctions are citations, and the goal is a second metric      #
# --------------------------------------------------------------------------- #
def _diverging_report(decisions):
    """One fixture, one declared divergence citing 'pending-status-gates'."""
    fx = fixture("f9", [soh(4.0)])
    declared = [Divergence.model_validate({
        "fixture_id": fx.fixture_id, "assert": "stock_on_hand",
        "port_value": 9.0, "reason": "planned pending-gate divergence",
        "decision_id": "pending-status-gates",
    })]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=declared)
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": 9.0})
    return verify_port(adapter, pack([fx]), manifest, decisions=decisions)


def test_a_sanction_is_a_citation_names_never_sanction() -> None:
    """The wave-1 inversion, stated as a property: renaming-invariance.

    A decision whose prose exhaustively NAMES the term but cites nothing
    sanctions nothing; a decision that CITES the term in its typed sanctions
    sanctions it even if its prose never mentions it. The port and the source
    are both free to rename — the glossary term is the identity of the
    question asked at the boundary, and only a citation of it resolves.
    """
    prose_only = _diverging_report(
        {"pending-status-gates":
         {"text": "stock_on_hand stock_on_hand stock_on_hand", "sanctions": ()}})
    (v,) = [x for x in prose_only.verdicts if x.outcomes]
    assert v.outcomes[0].status == AssertionStatus.FAILED

    cited = _diverging_report(
        {"pending-status-gates":
         {"text": "prose that names no glossary term at all",
          "sanctions": ("stock_on_hand",)}})
    (v,) = [x for x in cited.verdicts if x.outcomes]
    assert v.outcomes[0].status == AssertionStatus.DIVERGED


def test_goal_fit_measures_the_target_and_fidelity_measures_the_source() -> None:
    """Two metrics, two questions. A port meeting all its PLANNED divergences
    exactly has goal_fit 100% while value_score honestly reports the distance
    from the source; an unplanned mismatch drags both down."""
    planned = _diverging_report(
        {"pending-status-gates":
         {"text": "", "sanctions": ("stock_on_hand",)}})
    s = planned.score
    assert s.scored_diverged == 1 and s.scored_failed == 0
    assert s.goal_fit == 1.0          # the goal, including the divergence, is met
    assert s.value_score == 0.0       # and the distance from the source is not hidden
    assert "goal fit" in s.headline()

    unplanned = PortScore(assertions_total=4, answered=4, scored_answered=4,
                          scored_passed=2, scored_diverged=1, scored_failed=1)
    assert unplanned.goal_fit == pytest.approx(0.75)   # the failure hits the goal too
    assert unplanned.value_score == pytest.approx(2 / 3)


def test_the_readers_patience_is_capped_reader_side() -> None:
    """BridgeSpec.timeout is written by the port: it may ask for less, never more.

    The half of C5 that survived the deadline fix (MetaCoding-i48): a bridge
    declaring `"timeout": 86400.0` re-created the original hang because the
    reader's patience was a parameter in the port's own manifest.
    """
    from ctkr.oracle.port_adapter import PATIENCE_CAP, PortBridge

    def bridge_with_timeout(t: float) -> PortBridge:
        return PortBridge(PortManifest.model_validate({
            "port": "p", "bridge": {"command": ["true"], "timeout": t},
        }))

    assert bridge_with_timeout(86400.0)._deadline() == PATIENCE_CAP
    assert bridge_with_timeout(2.0)._deadline() == 2.0  # less is honoured


def test_divergences_are_not_counted_as_passes() -> None:
    """Declaring must never be arithmetically identical to reproducing."""
    score = PortScore(assertions_total=10, answered=10, scored_answered=10,
                      scored_passed=0, scored_diverged=10)
    assert score.value_score == 0.0        # not 1.0
    assert score.scored_nothing
    assert "NOT counted as passes" in score.headline()


def test_a_run_that_scored_nothing_is_never_clean() -> None:
    """An empty denominator is absence of evidence, not innocence.

    The attack: a marks file excluding every fixture turned 30 wrong answers
    into zero failures, zero gaps, exit 0.
    """
    report = PortVerifyReport(
        port="p",
        score=PortScore(assertions_total=30, answered=30, scored_answered=0,
                        excluded_corroboration=30, fixtures_excluded=12),
    )
    assert not report.clean
    assert any("NOTHING WAS SCORED" in w for w in report.needs_review)


def test_sanctioned_divergences_block_a_clean_verdict() -> None:
    """A port that deliberately differs is value-equivalent MODULO an exception."""
    report = PortVerifyReport(
        port="p",
        score=PortScore(assertions_total=2, answered=2, scored_answered=2,
                        scored_passed=1, scored_diverged=1),
    )
    assert not report.clean
    assert any("MODULO" in w for w in report.needs_review)


def test_there_is_no_external_marks_file_at_all() -> None:
    """The external `--marks` path is gone, not merely better validated.

    It was introduced as the trustworthy channel — a caller-supplied file the
    port's author supposedly did not write. But `port-verify` is invoked by hand
    or by an agent every time (there is no automated invocation anywhere in the
    repo), so "the caller" and "the party being judged" are the same process. A
    reason field does not fix who is holding the pen.
    """
    from ctkr.oracle import port_contract
    from ctkr.commands import port_verify as cmd

    assert not hasattr(port_contract, "load_marks")
    assert not hasattr(port_contract, "FixtureMark")

    # The flag is not accepted by the parser — the mention left in the source is
    # the comment explaining why it was removed.
    import argparse

    parser = argparse.ArgumentParser()
    cmd.register(parser.add_subparsers())
    with pytest.raises(SystemExit):
        parser.parse_args(["port-verify", "p.jsonl", "--port", "d",
                           "--marks", "m.json"])
    with pytest.raises(SystemExit):
        parser.parse_args(["port-verify", "p.jsonl", "--port", "d",
                           "--decisions", "mine.jsonl"])


def test_a_bridge_may_declare_a_per_call_gap() -> None:
    """A port may implement a probe in general yet not answer THIS input.

    Without this channel the only unpunished move was to FABRICATE a value,
    which is how a real representational divergence (farmOS 0.0 vs the port's
    absent row) scored as a clean PASS.
    """
    fx = fixture("f9", [soh(0.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": _PER_CALL_GAP})
    report = verify_port(adapter, pack([fx]), manifest)
    assert report.score.no_verdict == 1
    assert report.score.scored_passed == 0
    assert not report.clean


def test_every_live_write_surface_has_a_port_dispatch() -> None:
    """PROPERTY (MetaCoding-ej0): every `given`-step write surface the LIVE
    adapter implements, PortAdapter must dispatch too — an override on
    FarmOSAdapter with only the raising base on PortAdapter means the flow
    RECORDS live but every fixture dies at setup when verified against a
    port. Caught by the sensor round's fresh reading: create_sensor_asset
    existed on farmos_adapter/steps but not on port_adapter, and the port
    scored 0/14 with the builder's bridge never consulted. `create_` is the
    interpreter's whole given-surface prefix (steps.apply_given), so this
    covers the family, not the instance."""
    from ctkr.oracle.adapter import ImplementationAdapter
    from ctkr.oracle.farmos_adapter import FarmOSAdapter

    live_creates = {
        n for n in dir(FarmOSAdapter) if n.startswith("create_")
        and getattr(FarmOSAdapter, n) is not getattr(
            ImplementationAdapter, n, None)
        and not n.startswith("_")
    }
    missing = {
        n for n in live_creates
        if getattr(PortAdapter, n) is getattr(ImplementationAdapter, n, None)
    }
    assert not missing, (
        f"live write surfaces with no port dispatch (fixtures will record "
        f"live but die at port-verify setup): {sorted(missing)}"
    )
