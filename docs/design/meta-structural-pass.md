# The Meta-Structural Pass — advisory structural gating for cross-paradigm ports

> Bead **MetaCoding-9h5.1**. Written after the first end-to-end port run
> ([`eval/ctkr/results/vertical-slice-logs-quantities.md`](../../eval/ctkr/results/vertical-slice-logs-quantities.md)),
> where **8 of 8** structural punch items were waived as a single conscious paradigm
> divergence (PHP plugin registry → local-first event log). This document specifies the
> *disciplined replacement* Duke required so "structure is advisory" never degenerates into
> "we had gates and decided to skip them all."

## The problem this run exposed

The port-verifier ([`src/ctkr/verifyPort.ts`](../../src/ctkr/verifyPort.ts)) scores a
re-implementation `S'` against the extracted spec of `S` on five §7 gates — role coverage,
interface preservation, composition preservation, fidelity, cycle consistency — and emits a
localized *punch list* rather than a boolean. Port Decisions
([`src/ctkr/portDecisions.ts`](../../src/ctkr/portDecisions.ts)) let a builder **waive** a
punch item as a deliberate delta; raw and net-of-waivers scores are kept separate so a waiver
reclassifies a failure, never weakens the check.

That machinery works — but the vertical slice drove it to its degenerate limit. When the whole
architecture is a conscious divergence, **every** structural failure is a legitimate waiver, and
the structural verifier contributes *no independent acceptance evidence*. It confirmed disciplined
divergence, not correctness; the **value-equivalence oracle** (7/7 fixtures) carried the entire
acceptance weight. A verifier that can be 100% waived without penalty is indistinguishable, from
the outside, from a verifier that was simply switched off.

The fix is **not** to make the gate stricter, and **not** to delete it. It is to (a) declare the
divergence *before* the build so waivers are pre-registered hypotheses rather than post-hoc
excuses, (b) require any change to a gate's authority to be recorded in an append-only second-order
ledger, and (c) redefine what "did we get the structure right?" *means* once the gate is advisory.

---

## §a — The meta-structural PRE-BUILD pass

**When:** before any build, as soon as a source graph and a target profile both exist.

**What it does:** compares the **source paradigm** against the **target profile** across four
axes and emits a **paradigm-divergence declaration**.

| axis | source (e.g. farmOS/Drupal) | target (local-first) | verdict-driving? |
|---|---|---|---|
| `consistency_model` | `strong` | `eventual` | **yes** |
| `coordination_layer` | `true` (central authority) | `false` | **yes** |
| `language` | `php` | `ts` | no — handled by §6.2 normalization |
| `deployment` | `central-server` | `local-first` | no — informative context |

A divergence is **material** (downgrades the verdict) iff `consistency_model` **or**
`coordination_layer` differ. Language and deployment are recorded for context but do not by
themselves suppress the verdict — cross-language bias is already the job of the §6.2 edge-alphabet
normalization, and deployment substrate is downstream of the two consistency axes.

**The declaration pre-registers which gates are predicted non-informative and why.** Grounded in
the logs+quantities run (Stage 3b), a central-authority → distributed divergence is expected to
dissolve the source's *shape idioms*:

| gate | under a central-authority → local-first divergence | prediction |
|---|---|---|
| role coverage | role classes key on a class/plugin hierarchy the value port replaces with string-tagged events | **non-informative** |
| interface preservation | provided exports change usage mode (request-time call → event append) across the paradigm | **non-informative** |
| composition preservation | `EXTENDS`/subtype protocol ops don't survive; log kinds are events, not subclasses | **non-informative** |
| cycle consistency | whole regions are legitimately remapped, so `G(F(s))=s` drops for benign reasons | **non-informative** |
| **fidelity** | functor fidelity over the pairs that *do* map is still a real structure-preservation measure (it hit ceiling that run) | **BINDING** |

This is exactly the run's signature: the four "non-informative" gates produced all 8 punch items
and were all waived; **fidelity was the one gate at ceiling** — the single real structural signal.
The prediction is therefore not a heuristic guess but the encoded reading of the first data point.
It lives in `predictNonInformativeGates()` and is revised only through the §b ledger.

**Waivers become pre-registered hypotheses.** After the build, each waiver is classified:

- **Predicted waiver** — waives a punch item on a predicted-non-informative gate. Expected;
  this is the divergence declaration coming true. No signal.
- **Unpredicted waiver** — waives a punch item on a gate that was declared *binding*
  (`unpredictedWaiverCount`). This is a **first-class failure signal**: either the pre-build pass
  mis-predicted the divergence, or the builder drifted and is now waiving something the paradigm
  did *not* license. A fidelity waiver under advisory mode is the canonical example — it means the
  mapped subgraph itself is not faithful, which no paradigm difference excuses.
- **Stale waiver** — a decision record that matches no punch item at all
  (`staleWaiverCount` / `staleWaivers`). Spec drift or over-waiving; already surfaced by the
  existing waiver machinery, now promoted to a headline signal.

A post-hoc waiver that the pass did not predict is thus **itself a signal**, precisely as the
mandate requires.

### Inputs / defaults

`verifyPort` takes an optional `targetProfile` and optional `sourceParadigm`
(`VerifyPortOptions`). When a `targetProfile` is supplied without a `sourceParadigm`, the source is
assumed to be `CENTRAL_AUTHORITY_PARADIGM` (strong + coordination-layer + central-server) — the
canonical Drupal/farmOS port-loop baseline — and the declaration records
`sourceParadigmAssumed: true` so the assumption is never silent. With **no** `targetProfile`, the
verifier behaves exactly as before: `verdict: "binding"`, no divergence object, gate scoring
byte-for-byte unchanged. The `TargetProfile` shape is the consistency-relevant subset of
[`target-profile.md`](./target-profile.md) (`consistency_model`,
`capabilities.coordination_layer`).

