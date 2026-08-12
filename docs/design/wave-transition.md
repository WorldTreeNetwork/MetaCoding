# The wave transition: a ritual that does not depend on remembering it

**Status:** proposed, 2026-08-12. Duke: *"Sealing is an action that relies on my
fallible memory to perform. And the transition from one wave to another. It seems
like we need a ritual for this."*

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
- the test suites are green, or their redness is a named carry-forward (`6ep` is the
  standing example: smoke has been red at `smoke-extractor.ts` for the whole wave)

**B — HUMAN. The command asks, records the answer, and cannot verify it.**
- the elicitation menu was answered and the decisions bound
- the kernel version is frozen
- the Elenchus's pith was *read*, not merely produced

These are recorded as affirmations with a name against them. The command must not
pretend to check them — see `enforceability.md` disposition 3. An affirmation that
looks like a check is worse than an honest question.

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
- **Never open a wave.** Work outside any registered wave dodges layer 2 entirely.
  Mitigation: `ledger.py` refuses when the wave is unregistered, so this shows up as
  a refusal at the first probe, not as silence.
- **Probe without the ledger.** Already an admitted hole (`ledger.py` docstring):
  six lines of urllib gets you an OAuth token. Unchanged by this design.

## Open decisions — these are Duke's, not an implementer's

1. **Does `wave open` refuse, or warn loudly?** Refusing is the design; warning is
   the safer first version and is also how a gate quietly becomes advisory forever.
2. **Is `wave1-c1` a wave, a variant, or a lane?** The naming is already ambiguous
   and the answer decides what `predecessor` means and what `verdict_currency`
   should scope to (`hy6.56`).
3. **Should the Elenchus be an A-check (artifact exists) or a B-affirmation (it was
   read)?** Both, probably — but B has no teeth and A is satisfiable by producing a
   document nobody read.
4. **What closes wave 2?** It is open now, by this design's own definition, with 49
   open beads and 12 identity builds lacking verdicts. Closing it is the first use
   of the ritual and the honest test of whether it is usable.

## What this does not solve

Nothing here makes a wave *boundary* a good idea at the moment it fires. It makes
the transition impossible to perform silently. Whether wave 2 should close now, or
absorb another ten builds first, is judgment — and per `enforceability.md`
disposition 3, judgment is what the flags are for and what the Elenchus is for. This
ritual only guarantees that when the transition happens, it happens on the record.
