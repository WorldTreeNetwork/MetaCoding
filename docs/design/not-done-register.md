# The not-done register, 2026-08-07 → 2026-08-12

**Status:** observed, 2026-08-12, at Duke's instruction — *"record everything that we
didn't do."* Written by the builder, so it is a starting point for a fresh reading
rather than an authority. Every line is checkable against `bd` and `git log`.

## The number that frames it

**49 beads filed in five days, still open.** 23 of them P1. Over the same window the
count closed is a small fraction of that. Findings are being generated faster than
they are being closed, and by a mechanism that works: most were found by fresh
adversaries, several inside fixes for earlier findings.

That is not obviously bad — a project that stops finding things has usually stopped
looking — but it has a consequence nobody has decided about: **the backlog is now
the largest single artifact this effort has produced.** It should be read as one.

## 1. Built, correct, and wired to nothing

The most expensive category, because the work is done and yields nothing.

- `ctkr/ctkr/verdict_currency.py` — `hy6.54`. Nothing calls it.
- `ctkr/ctkr/elenchus.py --require-current` — `3oe`. Nothing calls it.
- `ctkr port-verify` — existed and worked from 2026-07-20 and was not run once
  against wave 2 until 2026-08-11, when it scored 60/60 cold on the first try.
  Twenty-one builds shipped past it.

See `enforceability.md`. The common cause: all three were specified to hook a
"wave-close sealing" step that does not exist in code.

## 2. Claimed, then found wrong by someone else

Each of these was stated confidently by the builder and refuted by a fresh reader.
Listed because the *rate* matters more than any single entry.

- The port-verify brief's arithmetic: "34 manifests, 31 bridges" were workspace
  totals including the four verified builds. Correct figures 30 and 27.
- "The seventeen have observations in the wrong format" — true of ten. Seven have no
  observation lane at all (`hy6.49`).
- "Distillation from transcripts is mechanical" — refuted (`hy6.50`). A distiller
  minting both assertion and witness from one authored projection satisfies the
  witness check by construction. The cheap remedy for `hy6.44` is dead and **has no
  replacement plan**.
- The `verdict_currency` gate shipped containing four of its author's own mutations
  and passed everything (`hy6.52`). The commit message asserted a live result
  produced from the pre-mutation file.
- Recipe step 8 silently reversed a bound decision for 19 of 34 manifests
  (`hy6.51`).
- `instrument-inversion`'s first threshold never fired across the episode it was
  written from — the flag was calibrated against its own founding case and failed.

## 3. Found and not fixed

- `6ep` — `bun run smoke` is **RED at `smoke-extractor.ts`** and predates all of
  this work. The smoke suite has been the baseline for several changes while
  carrying a known failure nobody has looked at.
- `3gz` — the 43 sealed packs were never re-recorded against the 128-module oracle.
- `hy6.48` — the four clean verdicts rest on packs recorded 2026-07-23, two weeks
  before the oracle preflight became mandatory, and `pack.seal.json` carries no
  preflight attestation. Nothing can distinguish a gated pack from an ungated one.
- `hy6.47` — `port-verify` scores clean over declared capabilities the pack never
  drives. `identity-lab-test` is clean at 22/22 with three of four operations never
  exercised.
- `hy6.36` — the hy6.28 gate reaches one build in five; `identity-transplanting` got
  an interim hand-written declaration rather than the migration.

## 4. No path to done

Where the remedy itself is missing, not merely unscheduled.

- **`hy6.49` / `hy6.44`** — seven builds have no observation lane, and the cheap
  distillation route is refuted. Their only honest path is real recording against
  the oracle, which nobody has costed.
- **`x5l`** — the port is not a running system: no server, no entry point, no
  deployable artifact. Recorded in the recipe as "not yet a step" precisely because
  nobody has decided what it would serve.
- **The 17 unjudged builds** — 30 manifests, 27 bridges, no verdicts, and under the
  identity-tier ruling (`hy6.51`) most are not required to have any.

## 5. Deferred deliberately, and correctly

Not failures. Recorded so they are not silently re-scoped.

- Step 5 of `lessons-as-mechanism.md` (`a3m`, `mutate.ts`) — the document conditions
  it on whether steps 1–4 paid off, and that is Duke's call, not an implementer's.
- Reopening the risk partition to gate spine builds — reaffirmed as-is (`hy6.51`),
  with the accepted cost stated.
- Step 9 (the running system) — deliberately not written, on the grounds that a step
  defined by nobody is the kind that gets skipped.

## 6. What the process did NOT do to itself

- **No Elenchus for 18 days and 88 build commits**, until one was convened on
  2026-08-09. All three of its pith questions were recurrences of wave 1's.
- **No fresh judge on several changes** until Duke asked for one by name; the
  standing rule now exists (`bd remember judge-every-completed-unit`) because the
  builder shipped, self-reported, and flagged the absence of a judge instead of
  calling one.
- **The lessons were already written down.** `lessons-as-mechanism.md` opens with
  that observation on 2026-08-07 and the five days since contain at least three
  violations of rules documented before it was written.

## The honest summary

The instrument for finding defects in this project is excellent and is running well
ahead of the instrument for fixing them. Four of the five most expensive events in
this window were not missing knowledge — the rule was written down, in this repo,
before the violation. That is an argument for mechanism over documentation, which is
what `lessons-as-mechanism.md` already says, and it is still mostly unbuilt.
