#!/usr/bin/env python3
"""Regression evidence for ctkr/verdict_currency.py.

    python3 -m pytest ctkr/tests/test_verdict_currency.py

This gate is an INSTRUMENT — it decides whether a build counts as done — so every
check below exercises a REFUTING outcome AND its contrast. A gate asserted only to
refuse is indistinguishable from one that refuses everything, and a gate that
refuses everything gets switched off exactly as fast as one that refuses nothing.

Built against synthetic workspaces, so the rules are testable without the port
tree. What is NOT covered here is discovery against the real workspace; that
evidence is the run recorded in the commit.
"""

from __future__ import annotations

import json

from ctkr.verdict_currency import (NAME_RULE, SPINE, _matches, discover,
                                   evaluate, load_partition, load_retirements,
                                   load_verdicts, main, render, resolve_tier,
                                   tier_of)


# ---------------------------------------------------------------------------
# a synthetic workspace
# ---------------------------------------------------------------------------

def workspace(tmp_path, builds, verdicts=(), wave="wave2", partition=(),
              retired=()):
    """builds: {name: {"seal": str|None, "manifest": bool, "port": str,
                       "packages": [str], "feature": str}}

    partition: [(filename, [row, ...])] written under results/<file-stem-dir>/.
    retired:   [(seal, reason)] written as retirement rows in PACKS.jsonl.
    """
    for name, spec in builds.items():
        b = tmp_path / "port_runs" / wave / name
        packages = spec.get("packages") or [""]
        if spec.get("manifest", True):
            for pkg in packages:
                d = b / "build" / pkg if pkg else b / "build"
                d.mkdir(parents=True, exist_ok=True)
                port = spec.get("port") or ("w2-" + name + ("-" + pkg if pkg else ""))
                doc = {"port": port}
                if spec.get("feature"):
                    doc["feature"] = spec["feature"]
                (d / "port.manifest.json").write_text(json.dumps(doc))
        if spec.get("seal") is not None:
            (b / "observe").mkdir(parents=True, exist_ok=True)
            (b / "observe" / "pack.seal.json").write_text(
                json.dumps({"seal": spec["seal"]}))
    vd = tmp_path / "results" / "port-verify"
    vd.mkdir(parents=True, exist_ok=True)
    for fn, doc in verdicts:
        (vd / fn).write_text(doc if isinstance(doc, str) else json.dumps(doc))
    for fn, rows in partition:
        pd = tmp_path / "results" / "wave2"
        pd.mkdir(parents=True, exist_ok=True)
        (pd / fn).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    if retired:
        pr = tmp_path / "port_runs"
        pr.mkdir(parents=True, exist_ok=True)
        with (pr / "PACKS.jsonl").open("a") as fh:
            for seal, reason in retired:
                fh.write(json.dumps({"record": "retirement", "seal": seal,
                                     "reason": reason}) + "\n")
    return str(tmp_path)


def verdict(port, seal, clean=True):
    return {"port": port, "pack_seal": seal, "clean": clean, "score": {}}


def prow(module, tier, cluster=""):
    return {"module": module, "tier": tier, "cluster": cluster}


def rows_for(tmp_path, builds, verdicts=(), wave="wave2", partition=(),
             retired=(), scope=None):
    ws = workspace(tmp_path, builds, verdicts, wave, partition, retired)
    return rows_of(ws, scope)


def rows_of(ws, scope=None):
    v, _err = load_verdicts(ws)
    p = load_partition(ws)
    ret, _e = load_retirements(ws)
    return {r.build.name: r for r in evaluate(discover(ws, scope, p, ret), v)}


# ---------------------------------------------------------------------------
# the rules, each refuting + its contrast
# ---------------------------------------------------------------------------

def test_a_build_with_no_verdict_GATES(tmp_path):
    r = rows_for(tmp_path, {"identity-a": {"seal": "abc"}})["wave2/identity-a"]
    assert r.state == "missing" and r.gates


def test_a_build_WITH_a_current_clean_verdict_does_not(tmp_path):
    """The contrast. A gate that refuses a correctly-verified build is a gate
    someone deletes within the week."""
    r = rows_for(tmp_path, {"identity-a": {"seal": "abc"}},
                 [("a.json", verdict("w2-identity-a", "abc"))])["wave2/identity-a"]
    assert r.state == "ok" and not r.gates


