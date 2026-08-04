# Index fitness: what a graph must establish before it may answer

> **SUPERSEDED 2026-08-04 by [graph-as-cache.md](./graph-as-cache.md).**
>
> Kept deliberately, and not to be deleted: its refutation history is the most
> valuable content in this repo on the subject. Three fixes, three fresh judges,
> three refutations — each fix directionally right and one layer short — is what
> established that the entry has no boundary, which is the successor's root
> finding. Read this document as evidence, not as instruction.
>
> **Two claims in the text below are FALSE and are corrected here (`zpi`):**
> * fake-it #3 is marked "Refuted and re-closed (MetaCoding-9ed)". It is **not
>   closed**: `Store.upsertSymbol`/`addEdge` are public on the exported barrel,
>   take no ticket and call no gate (`qv0`, measured 12 → 28 symbols under a
>   record reading fitness 12).
> * the claim that "basename correspondence distinguishes farmOS-in-Docker from
>   a vendored-dependency index (no basename corresponds)" is both superseded by
>   `eeb2bf8` and **false on its premise** — real vendored trees preserve
>   upstream layout, so every local path is a path *suffix* of its vendored twin
>   and matches one rung higher, earning `ratio: 1.0` (`5fi`, re-opened).
>
> A fourth refutation arrived without anyone attacking the gate: a correct,
> 100%-corresponding graph of a **relationship-free codebase** is persisted
> REFUSED, because `NO_RELATIONAL_EDGES` is a count used as a proxy for
> capability. Reproduced independently at `d8bee31`.

**Status:** IMPLEMENTED 2026-08-04 (root 2 then root 1, evidence alongside each).
Not yet judged — a fresh reader closes the beads, not the builder.

Where it lives:

| piece | file |
|---|---|
| the persisted record, RUNNING marker, pid/heartbeat | `src/store/health.ts` (`index-health.sqlite`) |
| the index session — the ONLY exported ingest entry | `src/ingest/session.ts` |
| the write capability that makes that true | `src/ingest/ticket.ts` (`MetaCoding-9ed`) |
| the measurements (contribution / fitness / correspondence) | `src/ingest/fitness.ts` |
| read-time typing + aggregating refusal | `src/mcp/health-gate.ts` |
| `status` / `describe_api` health lines | `src/index-state.ts`, `src/mcp/tools.ts` |
| the ten contrast pairs | `src/ingest/fitness.test.ts`, `src/ingest/session.test.ts`, `src/mcp/health-gate.test.ts`, `src/ingest/seam.test.ts` |

Two things this build does NOT claim:

* **Open red #2 is still open.** Re-ingesting yesterday's `.scip` at a new commit
  re-stamps every symbol, so `contribution` passes with a large number while the
  graph holds yesterday's facts. `index_identities` (path + sha256 + size) makes
  it visible to a reader. Citation, not prevention.
  *Corrected `MetaCoding-19g`:* the citation was recorded but **not comparable** —
  the health table is `PRIMARY KEY (repo, branch)` with `DO UPDATE`, so writing
  day 2 destroyed day 1 and the identical sha256 was visible only to a reader who
  had written the previous value down out of band. Finalized records are now
  appended to `index_health_history`, each record carries the previous run's
  identities in `prev_index_identities`, and `describeIndexRepetition` renders the
  sentence: *"ingested the SAME index file as the previous run (sha eef719a3) at a
  NEW commit."* Comparable citation. Still not prevention.
* **`watch`'s incremental writes after the initial pass are not re-gated.** The
  initial full pass runs inside a session and produces the same verdict as
  `index`; per-file updates afterwards do not re-run the measurement, and the
  record carries `watching: true` plus the owning pid so a reader can see it.

**Status of the original design:** proposed, 2026-08-04.
**Origin:** `MetaCoding-0sd` (refuted fix) → fresh-architect redesign.
**Beads:** `0sd`, `4kg`, `5fi`, `e6z`, `ae5`, `hy6.16`.

## The harm this exists to prevent

A full 41-row re-scoring pass was computed over a graph holding `CALLS = 0` and
`REFERENCES = 0`, and the empty result was mistaken for a real one
(`MetaCoding-hy6.16`). The pass did not crash. It produced numbers. The numbers
were wrong in a way nothing downstream could see.

That is the failure. Everything below is subordinate to it.

## Two roots, four defects

A first fix (`0c13fa2`) added a write-time gate. A fresh judge refuted it with four
findings. They are not four bugs; they are two roots.

### Root 1 — every measurement is taken from the nearest available number, not from the set its claim is about

