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

from ctkr.verdict_currency import (
    NAME_RULE,
    SPINE,
    _matches,
    discover,
    evaluate,
    gating_rows,
    load_partition,
    load_retirements,
    load_verdicts,
    main,
    render,
    resolve_tier,
    tier_of,
)

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
            for entry in retired:
                # (seal, reason) keeps the old call sites meaning what they meant:
                # scoped to the wave under test. (seal, reason, scope) is the
                # knob MetaCoding-hy6.58's reds need — including scope=None, a
                # retirement that names no wave and must therefore exempt nothing.
                seal, reason = entry[0], entry[1]
                scope = entry[2] if len(entry) > 2 else {"wave": wave}
                row = {"record": "retirement", "seal": seal, "reason": reason}
                if scope is not None:
                    row["scope"] = scope
                fh.write(json.dumps(row) + "\n")
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
                               # an older recorder convention: no wave prefix. Its
                               # id is a SUFFIX of its neighbour's, which is the
                               # whole defect.
                               "land-unprefixed": {"seal": "abc", "port": "identity-land"},
                               "land": {"seal": "abc", "port": "w2-land"},
                               "entity-land": {"seal": "abc", "port": "w2-entity-land"}},
                    [("l.json", verdict("w2-identity-land", "abc"))])
    assert rows["wave2/identity-land"].state == "ok"
    for other in ("wave2/land-unprefixed", "wave2/land", "wave2/entity-land"):
        assert rows[other].state == "missing", other
        assert rows[other].gates, other


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
    assert not _matches("stale-w2-identity-a", b)   # nor is a string ENDING in one
    assert not _matches("results/wave2/identity-a", b)
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


# ---------------------------------------------------------------------------
# hy6.58 — a retirement excuses the wave it NAMES, and no other
# ---------------------------------------------------------------------------

def test_a_LIVE_build_carrying_a_RETIRED_seal_from_another_wave_GATES(tmp_path):
    """THE P0, as a fresh judge demonstrated it: copy wave0-pilot's 40-byte
    pack.seal.json into a brand-new build in a brand-new wave and the gate said
    '1 exempt (pack RETIRED) ... of the 0 live' and EXITED 0 on a build with no
    verdict anywhere. Exemption keyed on the seal STRING ALONE, unscoped.

    It is not adversarial: _find_seal ascends directories on purpose, so any
    manifest dropped under a wave root holding a retired seal inherited it."""
    ws = workspace(tmp_path, {"identity-brandnew": {"seal": "RETIRED-SEAL"}},
                   wave="wave9",
                   retired=[("RETIRED-SEAL", "wave0 pilot: fixtures no longer re-hash",
                             {"wave": "wave0-pilot"})])
    r = rows_of(ws)["wave9/identity-brandnew"]
    assert r.gates, "a copied retirement seal exempted a live build in another wave"
    assert r.state == "undeterminable"
    assert "retires FOR 'wave0-pilot'" in r.detail


def test_the_SAME_seal_IS_an_exemption_inside_the_wave_it_names(tmp_path):
    """The contrast, and it is what keeps the retirement record useful: an
    exemption that excused nothing would make wave0-pilot permanently red, which
    is the always-red failure mode the original recency rule was answering."""
    ws = workspace(tmp_path, {"w0a-build": {"seal": "RETIRED-SEAL"}},
                   wave="wave0-pilot",
                   retired=[("RETIRED-SEAL", "wave0 pilot: fixtures no longer re-hash",
                             {"wave": "wave0-pilot"})])
    r = rows_of(ws)["wave0-pilot/w0a-build"]
    assert not r.gates
    assert r.build.retired_reason


