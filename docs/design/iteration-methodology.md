# The iteration loop — red, green, *how would I fake this?*, refactor

> Written 2026-07-21, after a day in which five separate defects turned out to be
> one defect wearing five costumes. This is the loop we iterate the port pipeline
> with, and the reasoning for each step. It is short on purpose.

## The failure it exists to prevent

A self-improving system optimizes what it can measure. When the measure is a
proxy for the goal, the system will find the gap and live in it — not from malice,
just from gradient. Everything below is machinery for keeping the measure and the
goal from drifting apart.

Five instances from one day, all the same shape:

| what happened | what got optimized | what we wanted |
|---|---|---|
| the judge scored ports against our own adapter | agreement with *us* | agreement with **farmOS** |
| a port marks its failing fixtures corroboration-only | the score | being correct |
| a bridge declines exactly where it would be wrong | "no failures" | answering |
| a fix landed in code with no fixture to catch its regression | "the bug is fixed" | it **stays** fixed |
| a validation workflow graded a tree that did not contain the change | "the workflow completed" | the thing was tested |

The last one was the orchestrator's, not an agent's. Nobody is outside this.

## The loop

**1. RED — state the goal as a PROPERTY, not as a defect to block.**

A red that says "attack N must fail" moves the goalposts sideways; the next
adversary finds attack N+1. A red that says *"a port that is wrong about farmOS
cannot score better than one that is right"* moves them toward the goal, and
satisfying it is real progress. Properties are also the only reds that can be
*subsumed* — one property closed four open findings at once.

Test for a well-formed red: **could the system satisfy it and still be wrong in
the way that motivated it?** If yes, it is a patch wearing a property's clothes.

**2. GREEN — make it true.**

**3. HOW WOULD I FAKE THIS? — the step that was missing.**

Before shipping, the author asks: *what would satisfy this check while defeating
its purpose?*

This step exists because refactoring alone does not catch proxy-gaming, and we
have the receipt. Invariant 2 said "the defendant holds no pen." It was
implemented faithfully — the manifest field was removed, the CLI flag deleted —
and then a public verb was shipped that re-issues the pack's entire authority.
**The invariant was satisfied; the intention was not.** Thirty seconds of "how
would I fake this?" catches that; a refactor does not, because the refactor is
aimed at the invariant, and the invariant was the thing that had drifted.

It costs a minute. Our adversarial agents answer the same question for ~500k
tokens. Do not make them find what you could have named.

**4. REFACTOR — ask what the solution says about the intention.**

Not "is this clean" but: *given what the adversary just found, what did we
actually believe, and does the structure express it?* The refactor's product is
usually one better-posed question replacing several patches. When four findings
collapse into one mechanism, that is the signal it worked.

Then set the next red as a property, and go again.

## Tiering — this loop is not free

Applied uniformly it costs more than the work. One day of full-weight loops ran
~2.3M subagent tokens. That is right for the foundation and ruinous at 147
features.

> **The rule: does this change touch the INSTRUMENT, or the thing being MEASURED?**

- **Instrument** (the judge, the recorder, the fixture schema, the kernel, a bound
  decision, anything that decides what counts as evidence) → full weight: fresh
  adversaries, a stated property, a GO-test-shaped check.
- **Measured** (a feature port, a build, a flow pack) → cheap tier: green, the
  fake-it question, and a discriminating fixture. Minutes, no workflow.

An instrument that is cheap to change is an instrument nobody can trust.

## Definition of done

**A fix ships with the evidence that would catch its regression.**

This is the day's highest-frequency defect and the cheapest to prevent. The C1
derivation fix is real in `probes.py` and absent from every shipped pack — so a
re-broken adapter would score green on `core-pack` tomorrow, and the two ports the
GO test *proved* distinguishable are byte-identically scored by everything the repo
ships. A fix in the code and not in the evidence is a fix with a half-life.

For a port fix: a fixture that fails before and passes after.
For an instrument fix: an attack, run, recorded, that the instrument now survives —
and recorded as **blocked by construction** or **blocked by a guard**, because a
guard is a patch that passed review and the next adversary walks around it.

## Self-verification is NOT load-bearing

An author checking their own work is worth approximately zero here, and this is
measured, not assumed. In one day:

- a build documented four "load-bearing" prevention gates; none were load-bearing;
- `group_member`'s comment claimed "farmOS's group-membership semantics" while
  implementing neither the recursion nor the time gate that farmOS's own service
  declares;
- a gate test called a `__log` hook that does not exist, asserted nothing, and
  passed green.

Every genuine finding came from a fresh adversary or from the live source. **None
came from an author reviewing themselves.** Self-checks are worth doing — they are
free — but nothing may be *promoted* on one. The moment a self-check substitutes
for an adversary, we are shipping confident prose over broken code, which is the
exact pure-LLM failure this method exists to refute.

Corollary, learned the hard way: **judges are always fresh, never the builder** —
and a judge must prove which tree it tested before its findings count.

> **Reframe (2026-07-21): the courtroom is retired.** See
> `epistemology-charter.md`. The loop stands — red-as-property, green, the
> fake-it question as *calibration*, refactor — but its purpose is dialectic,
> not prosecution: friction in service of revealing what is hidden, between
> parties assumed to be in good faith. "Judge" becomes **reader**, "adversary"
> becomes **interlocutor**, "attack" becomes **counterexample**, migrating as
> code is touched. Defenses target error, saturation, and drift; escalations
> whose only purpose is tamper-resistance against ourselves are out of scope
> by decision. This reframe was decided by Duke, outside the loop — consistent
> with "no account certifies itself."