| claim | subject of the claim | quantity actually read |
|---|---|---|
| "this run produced symbols" | this run's contribution | repo-wide census, history-blind |
| "SCIP produced something" | this run's SCIP output | document count — an empty document is a document |
| "the graph covers the repo" | files of the local tree | documents whose path may come from any filesystem |
| "measured from the store, never the accumulators" | the wiring in `main.ts` | nothing — tests call `storeCensus` directly |
| "scoped to (repo, branch)" | this repo's slice | true in code, undiscriminated by any fixture |

`4kg`, `5fi` and `e6z` are three faces of this. So is the original `0sd`, if you
read "availability instead of outcome" as the same substitution one level up.

`e6z` is not a testing gap sitting alongside two bugs. It is *the mechanism by which
root 1 is invisible*, and it will re-manufacture `4kg` and `5fi` under new names
after any fix that does not change how the evidence is constructed. Every existing
fixture is confirmatory; none is a contrast.

The gate's own header comment asks the fake-it question, names the `4kg` case
("coast on a PREVIOUS good run's symbols"), and answers it with a document count —
an answer that could not have come out any other way. The methodology's
does-your-evidence-discriminate test, failed inside the section that asks it.

### Root 2 — the verdict is an event, not a state

The gate's judgement lives in a process exit code and nowhere else. `status`,
`serve`, `describe_api`, the MCP graph tools, the CTKR tools and the eval harness
cannot know that the last run was killed or refused.

`ae5`: `SIGKILL` mid-ingest leaves 1,724 symbols and 0 edges — the `hy6.16` shape
exactly, because the loader upserts symbols before edges — and `status` reports
`Indexed: 1724 symbol(s)`.

**An empty result from an unfit graph is byte-identical to an empty result from a
fit one.** That sentence is `hy6.16`.

Note the asymmetry: root 1 has consumed all the attention; **root 2 caused the
actual 41-row loss.** Root 1 governs whether the diagnosis is correct. Root 2
governs whether anyone ever hears it.

## The property

> **A graph whose fitness for (repo, branch, commit) has not been established
> cannot produce an answer that is indistinguishable from one produced by a graph
> whose fitness has been.**

Tested against the motivating failures:

- `hy6.16` — the rescore receives a typed refusal, not `[]`. ✅
- `ae5` — a killed run leaves fitness *unestablished*; blocked by construction, not detected. ✅
- `0sd` — the refusal survives the process. ✅
- `4kg` — dissolves into two separate true facts; see below. ✅
- **Wrong-but-plentiful edges — NOT covered.** The property is about establishment,
  not correctness. Named, not hidden.

What the property is *not*: "a run must contribute N symbols." A legitimate
re-index of unchanged content contributes zero. A rule that false-alarms on the
most common invocation is a rule people disable.

### Why `4kg` dissolves

There are two distinct facts, and the old gate reported one while the operator
asked about the other:

1. **The store's fitness**, established for `(repo, branch, commit)` by whichever run established it.
2. **This run's contribution**, which may legitimately be zero.

A no-op re-ingest at the *same commit* into an already-fit store is **defensible** —
the store genuinely is fit. What is not defensible is the same run at a **new
commit**: fitness established at W, the run claims to advance to X, contributes
nothing, and everything downstream believes it is looking at X. That is the
real-world instance (index today, re-index next week after the lane breaks), and it
needs no threshold — `repo_commit_sha` is already stamped.

The discriminating fixture `4kg` actually needs is the **commit-advancing** one.

The other half of `4kg` *is* a straight failure: SCIP was requested and no SCIP lane
wrote a single **store-visible symbol this run**. That never false-alarms on a
no-op, because an idempotent `MERGE` still re-stamps `indexed_at`.

## Design

### 1. An index *session*, in the ingest layer

`runIndexSession(store, intent, fn)` — above `extractor`/`scip`, below `cli`.
`intent` carries repo, branch, commit sha, run stamp, requested lanes, operator
overrides.

- On entry: write a **RUNNING** record for `(repo, branch)`.
- `fn` indexes; lane outcomes accumulate.
- On exit: finalize to **HEALTHY / REFUSED / OVERRIDDEN**.

A process that dies never finalizes. **`ae5` is closed by construction** — the store
says RUNNING forever and every reader sees it. Roughly ten lines buy what the
staging model would buy for ~200 seconds of extra I/O per repo.

`indexDirectory` and `loadScip` stop being exported ingest entry points and become
internal to the session. That is what makes `watch`'s current bypass *structurally
impossible* rather than fixed-once. The CLI's remaining job is one line: map the
persisted verdict to an exit code. **The exit code becomes a view of the fact, not
the fact.**