def test_a_retirement_that_names_NO_wave_exempts_NOTHING(tmp_path):
    """An unscoped retirement is a skeleton key. Absence of an answer is never a
    yes — and the row is reported as a defect in the record rather than ignored."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "LOOSE"}},
                   retired=[("LOOSE", "retired, scope unstated", None)])
    _out, errors = load_retirements(ws)
    assert any("skeleton key" in e for e in errors), errors
    assert rows_of(ws)["wave2/identity-a"].gates


def test_an_ORDINARY_pack_row_carrying_a_seal_is_not_a_retirement(tmp_path):
    """The judge's J01, which SURVIVED: dropping the `record == "retirement"`
    filter exempted TEN more live builds and no test noticed, because every
    fixture wrote only retirement rows — so the filtered and unfiltered readings
    agreed on every case. The real PACKS.jsonl is 43 rows and ALL 43 carry a
    seal; that one `continue` is the entire exemption mechanism."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "PACKSEAL"}})
    with open(f"{ws}/port_runs/PACKS.jsonl", "a") as fh:
        fh.write(json.dumps({"pack_id": "p1", "seal": "PACKSEAL",
                             "recorded_at": "2026-07-23"}) + "\n")
    out, errors = load_retirements(ws)
    assert out == {}, f"an ordinary pack row was read as a retirement: {out}"
    assert rows_of(ws)["wave2/identity-a"].gates
    # AND the discriminating half. `out == {}` alone does NOT distinguish the two
    # readings any more: with the filter dropped, an ordinary pack row falls out
    # at the scope requirement instead — same empty result, different reason. The
    # scope check was masking the missing discriminator, which is the exact shape
    # 2527935 was about (a rule tested only where its two readings agree).
    # An ordinary pack row must never be EXAMINED as a retirement, so it must not
    # produce a retirement's complaint about scope.
    assert not any("scope" in e for e in errors), (
        "an ordinary pack row was examined as a retirement and complained about "
        f"its missing scope: {errors}")


# ---------------------------------------------------------------------------
# hy6.59 — the nine surviving mutations, each with the fixture that separates
# the two readings. THE SHAPE THIS FILE KEEPS GETTING BITTEN BY: a rule tested
# only where its two candidate readings AGREE is not tested (`_matches`/endswith,
# the PACKS.jsonl discriminator, `_find_seal`'s ascent). Every fixture below is
# built so that the mutant and the real rule give DIFFERENT answers.
# ---------------------------------------------------------------------------

def test_a_RETIRED_seal_is_matched_EXACTLY_not_by_PREFIX(tmp_path):
    """J02. Exemption is keyed on the seal a pack carries; a seal that merely
    BEGINS with a retired one is a different pack. Every fixture until now used
    a seal that either equalled a retired one or shared no prefix with it, so
    `==` and `startswith` agreed everywhere. Seals are hex digests, and a
    truncated or re-recorded digest sharing a prefix is exactly the case the
    exemption must not swallow."""
    ws = workspace(tmp_path, {"w0a-build": {"seal": "d2942d62e1b0-v2"}},
                   wave="wave0-pilot",
                   retired=[("d2942d62e1b0", "wave0 pilot: fixtures no longer re-hash")])
    r = rows_of(ws)["wave0-pilot/w0a-build"]
    assert not r.build.retired_reason, "a seal was excused for sharing a PREFIX"
    assert r.gates


def test_the_seal_the_record_names_EXACTLY_is_still_exempt(tmp_path):
    """The contrast: tightening to `==` must not stop the retirement record
    working, or wave0-pilot goes permanently red."""
    ws = workspace(tmp_path / "b", {"w0a-build": {"seal": "d2942d62e1b0"}},
                   wave="wave0-pilot",
                   retired=[("d2942d62e1b0", "wave0 pilot: fixtures no longer re-hash")])
    r = rows_of(ws)["wave0-pilot/w0a-build"]
    assert r.build.retired_reason and not r.gates