def test_a_verdict_against_a_SUPERSEDED_pack_gates(tmp_path):
    """The subtle one, and the reason the seal is compared rather than the name:
    re-recording a pack silently invalidates every score taken on the old one, and
    the stale verdict keeps sitting there looking like evidence."""
    r = rows_for(tmp_path, {"identity-a": {"seal": "NEW"}},
                 [("a.json", verdict("w2-identity-a", "OLD"))])["wave2/identity-a"]
    assert r.state == "stale" and r.gates
    assert "no longer exists" in r.detail


def test_an_UNCLEAN_verdict_gates(tmp_path):
    r = rows_for(tmp_path, {"identity-a": {"seal": "abc"}},
                 [("a.json", verdict("w2-identity-a", "abc", clean=False))])["wave2/identity-a"]
    assert r.state == "unclean" and r.gates


def test_a_build_with_NO_SEALED_PACK_gates_and_is_not_called_ok(tmp_path):
    """Absence of an answer is never a yes. A build with no pack has not been
    driven at all — the strongest form of undriven, and the easiest to read as
    'nothing to check here'."""
    r = rows_for(tmp_path, {"identity-a": {"seal": None}})["wave2/identity-a"]
    assert r.state == "undeterminable" and r.gates


def test_an_UNREADABLE_verdict_counts_as_NO_verdict(tmp_path):
    """A corrupt report must never satisfy the gate it was supposed to satisfy."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   [("a.json", "{not json")])
    v, errors = load_verdicts(ws)
    rows = {r.build.name: r for r in evaluate(discover(ws, "wave2"), v)}
    assert rows["wave2/identity-a"].gates
    assert any("never as one" in e for e in errors)


# ---------------------------------------------------------------------------
# the bound decision: spine is advisory
# ---------------------------------------------------------------------------

def test_SPINE_never_gates_even_with_no_verdict(tmp_path):
    """MetaCoding-hy6 (2)/(4), reaffirmed by Duke as hy6.51. Spine builds are
    REPORTED and never block. If this test starts failing, someone widened the
    gate without reopening the risk partition."""
    r = rows_for(tmp_path, {"spine-a": {"seal": None}})["wave2/spine-a"]
    assert r.build.tier == SPINE
    assert r.state == "undeterminable"
    assert not r.gates, "the gate reversed a bound decision"


def test_an_UNCLASSIFIABLE_build_gates(tmp_path):
    """Neither identity- nor spine-, and no recorded partition row: nobody
    decided about it, so it is not exempt. The exemption is a decision, not a
    default."""
    r = rows_for(tmp_path, {"mystery": {"seal": None}})["wave2/mystery"]
    assert r.gates


def test_the_FALLBACK_name_rule_still_reads_the_directory(tmp_path):
    assert tier_of("identity-sensor") == "identity"
    assert tier_of("spine-asset") == "spine"
    assert tier_of("quick-folds") == "unknown"


# ---------------------------------------------------------------------------
# hy6.55 — the tier comes from the RECORDED partition, not from a proxy
# ---------------------------------------------------------------------------

QUICK = [prow("quick/birth", "identity"), prow("quick/group", "identity"),
         prow("quick/movement", "identity")]


def test_the_RECORDED_partition_decides_where_the_name_rule_says_UNKNOWN(tmp_path):
    """`quick-folds`, exactly. The name rule calls it UNKNOWN — 'nobody decided
    about it' — while both recorded partitions tier every quick/* module
    IDENTITY. Two records decided; the proxy read neither."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc"}},
                    partition=[("partition-1.jsonl", QUICK)])
    r = rows["wave2/quick-folds"]
    assert tier_of("quick-folds") == "unknown"      # what the proxy says
    assert r.build.tier == "identity"               # what the RECORD says
    assert "partition" in r.build.tier_source and r.build.tier_source != NAME_RULE