Not the store's write path: a write path that refuses partial writes cannot express
deliberate partial indexing and would fight the incremental primitives. Fitness is a
judgement about a completed session.

### 2. Scope every measurement to its claim's subject

**`Symbol.indexed_at` already exists**, is set from one constant per run, is threaded
through both lanes, and is *not* COALESCE-protected — it is always overwritten. So
"the last run that touched this symbol" is exactly recoverable.

**Per-run measurement is available today with zero schema change and zero
migration.** Edges carry no provenance but attribute through their source symbol.

Both quantities — this run's contribution *and* the store's fitness — go in the
record, explicitly labelled as answers to different questions. They are never
substituted for each other again.

### 3. Coverage becomes *correspondence*, and names its own granularity

Replace `max(lane.files) / sourceFiles` with a store-side set intersection over
`Symbol.file`. `5fi`'s fixture dies immediately: forty symbols pathed
`node_modules/dep/vN.ts` intersect ten `.go` files in zero places.

For foreign paths (container-prefixed builds, scip-php without the PSR-4 sidecar),
degrade granularity and **record which level was used**:

1. exact relative path
2. path **suffix** (survives an `/app/web/` container prefix)
3. **basename** correspondence (survives an arbitrary prefix)
4. `UNMEASURABLE(reason)`

Basename correspondence distinguishes farmOS-in-Docker (every `farm_animal.module`
appears in both sets) from a vendored-dependency index (no basename corresponds).
So `--load-scip` is **not structurally unmeasurable** — it is measurable at a weaker
granularity, and the granularity is part of the record. `UNMEASURABLE` is a real
outcome and **never counts as a pass on its own**.

Also record the ingested index's identity (path + sha256 + size).

### 4. The record is read, and empty-from-unfit is a different type

Persist to a **new `index-health.sqlite` beside `graph.lbug`** — metadata about the
graph, not in it; and SQLite gives real transactions the graph path does not expose.
**Absent file ⇒ `UNKNOWN`, never `HEALTHY`.** That is the whole migration story, and
it is the honest reading of every store indexed before this ships.

Consumers, in order of how much they matter:

- **Aggregating consumers first** — CTKR motif mining, role-equivalence, cross-repo
  comparison, `graph_diff`, the eval harness, any rescoring pass. **Refuse by
  default** on `REFUSED` / `RUNNING` / `UNKNOWN`; require explicit acknowledgment.
  *This is the direct fix for the historical harm: an aggregate silently absorbs a
  zero, and `hy6.16` was an aggregate.*
- **Graph query tools** — an **empty** result against a repo whose fitness is not
  established is an **error**, not `[]`. Non-empty carries a `health` caveat.
  Empty-from-healthy stays `[]`. Breaking change to the MCP surface; it is the one
  place the property is enforced by *type* rather than by a banner someone must read.
- **`status` / `serve` / `describe_api`** — per-repo health line beside the symbol
  count, with failure codes and the fixing command.

### 5. Overrides become durable facts

`--allow-empty-index` and `--min-coverage 0` currently produce one stderr line and
vanish. They should finalize the record as `OVERRIDDEN` with the flag and value,
visible at read time forever. Parse them strictly: today any value other than the
literal `"false"` *enables* `--allow-empty-index`, and `--min-coverage 0` silently
disables the floor.

## Alternatives rejected

| Option | Why not |
|---|---|
| **Staging + atomic promote** | Closes only `ae5`, which the RUNNING marker closes far cheaper. ~2× a 169–222 s ingest. No transaction API on `Store`; two files cannot be promoted atomically anyway. Rhetorically seductive and epistemically empty: a validated-empty graph promoted atomically is still empty. |
| **Per-run delta as a pass/fail rule** | Rejected as a *rule*, adopted as a *measurement*. A legitimate re-index contributes zero; a must-be-positive rule false-alarms on the most common invocation. The **commit** is what makes zero-contribution a failure. |
| **`run_id` on all sixteen REL tables** | Unnecessary — edges attribute through their source symbol. |
| **Read-time visibility instead of a write gate** | Rejected as an either/or. The diagnosis is only cheap at write time (lanes, intent, tree are gone later); the harm lands at read time. The design's answer is that the write-time gate's *product* is the persisted fact. |
| **Keep the gate in the CLI, add a call in `cmdWatch`** | Fixes one caller; leaves the property depending on every future caller remembering. |

## How would we fake this design?

1. **Plentiful but meaningless edges** — correct paths, one bogus edge each: fitness
   `HEALTHY`. **Not caught**, exactly as today. Presence is cheap to measure;
   quality needs an oracle. Named, not hidden.
