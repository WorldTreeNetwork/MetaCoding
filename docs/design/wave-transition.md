# The wave transition: a ritual that does not depend on remembering it

**Status: LAYER 1 SHIPPED and used, 2026-08-12.** `ctkr/ctkr/wave.py`,
`port_runs/WAVES.jsonl`. **Wave 2 was closed with it the same day — the first
use, which this document called "the honest test of whether it is usable."**
**Kernel versioning stopped being hand-managed, 2026-08-13** — `kernel-frozen`
moved from the B list to the A list, `src/kernel/kernel.lock.json` pairs the
version with the fingerprint it was correct at, and `src/kernel/cli.ts bump`
writes both. Kernel is v1.4.0 (`surface_changed: false` — the number moved, the
answers did not; the real v1.4 is the punt-promotion still ahead).

Layer 2 (`ledger.py` refuses to probe outside an open wave) is `MetaCoding-hy6.66`
and is deliberately sequenced to land *with* the opening of wave 3, never before:
shipping it while no wave is open would refuse every probe in the repo, which is a
self-inflicted outage rather than enforcement.

Duke: *"Sealing is an action that relies on my fallible memory to perform. And the
transition from one wave to another. It seems like we need a ritual for this."*

## What the first use found — three defects, all in the design above

Recorded here because "the first use is the honest test" is only true if the test
is allowed to fail, and it did, three times:

1. **The untracked-file blind spot.** The close passed cleanly on its first dry
   run while `wave.py` — the file implementing the close — sat untracked in the
   tree. Modified files were checked; untracked ones were filtered away entirely.
   Untracked *source* is uncommitted work and untracked *build noise* is not, and
   no rule tells them apart, so modified stays UNSAFE while untracked became
   CARRYABLE: it cannot block a close and it cannot pass unmentioned.
2. **Affirmations could not be declined.** The B list accepted only a name, so the
   sole way to close was to assert all three were TRUE. Wave 2's honest answer to
   `kernel-frozen` is **no** — `KERNEL_VERSION` is still 1.3.0 and wave 1's v1.4
   freeze agenda never landed — and a ritual that cannot record that manufactures
   a false yes at exactly the moment it matters. `--affirm k="no: reason"` now
   records a decline in its own list, kept out of `affirmed` so the row can never
   later be read as a yes.
3. **The A/B split had no analogue of the carry-forward rule.** Section C already
   said "not done" is a legitimate close and "not done and nobody said so" is not.
   The B list was missing its version of that sentence until a real close went
   looking for it.

Depends on [enforceability.md](./enforceability.md), which is the reason this is a
command and not a checklist.

## The problem, stated exactly

Three mechanisms were built to gate "wave-close sealing" — `elenchus
--require-current`, `verdict_currency`, and recipe step 8. None of them runs,
because **there is no wave-close step in code.** Sealing is a human act with no call
site, so every gate hung on it was hung on nothing.

Adding a `wave close` command creates the call site. It does not solve the problem:
a command you must remember to type is exactly as reliable as the memory it depends
on, and the memory is the thing Duke just named as fallible.

## The move: make the next thing you want refuse until the last thing is closed

You cannot forget to close wave N if opening wave N+1 refuses while N is open.

That converts the ritual from **memory-dependent** to **path-dependent**, which
`enforceability.md` measured as the only kind that has ever worked here. And it
inherits the property that makes `ledger.py`'s preflight stick: the refusal arrives
at the moment you are trying to do the next piece of work, when the context is in
your head, rather than at a moment you have to schedule.

Two layers, and the second is what makes it real:

1. **`ctkr wave open <name>` refuses while the previous wave is open.**
2. **`ledger.py` refuses to probe in a wave that is not open.** This is the import
   path — the same surface that made `oracle_preflight` unavoidable. You cannot
   record an observation in an unregistered wave, so registering is not a
   discipline, it is a precondition of doing the work at all.