## The standing reds

Closed:
- *A port that is wrong about farmOS cannot score better than one that is right.*
  (the GO test — was inverted, now 100.0% vs 71.4%)
- **No artifact in the pipeline can endorse a claim its own witnesses contradict.**
  (MetaCoding-96q / MetaCoding-fmw) **Closed by posture, not by construction —
  and the distinction is recorded, not hidden.** The error-shaped forms are
  blocked by construction (witness values checked, orphans refused, evidence
  class re-derived, no public sealing verb). The deception-shaped residue —
  edit value + witness, call `seal_recording()`, full GO-test re-inversion,
  two field edits and a library call — is closed by the charter's stated
  assumption: the harness assumes good faith, its authorities are external
  (live source, reviewed history, human eyes), and no internal machinery can
  defend a system against its own hands. See the posture paragraph in
  `ctkr/ctkr/oracle/pack.py` and `epistemology-charter.md`. The
  history-anchoring red formerly proposed below is superseded by the same
  decision: the `PACKS.jsonl` ledger stays as **citation** (provenance a
  reader can consult), and is not escalated into a prosecution mechanism.

Historical record of the partial closure (kept because the loop's first outing
is itself evidence):
- (MetaCoding-96q) **was PARTIALLY closed — the naive forms only.**

  Real progress, blocked BY CONSTRUCTION: the recorder now writes a WITNESS
  observation carrying the VALUE each probe read, bound to its assertion inside
  the fixture's hash; `load_pack` refuses a fixture its witness contradicts,
  refuses a pack with unclaimed witnesses, and RE-DERIVES the corroboration-only
  exemption instead of believing the label. `ctkr oracle-seal` is removed — a
  seal is issued only by `seal_recording`, from a recording session.

  **Still open, and the implementer's own report overstated the cost of both.**
  It said a forger must now edit "the fixture AND its witness AND
  observation_refs AND the orphan set AND both digests AND re-issue the seal."
  A fresh adversary measured it: `observation_refs` key on `obs_id`, which does
  not change; the orphan set does not change; and `seal_recording` recomputes
  both digests and the seal *for the attacker*. **Two field edits and a library
  call, entirely offline** — and it FULLY RE-INVERTS the GO test (the wrong port
  4/4 = 100% EXIT=0, the right one 3/4) with the header printing
  `0 INVALID EVIDENCE` and no warning of any kind. Completing the subset attack
  by pruning the orphaned witnesses is likewise clean: 9 of 11 fixtures, nothing
  in the artifact saying it is partial, and on the GO pack both ports then score
  2/2 = 100% — the wrong port becomes indistinguishable from the right one.

  **This is the loop working exactly as designed, on its first outing.** The
  author asked the fake-it question and named one real gap (the unkeyed seal) —
  and *understated two others in the same breath*. That is the evidence for
  "self-verification is not load-bearing", generated by the methodology's own
  first use. It is not an argument for skipping step 3; it is the reason step 3
  can never be the last step.

Open:
- **A witness proves what the RECORDER saw, not what farmOS said.** The witness
  is filled from the same `_observe_probe` call that fills the assertion, so a
  wrong adapter produces a wrong fixture and a wrong witness that agree. This
  closes post-hoc editing and does nothing about a mis-derived value — that is
  invariant 1's job (authority + derivation stamps), and it is why a derivation
  correction still invalidates every value recorded under the old one.
- ~~**NEXT RED (proposed): evidence is only what the repository's reviewed history
  says was recorded.**~~ **SUPERSEDED by the charter (2026-07-21).** This red was
  prosecution-shaped: its motivating forger is ourselves, and the charter closes
  that by stated assumption rather than by mechanism. What survives of it is
  citation: the ledger already records every seal a recording issued, and a
  reader may consult it. The original reasoning is kept below because its core
  observation — an unkeyed digest cannot distinguish a recording from a
  simulation — is true and worth remembering. Every forgery that still works
  has the same shape — a
  self-consistent pack built offline, in `/tmp`, by someone who can import the
  sealing library. Chasing that with a stronger hash is the sideways move the
  loop warns about: an unkeyed digest cannot distinguish a recording from a
  simulation, so a better digest buys nothing. The authority a forger does not
  hold here is **the committed history**. A pack becomes evidence when its seal
  is appended to a ledger in the repo by a recording, and that append is
  reviewed like any other change; a pack whose seal has no history is not
  evidence regardless of how well it hashes. Test the red against its own
  standard before building it: *could the system satisfy this and still be wrong
  in the way that motivated it?* — yes, if a reviewer waves through a ledger
  append, so the append must be small, readable, and obviously tied to a run.

- **Group membership's TIME GATE is still undiscriminated by a shipped pack.**
  The recursion half is closed (`group-membership-recurses` in hardening-pack,
  recorded live: `group_member(A, G2) == True`). The flow DSL cannot date a
  group assignment — `assign_to_group` binds no alias and takes no `at`, and
  giving it one changes the port bridge's contract.