def test_a_verdict_with_NO_clean_KEY_is_not_clean(tmp_path):
    """J03. Every fixture set `clean` explicitly, so present-and-false was tested
    and ABSENT was not — and absent is the reading a truncated or older recorder
    produces. Absence of an answer is never a yes."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   [("a.json", {"port": "w2-identity-a", "pack_seal": "abc",
                                "score": {}})])
    r = rows_of(ws)["wave2/identity-a"]
    assert r.state == "unclean" and r.gates


def test_ONE_unclean_verdict_among_TWO_current_ones_still_gates(tmp_path):
    """J04. `all()` -> `any()` survived because no fixture ever gave one build
    two current verdicts, so the two readings agreed on every case in the suite.
    Two verdicts naming the same port against the same pack is not exotic — it is
    what re-running port-verify under a second filename produces, and under
    `any()` the older clean one would excuse the newer dirty one."""
    rows = rows_for(tmp_path, {"identity-a": {"seal": "abc"}},
                    [("a1-clean.json", verdict("w2-identity-a", "abc", clean=True)),
                     ("a2-dirty.json", verdict("w2-identity-a", "abc", clean=False))])
    r = rows["wave2/identity-a"]
    assert r.state == "unclean" and r.gates
    assert "a2-dirty.json" in r.detail and "a1-clean.json" not in r.detail


def test_TWO_current_verdicts_that_are_BOTH_clean_are_ok(tmp_path):
    """The contrast: duplication is not dirt."""
    rows = rows_for(tmp_path, {"identity-a": {"seal": "abc"}},
                    [("a1.json", verdict("w2-identity-a", "abc")),
                     ("a2.json", verdict("w2-identity-a", "abc"))])
    assert rows["wave2/identity-a"].state == "ok"


def test_two_modules_in_ONE_lookup_that_disagree_resolve_to_UNKNOWN(tmp_path):
    """J05. `Partition.unanimous` across MODULES — the path the live tree uses
    (identity-birth resolves over {log/birth, quick/birth}), and a different path
    from two FILES disagreeing about one module, which is all that was tested.
    Picking `sorted(tiers)[0]` LOOSENS: here it would return `spine`, and spine
    does not gate at all."""
    rows = rows_for(tmp_path, {"identity-mixed": {"seal": None}},
                    partition=[("partition-1.jsonl",
                                [prow("asset/one", "spine", "identity-mixed"),
                                 prow("asset/two", "unknown", "identity-mixed")])])
    r = rows["wave2/identity-mixed"]
    assert r.build.tier == "unknown", "a gate picked between two records"
    assert r.gates, "picking the alphabetically-first tier makes this ADVISORY"
    assert "rows disagree" in r.build.tier_source


def test_two_modules_in_ONE_lookup_that_AGREE_resolve_normally(tmp_path):
    """The contrast: a cluster of modules that agree is the ordinary case and
    must not be read as a contradiction."""
    rows = rows_for(tmp_path, {"identity-mixed": {"seal": None}},
                    partition=[("partition-1.jsonl",
                                [prow("asset/one", "spine", "identity-mixed"),
                                 prow("asset/two", "spine", "identity-mixed")])])
    r = rows["wave2/identity-mixed"]
    assert r.build.tier == SPINE and not r.gates


def test_the_NEAREST_pack_seal_decides_when_TWO_are_on_the_path(tmp_path):
    """J07, and the judge called it one of the two highest-value holes.
    `_find_seal`'s docstring names TWO conventions it must serve — a pack shared
    by a whole wave (wave1-c1) and a per-build pack — but every fixture wrote
    exactly ONE seal per build, so nearest-first and outermost-first agreed on
    every fixture AND on all 41 live builds. Reversing the ascent survived.

    Here both conventions are present at once: `near` has its own pack AND sits
    under a wave-level one. Its own must decide, or its verdict reads as stale."""
    ws = workspace(tmp_path, {"near": {"seal": "NEARSEAL", "port": "p-near"},
                              "far-only": {"seal": None, "port": "p-far"}},
                   wave="wave9",
                   verdicts=[("n.json", verdict("p-near", "NEARSEAL")),
                             ("f.json", verdict("p-far", "WAVESEAL"))])
    wave_pack = tmp_path / "port_runs" / "wave9" / "observe"
    wave_pack.mkdir(parents=True, exist_ok=True)
    (wave_pack / "pack.seal.json").write_text(json.dumps({"seal": "WAVESEAL"}))
    rows = rows_of(ws)
    near = rows["wave9/near"]
    assert near.build.seal == "NEARSEAL", "the OUTERMOST pack decided"
    assert near.state == "ok" and not near.gates
    # ... and the contrast, in the same tree: the ascent is REAL. A build with no
    # pack of its own still inherits the wave-level one (wave1-c1's portA/portB
    # share one pack), so this must not be "fixed" by refusing to ascend at all.
    far = rows["wave9/far-only"]
    assert far.build.seal == "WAVESEAL"
    assert far.state == "ok" and not far.gates


def test_the_reported_gating_COUNT_is_the_population_main_EXITS_on(tmp_path, capsys):
    """J10. `hy6.53` WAS a divergence between the population the headline counts
    and the population the exit code is taken from. It was fixed and then nothing
    bound the two, so blanking the report's list left the suite silent. The tree
    below holds one of everything that must NOT be counted — a retired pack, a
    spine build, a verified build — so the two populations can actually differ."""
    workspace(tmp_path, {"w0a-build": {"seal": "PILOT"}}, wave="wave0-pilot",
              retired=[("PILOT", "wave0 pilot: fixtures no longer re-hash")])
    workspace(tmp_path, {"identity-ok": {"seal": "abc"},
                         "identity-bad": {"seal": "xyz"},
                         "spine-quiet": {"seal": None},
                         "mystery": {"seal": None}},
              verdicts=[("a.json", verdict("w2-identity-ok", "abc"))])
    assert main(["--workspace", str(tmp_path)]) == 2
    cap = capsys.readouterr()
    headline = [ln for ln in cap.out.splitlines() if "gating build(s) lack" in ln]
    assert len(headline) == 1, cap.out
    reported = int(headline[0].split()[0])
    named = sorted(cap.err.strip().splitlines()[-1].strip().split(", "))
    assert named == ["wave2/identity-bad", "wave2/mystery"], cap.err
    assert reported == len(named), (
        f"the report announces {reported} gating build(s); the exit is taken on "
        f"{len(named)} — hy6.53 exactly")
    rows = rows_of(str(tmp_path))
    assert len(gating_rows(list(rows.values()))) == reported


def test_an_UNREADABLE_manifest_is_UNDETERMINABLE_and_gates(tmp_path):
    """J14. `test_an_UNREADABLE_verdict_counts_as_NO_verdict` exists; the manifest
    counterpart did not. The discriminating half: with the manifest unreadable the
    declared port id is empty, but `_matches` also accepts the BUILD KEY — so a
    verdict filed under the key satisfies a build whose manifest nobody could
    read. A build that cannot say what it is has not been driven."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   verdicts=[("a.json", verdict("wave2/identity-a", "abc"))])
    (tmp_path / "port_runs" / "wave2" / "identity-a" / "build"
     / "port.manifest.json").write_text("{not json")
    r = rows_of(ws)["wave2/identity-a"]
    assert r.state == "undeterminable", "an unreadable manifest was scored"
    assert r.gates
    assert "unreadable" in r.detail