2. **Re-ingesting yesterday's `.scip` at a new commit** — every symbol is re-stamped
   with the new run's `indexed_at`, so "this run wrote symbols" passes with a large
   number while the graph holds yesterday's facts. **This is `4kg` wearing the new
   design's clothes.** Recording the index's sha256 makes it *visible to a reader* —
   citation, not prevention. Standing open red, not a closed one.
3. **Writing around the session** — any direct `Store.upsertSymbol` leaves a stale
   `HEALTHY`. Why the session must be the *only* exported ingest entry: otherwise
   the fix is a guard, and a guard is a patch the next reader walks around.
   **Refuted and re-closed (`MetaCoding-9ed`).** The first attempt closed this
   with a text scanner over `import` lines; a fresh judge got past it in nine
   shapes and grew a HEALTHY store from 24 symbols to 52 under a record that
   still read `fitness 24`. It is now closed by a capability instead
   (`src/ingest/ticket.ts`): every ingest primitive requires an `IngestTicket`,
   and a ticket cannot write into a slice whose record currently reads
   established. Writing into an `UNKNOWN` / `RUNNING` / `REFUSED` slice stays
   possible and cannot manufacture a stale `HEALTHY`. **Still open at one level
   up: forging the record itself** — nothing stops a module from writing
   `status: "HEALTHY"` with invented numbers.
4. **`UNMEASURABLE` as the new escape hatch** — the weakest joint. The four-level
   ladder exists so it is the *fourth* answer, not the first.
5. **A RUNNING marker that cries wolf** — a crash during finalization leaves RUNNING
   on a good graph; users learn to ignore it. Needs a pid/heartbeat so `status` can
   tell "running now" from "abandoned". A real ongoing cost.
6. **Our own evidence** — `e6z`'s lesson points at this document. A suite built from
   the same quantities cannot detect that a quantity was substituted.

## Evidence that must ship with it

Each item is a **contrast pair** whose halves must give *opposite* verdicts. A
proposed test that is not a contrast is not yet evidence.

1. **Store vs accumulators** (kills `e6z` M3) — a *wired* test where accumulators are non-zero and the store is empty, plus its mirror. The existing wired test uses an empty `.scip` whose accumulators are also zero, which is why M3 survived.
2. **Repo scoping** (kills `e6z` M2) — populated repo B, empty repo A; A must be refused. Load-bearing for `d1l.2`'s shared corpus.
3. **Threshold bracketing** (kills `e6z` M1) — 9% refused, 11% established.
4. **Same-commit vs commit-advancing zero-contribution** (the corrected `4kg`) — identical barren ingest passes at the same commit with `contribution: 0` recorded, refuses at a new commit.
5. **Correspondence vs document count** (kills `5fi`) — the judge's `vendor40.scip` refused, a real 40-document index of the same tree passed. Fixtures already exist.
6. **Granularity ladder** — a container-prefixed index measurable at suffix level; an unrelated-basename index `UNMEASURABLE`.
7. **Crash visibility** (`ae5`) — SIGKILL, then `status` *and* a graph query report unestablished fitness. Asserted on the record and the tool response, **never on an exit code**.
8. **Read-time typing** (`hy6.16`) — the same query returning zero rows against a fit graph and a RUNNING graph must return **different types**. *This is the one test that would have prevented the 41-row loss.*
9. **`watch` inherits** — `metacoding watch` over the fosite shape produces the same refusal as `metacoding index`. If not, the seam is in the wrong place.
10. **Mutation-test the instrument**, with both guards: assert every anchor matched; verify the baseline clean before *and* after.

Per the epistemology charter: none of the above may be promoted on the builder's own run.

## Sequencing and cost

**If only one thing ships: the persisted record and the RUNNING marker (root 2)** —
that is the root that caused the measured loss, and it is the smaller change.
Measurement corrections (root 1) second, **evidence rewrite alongside, not after**,
or `e6z` regenerates.

Compute cost is negligible (~16 count queries plus one intersection against a
169–222 s ingest). The real costs are the MCP response-shape change and `UNKNOWN` on
every existing store — including production farmOS.

## Consequence for `d1l.2` today

`d1l.2` may **not** trust the exit code when indexing into the shared corpus: a
corpus is by definition a store that already holds repos, which is exactly the `4kg`
coasting case. Until root 1 is fixed, `d1l.2`'s own instruction to assert non-zero
`CALLS` and `IMPLEMENTS` **by type** after every ingest remains the load-bearing
check. The bead has been corrected.