---

## §b — The metric-update protocol (cybernetic second-order layer)

The primary system scores ports. The **secondary system adjusts the primary system's mechanism** —
suppresses a gate, replaces its acceptance signal, or re-weights it. The rule: **the secondary
system may only act through a recorded, append-only ledger. No silent mechanism change.**

Any change to a gate's authority requires an entry answering three questions:

1. **Rationale** — why the change is warranted (the observation that motivates it).
2. **Replacement acceptance signal** — what now carries the acceptance weight the gate used to
   carry. A suppression with no replacement is rejected by construction; that is the
   "we skipped them all" failure the mandate forbids.
3. **Reversal condition** — the observation that would *undo* the change. A change with no
   falsifier is dogma, not a metric update.

### Format & location

Append-only JSONL at **`eval/ctkr/metric_updates.jsonl`** (repo-level, because it governs the
*verifier mechanism* across runs — unlike per-subsystem Port Decisions, which live in the data-dir
under `port_decisions/<subsystem>.jsonl`). One object per line:

```jsonc
{
  "id": "MU-001",                       // stable unique id
  "date": "2026-07-19",                 // ISO-8601
  "author": "duke@worldtree.io",
  "target": "verdict",                  // gate name | "verdict" | "prediction-model"
  "change": "suppress",                 // suppress | replace | re-weight | add | restore
  "trigger_observation": "…",           // the observation that motivated the change (§b.1)
  "replacement_signal": "…",            // what now carries acceptance (§b.2) — REQUIRED for suppress
  "reversal_condition": "…",            // the observation that would undo it (§b.3)
  "evidence_refs": ["eval/ctkr/results/vertical-slice-logs-quantities.md#stage-3b"],
  "supersedes": null                    // id of a prior MU this revises, or null
}
```

`change` vocabulary: `suppress` (remove a gate's verdict authority), `replace` (swap its acceptance
signal), `re-weight` (change its floor/ceiling), `add` (introduce a new gate/prediction), `restore`
(reverse a prior suppression — the reversal_condition fired). A `re-weight` of
`DEFAULT_GATE_THRESHOLDS`, a change to `predictNonInformativeGates`, or the advisory downgrade
itself are all metric updates and all require an entry.

The ledger is **append-only**: a change is never edited in place; it is superseded by a later
entry naming it in `supersedes`. The reversal of a change is itself a `restore` entry, so the full
history of the mechanism is reconstructable — the second-order system has a memory.

The first entry, `MU-001`, records this very change (the advisory downgrade); see the seeded
ledger.

---

## §c — What "did we get the structure right?" means when the gate is advisory

When the verdict is advisory, the boolean "all gates at ceiling" no longer answers the question.
The answer this run establishes has three parts, in order of load-bearing:

1. **The value-equivalence oracle carries acceptance.** "Did we get the structure right?" reduces,
   for a cross-paradigm port, to "does the port deliver the same values?" — answered by the
   semantic fixture pack (7/7), not by structure preservation. A port that is value-equivalent and
   structurally divergent is *correct*; a port that is structurally identical and value-divergent
   is *wrong*. Structure is downstream of value here.

2. **The pre-registered divergence declaration carries structural discipline.** The declaration is
   the audit trail that the divergence was *reasoned about before the build*, not rationalized
   after. It answers "did we get the structure right?" as "did the structure diverge exactly where
   we predicted it would, and nowhere else?" A run whose waivers all land on predicted-
   non-informative gates got the structure right *in the disciplined sense*: it diverged as
   declared.

3. **Unpredicted waivers + stale waivers are the new structural failure signals.** With the gate
   advisory, a **non-zero `unpredictedWaiverCount` or `staleWaiverCount` is the failure the gate
   used to be.** An unpredicted waiver means the divergence was not the one declared (mis-prediction
   or drift); a stale waiver means the decision log has rotted against the spec. These two counts —
   surfaced first-class in the report and its banner — are what a reviewer reads instead of the
   suppressed pass/fail. **Advisory does not mean unchecked; it means the check moved from
   "gates pass" to "no unpredicted or stale waivers, and fidelity holds."**

Crisply: acceptance = value oracle; structural discipline = declared-vs-actual divergence match;
structural failure = unpredicted waiver ∨ stale waiver ∨ a binding-gate (fidelity) failure.

---

## Implementation map

| concept | code |
|---|---|
| paradigm descriptors | `SourceParadigm`, `TargetProfile`, `ConsistencyModel`, `CENTRAL_AUTHORITY_PARADIGM` in `verifyPort.ts` |
| pre-build comparison | `computeParadigmDivergence()`, `predictNonInformativeGates()` |
| declaration on the report | `PortVerificationReport.paradigmDivergence`, `.verdict` |
| first-class signals | `.unpredictedWaiverCount`, `.staleWaiverCount` |
| advisory banner | `formatReport()` renders the `PARADIGM DIVERGENCE — verdict ADVISORY` block |
| metric-update ledger | `eval/ctkr/metric_updates.jsonl` (this doc §b) |
| tests | `src/ctkr/verifyPort.test.ts` — "advisory verdict under paradigm divergence" + pure-function describes |

Gating behavior is **unchanged when paradigms match or no profile is supplied**: same-language
same-consistency ports, and every existing caller, keep `verdict: "binding"` and the full gate
authority.