def test_a_READABLE_manifest_is_satisfied_by_a_verdict_under_its_build_key(tmp_path):
    """The contrast, and what makes the test above discriminate: the same verdict,
    filed under the same build key, against a manifest that parses, is ok."""
    ws = workspace(tmp_path / "b", {"identity-a": {"seal": "abc"}},
                   verdicts=[("a.json", verdict("wave2/identity-a", "abc"))])
    assert rows_of(ws)["wave2/identity-a"].state == "ok"


def test_a_pack_seal_file_carrying_NO_seal_is_an_ERROR_not_an_empty_seal(tmp_path):
    """J18. Dropping the check leaves `seal == ""`, and then a verdict that
    records no `pack_seal` compares EQUAL to it — an unsealed pack and an
    unsealed verdict agreeing that nothing was checked, scored `ok`. Two
    absences do not make a currency."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   verdicts=[("a.json", {"port": "w2-identity-a", "clean": True,
                                         "score": {}})])
    (tmp_path / "port_runs" / "wave2" / "identity-a" / "observe"
     / "pack.seal.json").write_text(json.dumps({"pack_id": "p1"}))
    r = rows_of(ws)["wave2/identity-a"]
    assert r.state == "undeterminable", "an empty seal matched an empty pack_seal"
    assert r.gates
    assert "carries no" in r.detail


# ---------------------------------------------------------------------------
# hy6.60 — a partition that names NOTHING is not a partition
# ---------------------------------------------------------------------------

def test_a_partition_file_that_names_NOTHING_REFUSES(tmp_path, capsys):
    """MEASURED on the real tree: with both partition-*.jsonl present but
    truncated to zero bytes, the gate reported `40 build(s) were tiered by the
    FALLBACK name rule`, moved three builds' gating status, and refused nothing.
    That is hy6.55's defect — a bound risk decision made by a directory-name
    proxy — restored in full by a rename, a bad glob or an unsynced results/.

    The tree here is otherwise CLEAN: without the refusal it exits 0. That is
    what makes this a red rather than a decoration."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   verdicts=[("a.json", verdict("w2-identity-a", "abc"))],
                   partition=[("partition-1.jsonl", [])])
    assert main(["--workspace", ws]) == 2
    err = capsys.readouterr().err
    assert "REFUSING" in err
    assert "partition-1.jsonl" in err


