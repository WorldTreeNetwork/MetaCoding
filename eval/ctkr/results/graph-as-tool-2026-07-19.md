# Graph-as-tool experiment — interactive graph access on a cross-cutting feature (MetaCoding-9h5.11)

> Bead MetaCoding-9h5.11 · 2026-07-19 · Duke's hypothesis: *"the code graph being
> searchable for the LLM — I want that to show its worth… graph value appears at
> complexity the logs+quantities slice never reached."* The 9h5.4 / 9h5.8 line
> measured the graph as a **static brief** (marginal value ≈ 0). This experiment
> tests the graph as an **interactive tool**: two blind Sonnet builders port a
> genuinely cross-cutting farmOS feature; both get the same signatures + fixtures
> + target profile, but **Builder G additionally gets live query access** to the
> full-signal v2 code graph and must log every query. Judge (this orchestrator)
> runs an independent fixture pack against both builds and classifies every graph
> query. Single run per builder; stated where it matters.

## Bottom line

- **Interactive graph access did NOT earn its keep.** Builder G (graph) and
  Builder N (no graph) both scored **10/10 on the independent hardened fixture
  pack, including all 7 non-obvious fixtures.** Zero score delta.
- **The graph cost wall-time and tokens for zero decisions.** G ran **9 graph
  queries**; by its own logged assessment and mine, **0 were decision-bearing, 2
  were corroborating, 7 were dead-ends.** G took **180 s vs N's 137 s (+31 %)**,
  the entire delta attributable to a query phase that changed nothing, and did not
  write a line of its adapter until **+137 s** (N's adapter was done at **+83 s**).
- **The complexity Duke bet on was real — but it lives in the wrong place for the
  graph.** This feature is materially more cross-cutting than logs+quantities (5
  module roots, 27 classes, a 5-dependency DI-injected service). Yet the graph
  still added ≈ 0, because the hard part is the **behavioral semantics** (pending
  ignored, future-dated not-yet-effective, fixed-asset intrinsic geometry,
  same-timestamp tie-break, geometry-from-log-not-location) — and those live in
  the **fixtures/oracle**, not in the CALLS/REFERENCES/CONTAINS structure the graph
  navigates. The graph's own blind spots made this worse: the central service is
  **DI-wired**, so `callers AssetLocation` returns **0 edges**; intra-class
  `$this->` calls aren't captured; and the code is duplicated (`modules/…` vs
  `web/profiles/farm/modules/…`). Every substantive query G tried hit one of these.
- This is the same root cause as 9h5.3/9h5.4/9h5.8, now confirmed at higher
  complexity and in **interactive** mode: **the load-bearing artifact is the oracle
  (fixtures + hand-authored signatures), not the code graph.**

## 1. Feature choice + graph stats

**Chosen feature: asset location & movement** — an asset's *current location* and
*geometry* are not stored fields; they are **projected from movement logs**. The
core service is `\Drupal\farm_location\AssetLocation` (interface
`AssetLocationInterface`), with a `LogLocation` helper and a `GroupAssetLocation`
variant in the group module.

Why this over logs+quantities (justified by v2-graph stats, full-signal
scip-php+tree-sitter graph at `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2`,
8 059 nodes / 11 499 edges):

| stat | value | how measured |
|---|---|---|
| module roots the feature spans | **5** — `asset/group`, `core/location`, `core/ui`, `organization/farm`, `quick/movement` | classes whose file/name matches the feature, non-test, non-dup |
| feature classes (non-test, non-dup) | **27** | same query |
| `AssetLocation` service methods | **10** (`getLocation`, `getGeometry`, `getMovementLog`, `hasLocation`, `hasGeometry`, `isLocation`, `isFixed`, `getAssetsByLocation`, `setIntrinsicGeometry`, `__construct`) | `methods AssetLocation` |
| service constructor dependencies | **5** (`LogLocation`, `LogQueryFactory`, `EntityTypeManager`, `Time`, `Connection`) — cross-cuts log + core DB + clock | source of `AssetLocation.php` |
| cross-module boundary edges **into** `core/location` | 3 (2 EXTENDS, 1 IMPLEMENTS) | boundary query |
| cross-module boundary edges **out of** `core/location` | 32 (16 USES_TRAIT, 15 EXTENDS, 1 IMPLEMENTS) | boundary query |
| `IMPLEMENTS AssetLocationInterface` | **2** (`AssetLocation` core, `GroupAssetLocation` group module) | `implementers` |