def test_the_RECORDED_partition_decides_AGAINST_gating_too(tmp_path):
    """The contrast, and the one that costs something: the name says identity,
    so the proxy would GATE this build; the recorded partition says spine, so it
    is advisory. A record that can only ever tighten the gate is not being read,
    it is being overruled."""
    rows = rows_for(tmp_path, {"identity-activity": {"seal": None}},
                    partition=[("partition-1.jsonl",
                                [prow("log/activity", "spine")])])
    r = rows["wave2/identity-activity"]
    assert tier_of("identity-activity") == "identity"
    assert r.build.tier == SPINE and not r.gates
    assert "log/activity" in r.build.tier_source


def test_a_build_the_partition_does_not_NAME_falls_back_VISIBLY(tmp_path):
    """The fallback is allowed; being unable to see it is not. A build tiered by
    the proxy must say so, because that is the row a reader has to check."""
    rows = rows_for(tmp_path, {"identity-nowhere": {"seal": "abc"}},
                    partition=[("partition-1.jsonl", QUICK)])
    r = rows["wave2/identity-nowhere"]
    assert r.build.tier == "identity"
    assert r.build.tier_source == NAME_RULE
    out = render([r], [], all_tiers=True)
    assert "FALLBACK" in out
    assert "1 build(s) were tiered by the FALLBACK name rule" in out


def test_two_partition_files_that_DISAGREE_do_not_get_picked_between(tmp_path):
    """A gate is not the place a contradiction between two records gets quietly
    resolved. Disagreement resolves to UNKNOWN, which gates."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc"}},
                    partition=[("partition-1.jsonl", [prow("quick/birth", "identity")]),
                               ("partition-2.jsonl", [prow("quick/birth", "spine")])])
    r = rows["wave2/quick-folds"]
    assert r.build.tier == "unknown" and r.gates


def test_two_partition_files_that_AGREE_are_read_normally(tmp_path):
    """The contrast: the real tree has two partition files that agree on all 41
    modules, and duplication must not look like conflict."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc"}},
                    partition=[("partition-1.jsonl", [prow("quick/birth", "identity")]),
                               ("partition-2.jsonl", [prow("quick/birth", "identity")])])
    assert rows["wave2/quick-folds"].build.tier == "identity"


def test_the_manifests_DECLARED_module_is_read_before_any_name_guess(tmp_path):
    r = rows_for(tmp_path, {"identity-quantity-test": {"seal": "abc",
                                                       "feature": "quantity/test"}},
                 partition=[("partition-1.jsonl", [prow("quantity/test", "spine")])])
    r = r["wave2/identity-quantity-test"]
    assert r.build.tier == SPINE
    assert "manifest declares module quantity/test" in r.build.tier_source


def test_a_cluster_row_tiers_the_package_that_belongs_to_it(tmp_path):
    p = load_partition(workspace(tmp_path, {},
                                 partition=[("partition-1.jsonl",
                                             [prow("asset/compost", "spine", "spine-asset")])]))
    assert resolve_tier(p, "spine-asset", "compost")[0] == SPINE


# ---------------------------------------------------------------------------
# hy6.56 — scope by the RETIREMENT RECORD, not by recency
# ---------------------------------------------------------------------------

def test_an_OLDER_wave_that_was_never_retired_is_still_answered_for(tmp_path):
    """wave1 and wave1-c1 hold six manifests with sealed packs and no verdict.
    The recency rule made them invisible; PACKS.jsonl retires neither, and its
    own reason text calls wave1 a live lane."""
    workspace(tmp_path, {"input": {"seal": "w1seal"}}, wave="wave1",
              partition=[("partition-1.jsonl", [prow("log/input", "identity")])])
    workspace(tmp_path, {"identity-new": {"seal": "w2seal"}}, wave="wave2")
    rows = rows_of(str(tmp_path))
    assert "wave1/input" in rows, sorted(rows)
    assert rows["wave1/input"].build.tier == "identity"
    assert rows["wave1/input"].gates


def test_a_build_whose_pack_the_RECORD_retires_is_exempt(tmp_path):
    """The contrast, and the reason the old rule existed: a retired pilot must
    not sit permanently in the failing column. Exemption follows the retirement
    record — the seal the pack carries today — not the age of its directory."""
    workspace(tmp_path, {"w0a-build": {"seal": "PILOT"}}, wave="wave0-pilot",
              retired=[("PILOT", "MetaCoding-2oo: wave0 PILOT pack")])
    workspace(tmp_path, {"identity-live": {"seal": "LIVE"}}, wave="wave1")
    rows = rows_of(str(tmp_path))
    retired_row = rows["wave0-pilot/w0a-build"]
    assert retired_row.state == "retired" and not retired_row.gates
    # ... and the un-retired build in the very same sweep still gates.
    assert rows["wave1/identity-live"].gates


