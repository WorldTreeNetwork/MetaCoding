# `ctkr port-verify` — the mechanical JUDGE and the probe-surface contract

Closes blocker **B2** of `eval/ctkr/results/wave1-readiness-2026-07-20.md`
(bead `MetaCoding-kgu`). Before this existed, judging one built port meant three
agents each hand-writing a throwaway TypeScript harness in a sandbox: at 100+
features that authoring is the dominant cost of a wave, and — worse — a harness
bug is indistinguishable from a port bug.

```
ctkr port-verify <fixtures.jsonl> --port <path> [--marks <file>] [--json] [--show-passes]
```

`--port` is a directory containing `port.manifest.json` (or the manifest itself).

Exit codes: `0` clean · `1` a value failure · `2` usage/contract/bridge error
(nothing was judged) · `3` no failures but the verdict is incomplete (gaps or bad
declarations). **A build with gaps never exits 0.**

---

## 1. The probe-surface contract

`ctkr/ctkr/oracle/probes.py` is the single table binding the fixture vocabulary
to an implementation surface:

| glossary assertion | adapter method | args after the subject |
|---|---|---|
| `stock_on_hand` | `stock_on_hand` | measure, unit |
| `adjustment_count` | `adjustment_count` | — |
| `log_status` | `log_status` | — |
| `has_parent` | `has_parent` | *other* (alias → handle) |
| … | … | … |

plus `OPERATION_CONTRACT`, the same for `when` verbs. The oracle runner
(`runner.py`) and `port-verify` both read this table, so "which method answers
`adjustment_count`" cannot drift between the thing that records evidence and the
thing that judges against it. `contract_gaps()` is asserted empty by the test
suite: the glossary and the contract must cover each other exactly.

## 2. What a port declares — `port.manifest.json`

```jsonc
{
  "port": "w0a-asset-inventory",
  "bridge": { "command": ["bun", "run", "port_bridge.ts"], "cwd": "." },
  "capabilities": {
    "operations": ["record_inventory_adjustment"],   // glossary action terms
    "probes": ["stock_on_hand", "stock_pair_count"]  // glossary assertion terms
  },
  "divergences": [],
  "fixture_marks": []
}
```

The bridge also answers `describe` at run time. **If the manifest and the running
bridge disagree, `port-verify` refuses to run** rather than picking one — a
capability claim must be unambiguous.

### The bridge protocol

One JSON object per line, stdin → stdout:

```
→ {"id":7,"op":"stock_on_hand","asset":"A1","measure":"weight","unit":"kilograms"}
← {"id":7,"ok":true,"value":3.0}
← {"id":7,"ok":false,"error":"…","unsupported":true}
```

Protocol ops: `describe`, `reset` (fresh world per fixture), `close`. Domain ops
are named by the contract above. The bridge lives **inside the port** — it is the
port's own statement of how glossary terms reach its surface, written once per
build, not once per judging session.

## 3. The three honesty rules, and where each is enforced

**1 · An unanswerable assertion is a declared gap, never a pass and never a
silent drop.** `PortAdapter` gates every call on the declaration and raises
`Unanswerable` *without touching the bridge*; `Unanswerable` is deliberately not
an `AdapterError`, so no `except AdapterError` can turn it into a value. There is
no code path from an undeclared capability to `AssertionStatus.PASSED`. The
report carries four buckets — `passed` / `failed` / `diverged_as_declared` /
`unanswerable` — and **no field that blends them**: `coverage` (answered ÷ total)
and `value_score` (right ÷ *scored-answered*) are always printed together.

A fixture whose `when` needs an undeclared operation is not run at all: every one
of its assertions is a gap, because nothing about its values was learnt.

**2 · A sanctioned divergence is declared up front, never inferred at scoring
time.** A `Divergence` names the fixture, the assertion, the value the port will
deliver *instead* (`port_value` is required — a sanction covers one stated value,
not any deviation), a reason, and the decision id. Consequences:

* mismatch + matching declaration + declared value delivered → `diverged_as_declared`
* mismatch + declaration + a *different* value → **failed**
* mismatch + no declaration → **failed**, always
* match + a declaration → passed, plus a **declaration problem**: a stale sanction
  is a lie about the port
* declarations are consulted only for ANSWERED assertions, so "it's the
  divergence" can never excuse a gap
* two declarations matching one assertion → hard error (nobody knows which value
  was sanctioned)

**3 · A fixture whose value encodes source insertion order must not score.**
A `FixtureMark` with `corroboration_only` / `order_sensitive` (and a mandatory
reason) makes a fixture run and report normally while being excluded from both
the numerator and the denominator of the value score. Marks live **outside** the
recorded pack — `--marks <file>`, or the manifest — because a recorded pack is
evidence and `port-verify` must never rewrite it.

## 4. The wave-0 pilot build, judged

```
ctkr port-verify eval/ctkr/port_runs/wave0-pilot/w0a-observe/fixtures.jsonl \
  --port eval/ctkr/port_runs/wave0-pilot/w0a-build/build \
  --marks eval/ctkr/port_runs/wave0-pilot/w0a-fixture-marks.json
```

```
  assertions      : 30
  answered        : 18
  UNANSWERABLE    : 12   <- declared gaps, not passes
  scored          : 17   (1 answered but excluded from scoring)
    passed        : 17
    failed        : 0
  coverage        : 18/30 = 60.0%
  value           : 17/17 = 100.0%
```

The pilot's raw "24/30" is now two honest numbers: the build is *right about
everything it can be asked* and *can be asked about 60% of the pack*. The twelve
gaps are `adjustment_count` (no count surface), `log_status` (no lifecycle read),
and two whole fixtures needing `set_log_status` / `set_effective_time` verbs the
build does not have. `w0a-adjustments-sharing-one-effective-time` is marked
corroboration-only and no longer passes for the wrong reason.

Running the *lineage* pack against the same build reports 0/33 answerable and
scores nothing — the shape of a wrong-pack run, not a false green.