The telling stat: the boundary edges are almost all inheritance/trait
(EXTENDS/USES_TRAIT); **CALLS/REFERENCES into the service are ~0** because farmOS
consumers resolve it through the Drupal DI container by service id
(`farm_location.asset_location`), a string the structural graph doesn't connect to
the class. So the feature is *maximally* cross-cutting by module count yet
*minimally* connected by the edge kinds a builder would query — the exact profile
that starves interactive graph use.

## 2. Oracle pack (observed live, never authored)

10 fixtures recorded against **live farmOS 4.x** (`farmos-oracle-www`,
`http://localhost:8095`, admin/admin), all entities prefixed `m11-`, via a
recorder that executes each flow and reads back farmOS's **own published
current-location surface** (the asset's computed `location` relationship and
`geometry` attribute over JSON:API; the future-dated as-of read reproduces
`AssetLocation::getMovementLog`'s `timestamp<=t, status=done, sort -timestamp,-id`
query at the boundary). **7 of 10 are non-obvious** (semantics not recoverable
from the method-name surface alone):

| id | non-obvious? | semantic observed |
|---|---|---|
| `95de1fa8` | — | a done movement places the asset at the location |
| `d4bf80b0` | — | `is_location` flag marks which assets can be locations |
| `590f08ba` | — | the latest done movement determines current location |
| `b1c2e06f` | ✔ | **a pending movement does not change current location** |
| `364220a4` | ✔ | **a future-dated movement is not yet effective as of an earlier query time** |
| `9c55cce5` | ✔ | **a fixed asset ignores movements; geometry = its intrinsic geometry** |
| `8083c6d1` | ✔ | **one movement to multiple locations places the asset at every one** |
| `43a074ca` | ✔ | **two movements at the same timestamp tie-break to the later-recorded one** |
| `885eecc6` | ✔ | **assets-at-location is latest-wins too (moving away removes the asset)** |
| `7c6c376b` | ✔ | **a non-fixed asset's geometry comes from its latest movement log, not the location** |