def test_retirement_keeps_the_gate_from_being_permanently_red(tmp_path):
    """End to end: a tree whose only unverified build is a retired pilot exits 0.
    If this fails, the retirement record is not being honoured and the gate is
    the always-red kind nobody reads."""
    workspace(tmp_path, {"w0a-build": {"seal": "PILOT"}}, wave="wave0-pilot",
              retired=[("PILOT", "wave0 pilot, superseded")])
    workspace(tmp_path, {"identity-a": {"seal": "abc"}},
              verdicts=[("a.json", verdict("w2-identity-a", "abc"))])
    assert main(["--workspace", str(tmp_path)]) == 0


def test_a_pack_seal_that_is_NOT_in_the_retirement_record_is_not_exempt(tmp_path):
    """wave0-pilot holds four seals and PACKS.jsonl retires two of them. Being
    in an old directory is not retirement."""
    workspace(tmp_path, {"w0a-build": {"seal": "OTHER"}}, wave="wave0-pilot",
              retired=[("PILOT", "wave0 pilot, superseded")])
    rows = rows_of(str(tmp_path))
    assert rows["wave0-pilot/w0a-build"].state != "retired"
    assert rows["wave0-pilot/w0a-build"].gates


def test_wave_narrows_the_sweep_by_hand(tmp_path):
    workspace(tmp_path, {"identity-old": {"seal": "o"}}, wave="wave1")
    workspace(tmp_path, {"identity-new": {"seal": "n"}}, wave="wave2")
    assert set(rows_of(str(tmp_path), "wave2")) == {"wave2/identity-new"}
    assert set(rows_of(str(tmp_path))) == {"wave1/identity-old", "wave2/identity-new"}


# ---------------------------------------------------------------------------
# hy6.57 — one manifest is one build, and one verdict satisfies one build
# ---------------------------------------------------------------------------

def test_PER_PACKAGE_manifests_are_separate_builds(tmp_path):
    """Seven packages under spine-asset were one row with one verdict lookup: a
    single verdict marked all seven verified, and a per-package verdict was not
    representable at all."""
    rows = rows_for(tmp_path, {"identity-multi": {"seal": "abc",
                                                  "packages": ["compost", "water"]}})
    assert set(rows) == {"wave2/identity-multi/compost", "wave2/identity-multi/water"}


def test_a_verdict_for_ONE_package_does_not_verify_ITS_SIBLING(tmp_path):
    """The load-bearing half: the sibling must still gate. Both packages share a
    pack seal, so seal currency alone cannot tell them apart."""
    rows = rows_for(tmp_path, {"identity-multi": {"seal": "abc",
                                                  "packages": ["compost", "water"]}},
                    [("c.json", verdict("w2-identity-multi-compost", "abc"))])
    assert rows["wave2/identity-multi/compost"].state == "ok"
    assert rows["wave2/identity-multi/water"].state == "missing"
    assert rows["wave2/identity-multi/water"].gates


def test_a_SINGLE_package_build_is_still_exactly_one_row(tmp_path):
    """The contrast: splitting per manifest must not split a plain build in two,
    nor rename it out of recognition."""
    rows = rows_for(tmp_path, {"identity-a": {"seal": "abc"}})
    assert set(rows) == {"wave2/identity-a"}


def test_one_verdict_cannot_satisfy_a_build_its_name_merely_ENDS_WITH(tmp_path):
    """`_matches` was `endswith`, so a verdict naming `w2-identity-land` also
    satisfied builds called `land` and `entity-land`. A judge replaced the whole
    body with `return True` and all thirteen tests passed."""
    rows = rows_for(tmp_path, {"identity-land": {"seal": "abc", "port": "w2-identity-land"},
                               "land": {"seal": "abc", "port": "w2-land"},
                               "entity-land": {"seal": "abc", "port": "w2-entity-land"}},
                    [("l.json", verdict("w2-identity-land", "abc"))])
    assert rows["wave2/identity-land"].state == "ok"
    assert rows["wave2/land"].state == "missing" and rows["wave2/land"].gates
    assert rows["wave2/entity-land"].state == "missing"