def test_a_workspace_with_NO_partition_file_AT_ALL_still_falls_back_visibly(tmp_path,
                                                                            capsys):
    """The contrast, and it is the load-bearing half: there is a difference
    between "nobody wrote a record" and "the record I am reading is empty", and
    only the second is a broken instrument. A refusal that fired on both would
    make the fallback — which the docstring explicitly keeps — unreachable."""
    workspace(tmp_path, {"identity-a": {"seal": "abc"}},
              verdicts=[("a.json", verdict("w2-identity-a", "abc"))])
    assert main(["--workspace", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 build(s) were tiered by the FALLBACK name rule" in out


def test_a_partition_file_with_rows_but_no_MODULE_also_refuses(tmp_path, capsys):
    """The other way to name nothing: rows that parse and carry no module. A
    file with bytes in it must not read as a record because it is non-empty."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   verdicts=[("a.json", verdict("w2-identity-a", "abc"))],
                   partition=[("partition-1.jsonl", [{"tier": "spine"},
                                                     {"note": "header"}])])
    assert main(["--workspace", ws]) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_a_tier_OUTSIDE_the_vocabulary_is_an_ERROR_not_a_tier(tmp_path):
    """J13 / hy6.60's second half. `{"module": "asset/sensor", "tier": "SPINE"}`
    was accepted verbatim and printed as `the recorded partition says SPINE`.
    It gated (only the exact string `spine` disables gating) so the direction was
    safe, but the gate could not distinguish "the record says spine" from "the
    record says a word I do not recognise" — and a gate that cannot tell those
    apart is not reading the record."""
    ws = workspace(tmp_path, {"identity-sensor": {"seal": None}},
                   partition=[("partition-1.jsonl", [prow("asset/sensor", "SPINE")])])
    p = load_partition(ws)
    assert p.tier_by_module["asset/sensor"] == "unknown"
    assert any("is not a tier" in e for e in p.errors), p.errors
    r = rows_of(ws)["wave2/identity-sensor"]
    assert r.build.tier == "unknown" and r.gates
    assert "SPINE" not in r.build.tier_source, (
        f"the report repeats a word that is not a tier: {r.build.tier_source}")


def test_a_tier_INSIDE_the_vocabulary_is_read_as_written(tmp_path):
    """The contrast: closing the vocabulary must not reject the record itself.
    All three words the live partition uses still resolve."""
    ws = workspace(tmp_path, {"identity-sensor": {"seal": None}},
                   partition=[("partition-1.jsonl",
                               [prow("asset/sensor", "spine"),
                                prow("log/input", "identity"),
                                prow("asset/mystery", "unknown")])])
    p = load_partition(ws)
    assert p.errors == []
    assert p.tier_by_module == {"asset/sensor": "spine", "log/input": "identity",
                                "asset/mystery": "unknown"}
    r = rows_of(ws)["wave2/identity-sensor"]
    assert r.build.tier == SPINE and not r.gates


# ---------------------------------------------------------------------------
# hy6.61 — say which reading decided, and let the manifest RAISE scrutiny only
# ---------------------------------------------------------------------------

def test_a_row_the_partition_named_by_a_GUESSED_key_says_so(tmp_path):
    """31 of 41 live rows printed `tier: partition via …` about a lookup whose
    KEY came from a directory name. The docstring promises a fallback "is visible
    as such", and that held for the 6 rows reaching the literal NAME_RULE and for
    nothing else. `quick-folds` is the case: there is no `quick/folds` module row
    at all, so its tier comes from a `quick/*` family-prefix guess."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc"}},
                    partition=[("partition-1.jsonl", QUICK)])
    r = rows["wave2/quick-folds"]
    assert r.build.tier == "identity"
    assert not r.build.tier_anchored
    assert "GUESSED" in r.build.tier_source
    out = render([r], [], all_tiers=True)
    assert "1 build(s) were tiered from a partition row found by GUESSING" in out
    assert "0 from a module their own manifest declares" in out