**Adapter contract = signatures only** (`ADAPTER_SIGNATURES.md`, hand-authored,
the experiment's constant): `makeAdapter(): LocationAdapter` with
`createAsset / recordMovement / setLogStatus / setIntrinsicGeometry` (events) and
`currentLocations / hasLocation / currentGeometry / hasGeometry / isFixed /
isLocation / assetsAtLocation` (projections, `atTimestamp`-parameterised). No
prose semantics — the fixtures are the behavioral spec. A judge-side reference
adapter confirmed the pack + runner are self-consistent (10/10).

## 3. Per-cell fixture results (independent runner, judge-driven)

Runner `judge/runFixtures.ts` (verifier-side, not builder-written) drives each
port's `makeAdapter()` through the contract and compares returned values.

| cell | inputs | own `bun test` | independent pack | non-obvious (7) | verdict |
|---|---|---|---|---|---|
| **Builder N** (no graph) | signatures + 10 fixtures + target profile | 10 / 0 | **10/10** | **7/7** | full pass |
| **Builder G** (graph) | same **+ live graph query tool** | 10 / 0 | **10/10** | **7/7** | full pass |

Both reproduced every non-obvious semantic. Both independently chose the same
local-first design (append-only event log + materialized-view projections) and the
same consistency-model menu picks (`preserve-as-eventual-invariant` for the as-of
reads; a local `(timestamp, seq)` tie-break flagged as needing a UUID/HLC key
before multi-replica sync). **The graph produced no design difference.**

## 4. Query ledger analysis (the key qualitative axis)

Builder G's `graph_queries.log` — 9 queries, auto-logged, each annotated by G with
what it was deciding and what it did with the answer. My classification matches
G's own:

| # | query | result | class | why |
|---|---|---|---|---|
| q1 | `methods AssetLocation` | 12 methods | **corroborating** | method names matched the signatures already in hand; no decision changed |
| q2 | `callers AssetLocation::getLocation` | 0 | **wasted** | dead end — DI-wired, no CALLS edges |
| q3 | `search status` | 20 noise hits | **wasted** | only unrelated Drupal form/test noise; fixtures already give done/pending |
| q4 | `neighbors …getLocation both` | 0 | **wasted** | dead end |
| q5 | `search log_movement` | 0 | **wasted** | dead end |
| q6 | `search LogLocation` | 20 hits | **corroborating** | confirmed a distinct LogLocation helper exists; contract already collapses it |
| q7 | `cypher` literal filter for done/pending | error | **wasted** | Cypher literal-filter mistake; no data |
| q8 | `search "'done'"` | FTS error | **wasted** | trigram/quote artifact; no data |
| q9 | `callers AssetLocation::getGeometry` | 0 | **wasted** | dead end |

**Tally: 0 decision-bearing · 2 corroborating · 7 wasted.** G's own summary
(verbatim): *"none of the graphq queries changed a design decision. All method
names corroborated what ADAPTER_SIGNATURES.md already specified, and the
movement/status/geometry semantics came entirely from FIXTURES.jsonl."*

Two structural reasons the corroborating queries could never have been
decision-bearing here, and the wasted ones were predestined:
1. **The signatures already named the reads** (`currentLocations`,
   `currentGeometry`, `assetsAtLocation`), so confirming the source method names
   (q1) is definitionally corroboration.
2. **The graded semantics aren't edges.** "Pending is ignored," "future is not yet
   effective," "fixed reads intrinsic," the tie-break — these are conditionals
   *inside* method bodies and a DB query string, not CALLS/REFERENCES/CONTAINS
   relationships. The only channel that could carry them (full-text `search` over
   literals) returns the field-name tokens (`is_fixed`, `intrinsic_geometry`) but
   not the *rule*, and the status-string search drowned in Drupal noise. The graph
   surfaces **structure**; the value lives in **behavior**.

## 5. Cost comparison

| metric | Builder N (no graph) | Builder G (graph) |
|---|---|---|
| total build wall-time | **137 s** | **180 s (+31 %)** |
| time to first adapter line | +83 s | +137 s |
| graph-query phase | — | +43 s … +85 s (≈42 s, pure overhead) |
| graph queries run | 0 | 9 (0 decision-bearing) |
| adapter LOC | 211 (+63 eventLog +39 types) | 229 |
| own test suite | 10 pass / 0 fail | 10 pass / 0 fail |
| independent pack | 10/10 | 10/10 |
| est. model spend (Sonnet, not metered) | ≈ $0.15–0.25 | ≈ $0.25–0.40 |

Neither approached the **$3** abort cap. Spend is an estimate (no token meter
exposed to the orchestrator); the **direction** is what matters: G spent strictly
more (extra tool calls + reasoning about their answers) for an identical result.

## 6. Verdict on Duke's hypothesis

**Does interactive graph access earn its keep at complexity? On this feature — no.**

Duke's hypothesis was that the graph's value would appear at complexity the
logs+quantities slice never reached. We deliberately chose a feature that *is* that
complexity (5 modules, a DI-injected 5-dependency service, cross-cutting into log +
group + geometry). The graph still contributed **0 decision-bearing queries, 0
score delta, and −31 % wall-time**. The reason is not that the feature was too
simple; it is that **complexity in a port lives in the behavioral semantics, and
those are carried by the oracle (fixtures + signatures), not by the structural
graph.** The graph answers "who calls / what implements / where is this field
named" — real questions, but not the questions a value-equivalent port must answer
("does a pending movement count," "what wins a timestamp tie"). And precisely at
this complexity, the graph's structural coverage is *weakest* (DI wiring, intra-
method conditionals, code duplication), so the interactive channel dead-ended.