def test_a_verdict_from_ANOTHER_WAVE_does_not_satisfy_this_one(tmp_path):
    """Nothing used to constrain a verdict to its wave."""
    workspace(tmp_path, {"identity-a": {"seal": "s1", "port": "w1-identity-a"}},
              wave="wave1")
    workspace(tmp_path, {"identity-a": {"seal": "s1", "port": "w2-identity-a"}},
              verdicts=[("a.json", verdict("w1-identity-a", "s1"))])
    rows = rows_of(str(tmp_path))
    assert rows["wave1/identity-a"].state == "ok"
    assert rows["wave2/identity-a"].state == "missing"
    assert rows["wave2/identity-a"].gates


def test_matching_is_EXACT_on_the_declared_id_or_the_build_key(tmp_path):
    """Direct on the rule, because this is the one a mutation walked through:
    `return True` must not survive."""
    rows = rows_for(tmp_path, {"identity-a": {"seal": "abc"}})
    b = rows["wave2/identity-a"].build
    assert _matches("w2-identity-a", b)          # the id its manifest declares
    assert _matches("wave2/identity-a", b)       # or its build key
    assert not _matches("identity-a", b)         # a suffix is not an identifier
    assert not _matches("w2-identity-a-extra", b)
    assert not _matches("", b)


def test_two_builds_declaring_the_SAME_port_id_are_not_scored(tmp_path):
    """An ambiguous identifier is not an identifier: a verdict naming it could be
    about either build, so it is evidence about neither."""
    rows = rows_for(tmp_path, {"identity-a": {"seal": "abc", "port": "w2-dup"},
                               "identity-b": {"seal": "abc", "port": "w2-dup"}},
                    [("d.json", verdict("w2-dup", "abc"))])
    for name in ("wave2/identity-a", "wave2/identity-b"):
        assert rows[name].state == "undeterminable" and rows[name].gates
        assert "also declared by" in rows[name].detail


def test_DISTINCT_port_ids_are_scored_normally(tmp_path):
    """The contrast — the ambiguity guard must not refuse honest builds."""
    rows = rows_for(tmp_path, {"identity-a": {"seal": "abc", "port": "w2-a"},
                               "identity-b": {"seal": "abc", "port": "w2-b"}},
                    [("a.json", verdict("w2-a", "abc")),
                     ("b.json", verdict("w2-b", "abc"))])
    assert rows["wave2/identity-a"].state == "ok"
    assert rows["wave2/identity-b"].state == "ok"


def test_the_headline_counts_what_it_names(tmp_path):
    """It said '34 build(s) declare a manifest' while counting manifests over 21
    build directories. One manifest is one build now, so the noun is true."""
    rows = rows_for(tmp_path, {"identity-multi": {"seal": "abc",
                                                  "packages": ["a", "b"]}})
    out = render(list(rows.values()), [], all_tiers=True)
    assert "2 build(s) declare a manifest — one row per manifest" in out


# ---------------------------------------------------------------------------
# vacuity
# ---------------------------------------------------------------------------

def test_an_EMPTY_SWEEP_refuses_rather_than_passing(tmp_path, capsys):
    """The classic vacuous pass: find no builds, report everything verified. A
    wrong --workspace would otherwise be indistinguishable from a clean tree."""
    (tmp_path / "port_runs" / "wave2").mkdir(parents=True)
    assert main(["--workspace", str(tmp_path)]) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_main_exits_2_when_a_gating_build_lacks_a_verdict(tmp_path):
    workspace(tmp_path, {"identity-a": {"seal": "abc"}})
    assert main(["--workspace", str(tmp_path)]) == 2


def test_main_exits_0_when_every_gating_build_is_current(tmp_path):
    """The contrast that makes the exit code worth reading."""
    workspace(tmp_path, {"identity-a": {"seal": "abc"}, "spine-b": {"seal": None}},
              [("a.json", verdict("w2-identity-a", "abc"))])
    assert main(["--workspace", str(tmp_path)]) == 0