def test_a_manifest_may_declare_a_LIST_of_modules_and_that_is_RECORD_ANCHORED(tmp_path):
    """The contrast, and the fix: `feature` was read as a single string, so
    quick-folds — which ports five modules — could not declare them. Declaring
    them makes the same row record-anchored instead of a name guess."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc",
                                               "feature": ["quick/birth",
                                                           "quick/group",
                                                           "quick/movement"]}},
                    partition=[("partition-1.jsonl", QUICK)])
    r = rows["wave2/quick-folds"]
    assert r.build.tier == "identity"
    assert r.build.tier_anchored
    assert "manifest declares module" in r.build.tier_source
    assert "GUESSED" not in r.build.tier_source
    out = render([r], [], all_tiers=True)
    assert "0 build(s) were tiered from a partition row found by GUESSING" in out
    assert "1 from a module their own manifest declares" in out


def test_a_DECLARED_module_may_RAISE_scrutiny_above_the_name_reading(tmp_path):
    """The direction that is allowed. Nothing about the name `spine-widget`
    reaches a partition row, so the name proxy calls it spine — advisory, never
    gates. Its manifest declares a module the partition tiers IDENTITY, and that
    is believed: a build asking to be judged harder is not the failure mode."""
    rows = rows_for(tmp_path, {"spine-widget": {"seal": None,
                                                "feature": ["asset/sensor"]}},
                    partition=[("partition-1.jsonl", [prow("asset/sensor", "identity")])])
    r = rows["wave2/spine-widget"]
    assert tier_of("spine-widget") == SPINE       # what the name proxy says
    assert r.build.tier == "identity"             # what its declaration raises it to
    assert r.build.tier_anchored and r.gates


def test_a_DECLARED_module_can_NEVER_LOWER_the_tier(tmp_path):
    """THE INVARIANT (`oracle/port_verify.py` I2): the thesis does not write its
    own reading. `port.manifest.json` is written BY THE PORT, so accepting a
    declaration that tiers a build DOWN hands the defendant the pen — a build
    could declare a spine module and buy its way out of the gate.

    Here the name reading says identity (nothing else names this build) and the
    declared module is spine. The stricter reading stands, the declaration is
    printed with its reason, and the row is NOT record-anchored: it did not get
    to decide."""
    rows = rows_for(tmp_path, {"identity-widget": {"seal": None,
                                                   "feature": ["asset/compost"]}},
                    partition=[("partition-1.jsonl", [prow("asset/compost", "spine")])])
    r = rows["wave2/identity-widget"]
    assert r.build.tier == "identity", "a manifest tiered its own build DOWN"
    assert r.gates
    assert not r.build.tier_anchored
    assert "may only RAISE scrutiny" in r.build.tier_source
    assert "asset/compost" in r.build.tier_source, (
        "the overruled declaration must still be visible")


def test_DECLARED_modules_that_DISAGREE_resolve_UNKNOWN_which_is_STRICTER(tmp_path):
    """A list is not a licence to pick. quick-folds' family guess gives identity;
    declaring one identity module and one spine module is not unanimous, and
    UNKNOWN gates — so an ambiguous declaration raises scrutiny rather than
    resolving in the declarer's favour."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc",
                                               "feature": ["quick/birth",
                                                           "asset/compost"]}},
                    partition=[("partition-1.jsonl",
                                QUICK + [prow("asset/compost", "spine")])])
    r = rows["wave2/quick-folds"]
    assert r.build.tier == "unknown" and r.gates
    assert "rows disagree" in r.build.tier_source


def test_a_declared_module_the_partition_does_not_NAME_changes_nothing(tmp_path):
    """The contrast that keeps the declaration from being a second proxy: a
    `feature` naming a module no partition row mentions is not evidence, so the
    name reading stands unchanged and still says it guessed."""
    rows = rows_for(tmp_path, {"quick-folds": {"seal": "abc",
                                               "feature": ["not/a/module"]}},
                    partition=[("partition-1.jsonl", QUICK)])
    r = rows["wave2/quick-folds"]
    assert r.build.tier == "identity"
    assert not r.build.tier_anchored
    assert "GUESSED" in r.build.tier_source


def test_a_single_STRING_feature_still_works(tmp_path):
    """Backwards compatibility, counted: 2 of the 41 live manifests declare a
    `feature` and both declare a string."""
    rows = rows_for(tmp_path, {"identity-quantity-test": {"seal": "abc",
                                                          "feature": "quantity/test"}},
                    partition=[("partition-1.jsonl", [prow("quantity/test", "spine")])])
    r = rows["wave2/identity-quantity-test"]
    # spine, and only because the name reading independently reaches the same
    # row (module tail `quantity/test`) — a declaration alone could not lower it.
    assert r.build.tier == SPINE and r.build.tier_anchored
    assert resolve_tier(load_partition(workspace(tmp_path / "b", {},
                        partition=[("partition-1.jsonl", [prow("quantity/test", "spine")])])),
                        "identity-quantity-test", "", "quantity/test")[0] == SPINE