This closes the loop opened by 9h5.4/9h5.8 from a new direction: the static-brief
line showed the graph's *content* adds ≈ 0; this shows the graph's *interactivity*
adds ≈ 0 even when the feature is genuinely hard — because the missing information
was never in the graph to be queried. Where a graph query **would** be decision-
bearing is a build with **no fixtures** (the unaided-discovery regime of 9h5.8
Cell 4); but any port that has the oracle already has the answers the graph lacks.

## 7. Honesty notes

- **Single run per builder.** One blind Sonnet build each; no statistical spread.
  A different G run might phrase queries better — but the *structural* reasons the
  graph can't carry these semantics (DI wiring, behavior-in-method-bodies) are
  run-independent.
- **Signatures are still hand-authored** (the experiment's constant, as designed).
  As in the whole 9h5 line, the load-bearing oracle artifact is not graph-derived.
  Both builders benefited from the signatures naming the reads; the graph was
  tested *on top of* that, which is the honest question ("does interactive graph
  access add anything beyond the oracle?" — answer: no).
- **Fixtures partly "teach to the test":** the 7 non-obvious given/when/thens
  literally contain the graded behaviors, by design (fixtures ARE the spec). So
  this measures "does graph access add value beyond fixtures" (no), not "can a
  builder discover these unaided" (untested here; 9h5.8 Cell 4 is the unaided
  probe).
- **The graph tool works.** `search`, `methods`, `implementers`, `neighbors`,
  `cypher` all returned correct data when the data existed (e.g. `implementers
  AssetLocationInterface` correctly found the cross-module `GroupAssetLocation`).
  The 7 wasted queries are not tool bugs (2 were G's own Cypher/FTS syntax slips);
  they are the graph honestly having nothing to say about in-method value rules.
- **Spend not metered**, reported as estimates; the qualitative comparison
  (G strictly ≥ N in time and tokens for equal output) is robust regardless.
- The as-of fixture (`364220a4`) is observed by reproducing farmOS's documented
  movement-log query at the JSON:API boundary (same contract farmOS.js/Aggregator
  use), not by an internal Drupal read — consistent with the oracle's boundary
  discipline.

## Artifacts & sandbox paths (ALL sandbox unless noted)

- **In-repo committed (production):** this report only —
  `eval/ctkr/results/graph-as-tool-2026-07-19.md`. No `.metacoding/` data-dir
  created or mutated.
- **Experiment workspace (SANDBOX):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/m11/`
  — `oracle/` (recorder `farm.py` + `recorder.py`), `FIXTURES.jsonl` (10),
  `ADAPTER_SIGNATURES.md`, `BUILD_INSTRUCTIONS.md`,
  `judge/` (`runFixtures.ts`, `refAdapter.ts`, `builders_start.txt`),
  `builderN/{inputs,build}`, `builderG/{inputs,build,graph-ro}`.
- **Builder G query ledger (SANDBOX):**
  `…/scratchpad/m11/builderG/build/graph_queries.log` (9 queries + annotations).
- **Graph queried (SANDBOX, READ-ONLY copies of the v2 full-signal graph):**
  `…/scratchpad/m11/builderG/graph-ro` and `…/scratchpad/graph-v2-ro`, both copied
  from `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2` (unmutated).
- **Live oracle:** farmOS 4.x Docker `farmos-oracle-www` @ `http://localhost:8095`
  (admin/admin) — used to record the m11 fixtures; all entities prefixed `m11-`.
- **Farm source read by the JUDGE only** (never by builders), for authoring the
  oracle: `/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/core/location/`.

No push/merge; bead MetaCoding-9h5.11 left open.