Layer 2 is the whole design. Without it, layer 1 is another command nobody types.

## Where the state lives

`port_runs/WAVES.jsonl` — append-only, one row per transition, matching the existing
`PACKS.jsonl` convention exactly (the ledger's records live with the ledger, not
with the instrument).

```json
{"record":"open",  "wave":"wave3", "opened_at":"...", "predecessor":"wave2"}
{"record":"close", "wave":"wave2", "closed_at":"...", "elenchus":"results/wave2/elenchus-wave2-2026-08-09.md",
 "kernel":"v1.4", "carried":[{"item":"MetaCoding-hy6.49","reason":"7 builds have no observation lane; remedy uncosted"}],
 "affirmed":["elicitation menu answered","kernel frozen"]}
```

Append-only matters: a wave that was closed with debt and later re-opened is two
rows, not an edit. The history of what we accepted is the point.

## What closing consists of

Three kinds, kept separate because they have different authority. Conflating them is
how a ritual becomes a rubber stamp.

**A — MECHANICAL. The command checks, and can refuse.**
- verdict currency: every identity build has a current, clean verdict *or* an
  explicit carry-forward with a reason (`verdict_currency.py`, already built)
- the workspace is committed; no uncommitted work is being sealed
- a current Elenchus artifact exists for this wave (the file check, not the judgment)
- **the kernel** — `wave open` records `{version, fingerprint}` with no input from
  anyone, and `wave close` recomputes. Three outcomes: *held* (green, silent);
  *bumped mid-wave* (green, and the row carries both versions so no later reader
  has to guess which kernel the wave's builds answered against); *drift* — a gate
  edited with no version move — which is **UNSAFE and uncarryable**, because
  closing would write a version claim into `WAVES.jsonl` that does not describe
  the answers the wave's builds gave. The remedy is one command, so refusing
  costs nothing that fixing it would not.

  **Scope caveat, stated because the check's own wording overreaches it**
  (`MetaCoding-wfz4`): `kernelFingerprint()` hashes only `status.ts`, which is
  element 4 of the five frozen elements. Editing the kind taxonomy, the id/HLC
  scheme, the latest-wins comparator, or the CM registry moves nothing, and the
  check still says "held". That is the fake-it answer for this check, and it was
  found by asking the question rather than by a later judge.
- **the decisions** — every question two or more builders hit independently has a
  recorded answer. Carryable, never unsafe: deciding is judgment, and a wave that
  cannot close until every open question is settled never closes. What it refuses
  is the third state, unanswered *and* unmentioned. A **missing** builders' log is
  also not a pass — "nobody reported a question" is not "nobody had one", and this
  check cannot tell you which.
- **the declarations** — every build in the wave said whether it had to guess at
  anything, via `questions` in its `port.manifest.json`. Three states, not two:
  *declared* (a list, or `none_because` — "nothing came up" is a claim with a
  reason), *silent* (no block at all — the build never said), and *unreported*
  (declared at the end with no in-flight record behind it, meaning the builder
  knew while it was running and nobody could act on it). Unreported leads the
  detail; it is the worse failure. Carryable: all 41 existing manifests are
  silent by construction, and a gate that makes the first close after its own
  introduction unperformable is one people route around.

## What is actually being asked of a person — `wave.py elicit`

`inflight.promotion_candidates` has computed this list since 2026-07-20 and
**nothing ever showed it to anybody.** The close asked instead for the
`elicitation-answered` affirmation, which is a person promising they read a menu
no command ever printed. `promotions.py` prints it, and the close now checks the
half of it that is a fact.

**It is written in plain words, and that is a requirement rather than a
courtesy.** Duke, 2026-08-13: *"It should be really clear. To me, or the person
running this process, what is being elicited, what decisions are being asked
without referencing all our special terms."* This project's internal vocabulary —
punt, promotion, kernel, wave, blast radius, elicitation, binding, pith — is
precise and load-bearing in the code, and unreadable to the person whose judgment
is the entire reason for asking. A question nobody can read is a question nobody
answers. So the translation happens once, at the boundary where a machine hands
work to a human, and `test_promotions.py` fails if any of those words reaches the
menu:

| internal | what the menu says |
|---|---|
| a punt | a builder had no answer and guessed |
| the topic | the question |
| the kernel | the rules every builder follows |
| promotion | decide it once, for everyone |
| the assumption | what they did instead, in the meantime |
| N distinct agents | how many builders hit it independently |

Three answers, each named for what it costs: **shared** (decide once, everyone
follows), **per-build** (each builder decides, and their answers differ),
**later** (it comes back next round, with the reason recorded). Recorded in
`port_runs/DECIDED.jsonl`, append-only — a re-decision is a new row.

**The one derived fact leads every entry: did the builders guess *differently*?**
If they did, the port does not hold an open question, it holds two answers,
already written, in two places. That is damage rather than debt, it is the fact
most likely to change what a person decides, and a reader must not have to notice
it by comparing rows.
- the test suites are green, or their redness is a named carry-forward (`6ep` is the
  standing example: smoke has been red at `smoke-extractor.ts` for the whole wave)

**B — HUMAN. The command asks, records the answer, and cannot verify it.**
- the elicitation menu was answered and the decisions bound
- the Elenchus's pith was *read*, not merely produced

These are recorded as affirmations with a name against them. The command must not
pretend to check them — see `enforceability.md` disposition 3. An affirmation that
looks like a check is worse than an honest question.

**`kernel-frozen` used to be a third, and it was misfiled** (removed 2026-08-13,
after its first and only use, where the honest answer was *no*). Disposition 3
says an affirmation that looks like a check is worse than an honest question. The
converse was never written down and cost the same: **a check parked on the human
list is a toll with no epistemic value.** "Did the kernel change during this
wave?" was computable from `kernelFingerprint()` the whole time. Duke, 2026-08-13:
*"I don't want to manually manage kernel versioning ... The mechanism should be
something that is managed automatically."*

The part of that question that genuinely *was* his is not a yes/no and does not
belong at close time: **should the kernel now change** — which punts recurred
often enough to promote into the shared substrate. That is an intention, and it
reaches a person as ranked candidates on the elicitation menu (`inflight.by_topic`
is the punt-promotion input; `decisions.render_menu` renders it) or not at all.

The general rule this yields, worth applying to the other two: **before putting a
question on the B list, ask what would have to be true for a machine to answer
it.** If the answer is "nothing — we already compute it", it is an A-check
wearing a question's clothes.

**C — CARRY-FORWARD. Recorded, never blocking.**
Everything known-unfinished, each with a reason. **This list becomes the next wave's
ratchet baseline**, which is the unification worth having: the debt we accept is
recorded deliberately at a boundary, by a person, once — instead of accumulating
silently and being discovered by a judge three weeks later.

## Two properties it must have or it will not be used

**Closing must be cheap when nothing is wrong.** One command, seconds. If a clean
close is expensive, the ritual gets skipped precisely when things are going well,
which is most of the time.

**It must be possible to close a wave with debt.** A ritual that only succeeds when
everything is perfect never succeeds. The refusal is reserved for *unsafe*, not
*unfinished*: sealing uncommitted work, or carrying an item with no reason. "Not
done" is a legitimate close with a recorded carry-forward; "not done and nobody said
so" is not.

## How this can be faked

- **Edit `WAVES.jsonl` by hand.** Trivially possible. It is a ledger, not a lock —
  the same status as `PACKS.jsonl`, and the defence is the same: it is reviewed
  history, and a hand-edited row is visible in the diff.
- **Carry everything forward with the reason "known".** The reason field is only as
  good as the review of the commit that adds it. This is the real weakness and it
  should be stated in the command's own output.
- **Hand-edit `kernel.lock.json`** to match a drifted surface, and the kernel
  check reads clean. Same status as `WAVES.jsonl` and the same defence: a ledger,
  not a lock, and a hand-edited pair is visible in the diff.
- **Bump with a four-word reason that says nothing.** Identical weakness to the
  carry-forward reason, and admitted for the same reason.
- **Never open a wave.** Work outside any registered wave dodges layer 2 entirely.
  Mitigation: `ledger.py` refuses when the wave is unregistered, so this shows up as
  a refusal at the first probe, not as silence.
- **Probe without the ledger.** Already an admitted hole (`ledger.py` docstring):
  six lines of urllib gets you an OAuth token. Unchanged by this design.

## Decisions

**1. `wave open` REFUSES, with an override — ruled by Duke, 2026-08-12.**

Refusal is the mechanism; the override is what keeps it usable. The two failure
modes are symmetric and both are fatal: a gate that only warns becomes advisory
within a week, and a gate with no escape hatch gets bypassed by editing the ledger
by hand — at which point you have neither enforcement nor a record.

So the override is not a weakening, it is *where the record comes from*:

- `ctkr wave open <name>` exits non-zero while the predecessor is open.
- `--force <reason>` proceeds AND writes the reason into `WAVES.jsonl` as a row of
  its own. An override is a first-class recorded event, not a silence.
- A `--force` with no reason, or a reason under a few words, is refused. The
  friction is the point: the cost of overriding should be stating why, and that
  cost should land on the person overriding rather than on the next reader.

This mirrors what the flags already do correctly — the mechanism reports, the human
decides, and the deciding is recorded. What it refuses is the *unrecorded* skip.

## Open decisions — these are Duke's, not an implementer's

1. **Is `wave1-c1` a wave, a variant, or a lane?** The naming is already ambiguous
   and the answer decides what `predecessor` means and what `verdict_currency`
   should scope to (`hy6.56`).
2. **Should the Elenchus be an A-check (artifact exists) or a B-affirmation (it was
   read)?** Both, probably — but B has no teeth and A is satisfiable by producing a
   document nobody read.
3. ~~**What closes wave 2?**~~ **ANSWERED 2026-08-12: this did.** Duke: *"ok, it's
   time. close the wave 2."* Sealed with 7 of 10 mechanical checks green, two
   affirmations by name, one declined with its reason, and three items carried
   forward:

   | carried | why |
   |---|---|
   | `verdicts` | 19 gating builds lack a current clean verdict. Every value still reproduces — it is the *evidence* that is unverified, after `hy6.47`/`hy6.48` correctly invalidated four packs predating the mandatory preflight. `hy6.44`, `hy6.49`; remedy uncosted. |
   | `smoke` | `smoke-extractor.ts` emits no `SMOKE_RECORD`, so the runner refuses it as silent. The original crash was fixed; the missing record was not. Standing red for the whole wave — `6ep`. |
   | `untracked:farmos-port` | two generated `.scip` index files; build artifacts, not source. |

   **This carried list is wave 3's ratchet baseline**, which is the unification
   this document argued for: debt accepted deliberately at a boundary, by a
   person, once — instead of accumulating silently and being found by a judge
   three weeks later.

   Answered *around* the close but still open: (1) `wave1-c1`'s status, and (2)
   whether the Elenchus is an A-check or a B-affirmation. In practice it was
   **both**, as this document guessed: `elenchus` is a file-existence A-check and
   `pith-read` is a B-affirmation, because A is satisfiable by producing a
   document nobody opened.

## What this does not solve

Nothing here makes a wave *boundary* a good idea at the moment it fires. It makes
the transition impossible to perform silently. Whether wave 2 should close now, or
absorb another ten builds first, is judgment — and per `enforceability.md`
disposition 3, judgment is what the flags are for and what the Elenchus is for. This
ritual only guarantees that when the transition happens, it happens on the record.
