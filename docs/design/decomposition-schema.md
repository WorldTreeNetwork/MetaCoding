# The Decomposition Meta-Schema — the fixed document set for any port

The discipline question, answered once ([`port-loop-plan.md`](./port-loop-plan.md) cross-cutting
machinery #1): **when we decompose *any* codebase for re-implementation, what must the output
always contain, and what is free to vary per instance?** This doc fixes the mandatory document
set every decomposition produces, states how each document maps onto artifacts the pipeline
*already* emits, names the two genuinely new artifacts, and draws the line between the mandatory
core and the instance-flexible periphery (harvest lanes, target profile, port-decisions log).

It is a **contract over the existing artifacts, not a parallel system.** Nothing here re-derives
the structural lane ([`ct-subsystem-extraction.md`](./ct-subsystem-extraction.md)) or the
intention lane ([`ct-intention-extraction.md`](./ct-intention-extraction.md)); it names the
*documents* those lanes must jointly cover and pins the ones that currently fall through the
cracks. Cards and port briefs are **renderings** over this set (§10), never its source of truth.

Companions: [`ct-subsystem-extraction.md`](./ct-subsystem-extraction.md) (structure lane, cards,
invariance tiers I/N/A §6.1), [`ct-intention-extraction.md`](./ct-intention-extraction.md)
(intention harvest, portability tiers intent-I/N/A §7.2, the port brief §4, intention-load §5),
[`port-loop-plan.md`](./port-loop-plan.md) (the farmOS instantiation, intent-CM tag, Phase 0
declarative lane), [`ctkr-l3-artifacts.md`](./ctkr-l3-artifacts.md) (provenance + determinism
conventions this doc inherits wholesale), [`ctkr-artifacts.md`](./ctkr-artifacts.md) (L1 Parquet
schema conventions), [`../notes/entropy-as-dial.md`](../notes/entropy-as-dial.md) (dials, not
truths — every threshold below is one).

Decisions honored, not relitigated:

- Structure is name-blind; intention never flows back into the math (intention doc §0). This
  schema sits entirely *downstream* of the frozen structural elements.
- Portability tiers are **intent-I / intent-N / intent-A** (intention doc §7.2); structural
  invariance tiers are **I / N / A** (subsystem doc §6.1). They are different axes on different
  objects; §6.3 reconciles them so the Invariant Register carries one coherent tag.
- The N=1 problem is real (subsystem doc §1.2). Every judgment tag in this set is *corrected*
  when a port supplies the second instance; the document set is not one-shot.
- Cards/briefs are derived and regenerable (subsystem doc §8.1, intention doc §4). This doc
  makes that a hard rule (§10), not a convenience.

---

## 0. Thesis — three claims

1. **The mandatory core is fixed and codebase-independent.** Seven documents — Feature
   Inventory, Domain Glossary, Data Shapes, Behavioral Scenarios, Invariant Register, Seam Map,
   Warnings/Conflicts — must be produced for *every* decomposition, farmOS or otherwise. A
   decomposition missing any of them is incomplete by definition, not by taste. The seven are
   chosen so that together they answer the re-implementer's whole question: *what features exist,
   in what vocabulary, over what data, behaving how, under what constraints, across what seams,
   with what caveats.*

2. **The core is a contract over existing artifacts, with exactly two gaps.** Five of the seven
   documents are already carried (some fully, some partially) by `subsystems.parquet`,
   `interfaces.parquet`, `data_shapes.parquet`, `operads.parquet`, `intention_signals.parquet`,
   and `subsystem_cards.jsonl`. Two are genuinely missing and get new artifacts:
   **Feature Inventory** (`features.parquet`) and **Invariant Register** (`invariants.parquet`).
   Naming the gaps precisely is half the value of this doc.

3. **Everything else is instance-flexible and attaches without touching the core** (§9):
   which harvest lanes ran (declarative-config, git, community), whether a target profile was
   supplied, and the running Port Decisions log. The system must produce a valid decomposition
   with *none* of these; they only enrich, never gate.

---

## 1. The mandatory document set at a glance

| # | Document | Answers | Producing stage | Backing artifact | Status |
|---|---|---|---|---|---|
| D1 | **Feature Inventory** | *What user-visible capabilities exist, and how do they decompose?* | Phase 0 declarative lane / feature harvest | `features.parquet` | **NEW — gap** |
| D2 | **Domain Glossary** | *What does this domain call its things, and what do those terms mean?* | Intention harvest (A3/A4/A5/S2) → synthesis | `intention_signals.parquet` (rows) + card `glossary` field | Partial — has home, no standalone artifact |
| D3 | **Data Shapes** | *What data crosses boundaries, in what shape, flowing which way?* | Structural Stage B (§3) | `data_shapes.parquet` | Covered |
| D4 | **Behavioral Scenarios** | *What value does the system deliver, given/when/then, at the value level?* | Intention synthesis from S1 (§5) | card `behavioral_scenarios` field | Covered (field), value-level rule new |
| D5 | **Invariant Register** | *What must always hold, how portable is it, and where is it enforced?* | Invariant harvest + tiering (§6) | `invariants.parquet` | **NEW — gap** |
| D6 | **Seam Map** | *Where are the subsystem boundaries and what are the interface contracts?* | Structural Stages A–C (§2–§4) | `subsystems.parquet`, `interfaces.parquet`, `operads.parquet` | Covered |
| D7 | **Warnings / Conflicts** | *Where must the re-implementer not trust the obvious reading?* | Conflict detection (§6) + intention-load (§5) | card `conflicts` + `intention_load` fields | Covered (fields) |

The rule of coverage: **a decomposition is complete iff all seven documents are populated for
every subsystem, with `spec_basis` / coverage notes marking the thin spots** (never a silent
omission — the honesty gauges of subsystem doc §8.1 and intention doc §5.4 extend to every
document here). "Populated" tolerates "empty with a reviewed reason"; it never tolerates absent.

Sections §2–§8 take the seven in re-implementer reading order: features first (orientation),
warnings last (caveats), matching the port brief's own ordering (intention doc §4.2).

---

## 2. D1 — Feature Inventory  *(NEW: `features.parquet`)*

**Purpose.** The top-level map of *what the system does for its users*, decomposed into named
capabilities with their dependencies. This is the one document that is neither a structural
element nor an intention signal — it is the **product decomposition**, the answer to "if I
re-implement this, what is the checklist of things it must still do?" Every other document is
scoped or cross-referenced against it. Without it, a decomposition is a pile of subsystems with
no statement of what capability each serves.

**Why it is a gap.** The structural lane produces *subsystems* (cohesion communities) and the
intention lane produces *purpose paragraphs*, but neither produces an enumerated,
dependency-linked **feature list**. Subsystems are an implementation partition; features are a
product partition; they are related (§2.1) but not identical. Nothing in the current artifact set
carries the feature axis.

**Producing stage.** A feature-harvest pass, lane-dependent:

- **Declarative-config lane** (the strong case — port-loop Phase 0): where the source encodes
  features declaratively (module manifests, route + permission tables, plugin registries), the
  feature list is *read*, not inferred. farmOS: module ≈ feature, `.info.yml` + routing +
  permissions give the list and the dependency graph for free (§11).
- **Structural fallback** (no declarative manifest): features are proposed from subsystem
  boundaries + interface exports (each externally-callable cluster of exports is a candidate
  feature) and labeled by the intention lane. Lower confidence; marked as such.

**Schema sketch** (`features.parquet`, one row per `(run_config, feature_id)`):

```jsonc
{
  "feature_id": "...",            // blake3(repo, config, feature-key)
  "repo": "...",
  "name": "...",                  // declarative key where available, else L3 label
  "source_basis": "declarative | structural",   // how it was derived — the honesty gauge
  "declarative_ref": "...",       // e.g. farmOS "farm_harvest" module, or null
  "depends_on": ["feature_id"],   // feature-level dependency edges (free from manifests)
  "subsystem_ids": ["..."],       // FK → subsystems.parquet — the M:N feature↔subsystem map
  "interface_refs": ["..."],      // FK → interfaces.parquet — the exports that realize it
  "intent": "...",                // L3 — one-line capability statement (intent-I)
  "schema_version": 1
}
```

### 2.1 Feature ⇄ subsystem is many-to-many, and that is the point

A feature may span several subsystems (a "record a harvest" feature touches logging, assets,
quantities); a subsystem may serve several features. The `subsystem_ids` list records the mapping,
and **the disagreement between the feature partition and the subsystem partition is itself a
finding** — a feature that smears across many subsystems is a cross-cutting concern the port must
handle deliberately; a subsystem serving one feature is a clean vertical slice (a good first port
target, per port-loop Phase 4). This is the feature-axis analogue of the structure↔declared-module
disagreement the subsystem partition already surfaces (subsystem doc §2.1).

---

## 3. D2 — Domain Glossary  *(has a home; needs a standalone artifact)*

**Purpose.** The normalized domain vocabulary — each term with a one-line meaning — giving the
re-implementer *the language to think in before any structure arrives* (intention doc §4.2 item 2).
This is precisely what a name-blind spec withholds and what the strongest re-implementation
judgment calls run on.

**Producing stage.** Intention harvest of A3 (enum/constant/config-key names), A4 (type + field
names), A5 (naming patterns across a role class), S2 (interface identifiers), normalized via the
intention doc §7.1 tokenizer + affix tables, synthesized into term→meaning by the cheap labeler.
Glossary entries are built from **intent-I material only**; intent-N terms appear *restated* (the
role meaning, not the affix); intent-A never appears (intention doc §7.2).

**Mapping to existing artifacts.** The *source rows* already exist in `intention_signals.parquet`
(the harvest's ground truth, one row per indicator with provenance). The *synthesized glossary*
already has a home: the `glossary` field added to `subsystem_cards.jsonl` (intention doc §9.1). The
gap is only that there is no **corpus-level** glossary artifact — glossary today is per-card, so a
term used by five subsystems is synthesized five times with no canonical entry. Recommended: a
thin derived `glossary.jsonl` (corpus-scoped, one row per canonical term with its per-subsystem
usages), deduping the per-card entries. This is a *convenience index over `intention_signals` +
card glossary fields*, not a new source — flagged as open decision (a) in §12.

**Schema sketch** (glossary entry, whether corpus `glossary.jsonl` or card field):

```jsonc
{
  "term": "...",                  // normalized (tokenized) canonical form
  "surface_forms": ["..."],       // raw spellings observed (retained per §7.1)
  "meaning": "...",               // L3, one line, distilled from docstrings/usage
  "portability_tier": "intent-I", // intent-I | intent-N (restated) — intent-A excluded by construction
  "signal_refs": ["..."],         // FK → intention_signals rows that cite it
  "used_by_subsystems": ["..."]   // corpus-scoped only
}
```

---

## 4. D3 — Data Shapes  *(covered: `data_shapes.parquet`)*

**Purpose.** The data that crosses subsystem boundaries, field-level, with flow direction —
what the port *must reproduce semantically* (boundary shapes) versus what it *may restructure*
(internal shapes). This is a **semantic** contract, not a schema dump: per port-loop Phase 2 the
port's data model is free to differ everywhere below the boundary line (event log + materialized
views instead of Drupal tables), so Data Shapes records *what data means and which way it flows*,
never *how it is stored*.

**Producing stage.** Structural Stage B (subsystem doc §3): type-closure over the data-flavored
edge kinds (`READS_FIELD` / `WRITES_FIELD` / `TYPE_OF` / `RETURNS_TYPE` / `CONSTRUCTS`), fused with
the A4/S4 intention layer for per-field meaning.

**Mapping.** Fully carried by `data_shapes.parquet` (subsystem doc §3): `boundary` bool,
`field_name`, `field_type`, read/write-by-internal/external flags, `constructed_by`. The intention
lane adds per-field *meaning* (A4/S4) rendered into the card's fused `data_shapes` table
(subsystem doc §8.1). **No new artifact.** Carry the `alphabet_coverage` note per lane so a thin
shapes section reads as "extractor gap," not "no data model" (subsystem doc §3 reality check).

**One addition this contract imposes:** each boundary shape row that participates in an invariant
(a uniqueness constraint on a field, a required non-null) generates a cross-reference into the
Invariant Register (§6) — Data Shapes says *what the field is*; the Invariant Register says *what
must always be true of it*. The two are joined on `(type_symbol_id, field)`.

---

## 5. D4 — Behavioral Scenarios  *(covered field; the value-level rule is the new discipline)*

**Purpose.** The system's delivered behavior as **value-level** given/when/then scenarios — the
port's acceptance list. The load-bearing word is *value-level*: a scenario states *what value the
system delivers*, in Domain-Glossary terms, **never** a SQL trace or a data-model replay. Per
port-loop Phase 2 the value-equivalence oracle is explicitly *not* trace replay — "after recording
a harvest log with quantity X against asset A, A's yield total reflects X" is a scenario; "row
inserted into `field_data_quantity` with `entity_id=…`" is not. The port's data model differs
everywhere below the value line, so any scenario that mentions storage is a defect.

**Producing stage.** Intention synthesis (cheap model, mostly transcription) over the **S1 harvest**
— test names + bodies + assertion messages, the one place intention is written down *and* machine-
checked (intention doc §1, §4.2 item 7). Normalized across test-framework grammars via the
intention doc §7.1 marker-vocabulary map so `test_*`, `it("should …")`, `#[test]`, and table-driven
Go all collapse into one scenario form.

**Mapping.** Carried by the `behavioral_scenarios` field on `subsystem_cards.jsonl` (intention doc
§9.1), distilled from S1 rows in `intention_signals.parquet`. **No new artifact.** This contract
adds one rule the intention doc leaves implicit: **scenarios are written in Domain-Glossary
vocabulary and are storage-free** — a lint over synthesized scenarios rejects any that name a
table, column, or persistence primitive.

**Schema sketch** (behavioral scenario entry):

```jsonc
{
  "scenario_id": "...",
  "feature_id": "...",            // FK → features.parquet — scenarios roll up to features
  "given": "...", "when": "...", "then": "...",   // all in glossary terms, storage-free
  "value_assertion": "...",       // the observable value delivered (the oracle's target)
  "source_test_refs": ["..."],    // FK → intention_signals S1 rows — every scenario cites its test
  "portability_tier": "intent-I"  // behavioral scenarios are intent-I by construction
}
```

Scenarios are the seed for port-loop Phase 2's semantic fixture pack and Phase 4's verifier; they
carry `feature_id` so the acceptance list rolls up to the Feature Inventory.

---

## 6. D5 — Invariant Register  *(NEW: `invariants.parquet`)*

**Purpose.** The explicit list of **things that must always hold** — the constraints a port breaks
silently and catastrophically if it doesn't know them. Uniqueness, referential integrity, ordering
("X must init before Y"), value bounds, legal state-machine transitions, access rules, arithmetic
conservation ("quantities sum"). These live scattered across the source — DB constraints, type
signatures, guard clauses, test assertions, config annotations, WHY-comments — and **no single
document collects them today.** For a local-first re-implementation this is the highest-stakes
document: the invariants a central-authority app enforces for free (§6.2) are exactly the ones an
eventually-consistent port must consciously re-answer.

**Why it is a gap.** Invariants are *implied* by many existing artifacts (an operad protocol law is
an ordering invariant; a boundary data shape's non-null is a value invariant; an S3 error message
encodes a failure-policy invariant) but are **never gathered into one register with a portability
judgment and an enforcement source**. Scattering is the failure mode; the register de-scatters.

**Producing stage.** An invariant-harvest pass that *joins across* the other documents rather than
introducing a new signal source:

- from `operads.parquet` boundary/protocol ops → **ordering** invariants;
- from `data_shapes.parquet` + declarative-config lane → **structural** invariants (uniqueness,
  referential integrity, required fields — for farmOS, read directly from Drupal field/entity
  annotations, Tier S);
- from S1 tests asserting a constraint and S3 error semantics → **behavioral/policy** invariants;
- from A3 policy constants (`MAX_RETRIES = 3`) → **value-bound** invariants.

Tier assignment is mechanical-seeded, LM-adjudicated (§6.3), same split as every other tier in the
pipeline.

**Schema sketch** (`invariants.parquet`, one row per `(run_config, invariant_id)`):

```jsonc
{
  "invariant_id": "...",          // blake3(repo, config, statement-digest)
  "repo": "...",
  "statement": "...",             // L3, one sentence, glossary terms ("asset yield = Σ harvest quantities")
  "kind": "ordering | uniqueness | referential | value-bound | state-transition | access | conservation",
  "scope_refs": {                 // what this invariant is about — joins into the other documents
    "subsystem_ids": ["..."], "feature_ids": ["..."],
    "data_shape_refs": ["..."],   // (type_symbol_id, field)
    "operad_op_ids": ["..."]
  },
  "portability_tier": "intent-I", // intent-I | intent-N | intent-A  — §6.3
  "consistency_sensitivity": "CM-hard | CM-soft | CM-none",   // orthogonal axis — §6.2
  "enforcement_source": ["db-constraint","type-system","test","config-annotation",
                          "code-guard","operad-law","docstring"],   // where it is CHECKED today
  "evidence_refs": ["..."],       // FK → intention_signals / data_shapes / operads rows
  "adjudication": "mechanical | lm-confirmed",
  "schema_version": 1
}
```

### 6.1 Every invariant carries two independent tags

The bead asks for "portability tier intent-I/N/A/CM." Design decision, stated once: **CM is not a
fourth value of the portability axis — it is a second, orthogonal axis.** An invariant can be
intent-I (survives any stack) *and* consistency-model-sensitive (assumes central authority). Folding
CM into the I/N/A enum would lose exactly the case that matters most: a *universal* domain rule that
a *distributed* target must re-answer. So the register carries **`portability_tier` ∈ {intent-I,
intent-N, intent-A}** and **`consistency_sensitivity` ∈ {CM-hard, CM-soft, CM-none}** separately.
Read them as a pair.

### 6.2 The consistency-model axis (`consistency_sensitivity`)

Straight from port-loop Phase 3: a source app built on a central authority silently assumes ACID
transactions, unique constraints, autoincrement ids, server-side access checks, and revision locks.
Every invariant that leans on one gets a **CM** grade:

| Grade | Meaning | Example | Port consequence |
|---|---|---|---|
| **CM-hard** | Cannot hold under eventual consistency without a chosen resolution strategy | "asset id is globally unique and monotonic"; "only one open till per register" | Target-adaptation section MUST choose: convergence rule (CRDT/LWW), or move to a coordination layer, or weaken — a conscious Port Decision (§9) |
| **CM-soft** | Holds eventually; transient violation is tolerable | "yield total reflects all harvests" (converges as events replay) | Preserve as an eventual invariant; note the convergence window |
| **CM-none** | Independent of consistency model | "quantity is non-negative"; "a log has a timestamp" | Port verbatim |

CM grades are **mechanically seeded** (autoincrement / unique-constraint / transaction / access-check
detection over the declarative lane and edges) and **LM-adjudicated**. Per port-loop Phase 3 the CM
grade *conditions the target-adaptation section of the brief and nothing else* — it never alters the
harvest or the intent. A decomposition run **with no target profile still emits CM grades** (they
describe the *source's* assumptions); the profile only decides how the brief *responds* to them.

### 6.3 Reconciling the portability tiers

Two tier vocabularies exist upstream and the register must not invent a third:

- **Structural invariance tiers I / N / A** (subsystem doc §6.1) tag *card fields* (role classes,
  shapes, topology) by what a port must preserve / normalize / shed.
- **Intention portability tiers intent-I / N / A** (intention doc §7.2) tag *intention signals*
  by what survives a stack change verbatim / restated / not at all.

An invariant is a *statement* harvested from intention and cross-checked against structure, so its
portability tag is the **intention** vocabulary (`intent-I/N/A`), which is what the bead names.
Where an invariant is *also* backed by a tier-I structural fact (an operad protocol law, a boundary
shape), that structural backing is recorded in `enforcement_source` (`operad-law`) and `evidence_refs`
— it *raises confidence* in the intent-I assignment but does not change the axis. Stated crisply:
**structural tiers grade fields; portability tiers grade statements; the Invariant Register is a
statement document and uses the statement vocabulary.**

---

## 7. D6 — Seam Map  *(covered: `subsystems` + `interfaces` + `operads`)*

**Purpose.** Where the system divides and how the pieces contract with each other: subsystem
boundaries, the interface (provides/consumes) at each seam, and the composition/protocol algebra
across seams. This is the re-implementer's structural skeleton — *the order-of-operations contracts
a port breaks first and silently* (subsystem doc §4.3).

**Producing stage.** Structural Stages A–C (subsystem doc §2–§4): partition (DECOMPOSE), boundary
+ interface extraction, role inventory + operad recovery.

**Mapping — fully covered, three artifacts:**

- `subsystems.parquet` + `subsystem_members.parquet` — the boundaries, with `boundary_confidence`
  and `placement` so the re-implementer knows which assignments were judgment calls (subsystem doc §2.4).
- `interfaces.parquet` — every crossing morphism as a provides/consumes row with edge kind and
  count; the subsystem-level dependency topology is the quotient of these (subsystem doc §3).
- `operads.parquet` (+`subsystem_id`, `is_boundary_op`) — the composition laws and, crucially, the
  **protocol** (boundary ops: init-before-use, acquire-then-release), each an ordering contract
  that also feeds the Invariant Register (§6, `operad-op_ids`).

**No new artifact.** The Seam Map is a *view* joining these three, rendered into the card's `roles`
/ `composition_rules` / `interface` sections. This contract adds one requirement: **every seam's
interface contract must state its invariance tier** (subsystem doc §6.1 I/N/A) so a port knows which
seams are contracts external code observes (tier-I, must preserve) versus internal factoring
(tier-A, free to restructure).

---

## 8. D7 — Warnings / Conflicts  *(covered: card `conflicts` + `intention_load`)*

**Purpose.** The explicit "do not trust the obvious reading here" list — where structure and
intention disagree (a "Cache" that mutates external state), where structure alone underdetermines
the spec (business-rule predicates whose rule lives entirely in names/tests), and where even
intention is thin (flag for human review). This is the document that keeps a port from confidently
re-implementing a lie.

**Producing stage.** Conflict detection (intention doc §6: mechanical detectors + LM adjudication)
and the intention-load indicator (intention doc §5: the `D`/`R` scores → structure-clear /
intention-critical / ambiguous).

**Mapping — covered by two card fields:**

- `conflicts` on `subsystem_cards.jsonl` — port-critical conflicts (a strong intention signal
  contradicting a tier-I structural fact) and advisory dissonance (intention doc §6.1). Each states
  *both* readings, epistemically labeled, with the builder instruction ("trust structure for what
  happens, the name for what was meant").
- `intention_load` per element (intention doc §5.4) — the class + `D`/`R` scores + drivers, routing
  builder attention and evidence budget.

**No new artifact.** This contract adds the ordering rule (intention doc §4.2 item 8): warnings
render **port-critical conflicts first, then intention-critical elements, then ambiguous, then
declared debt** (`HACK`/`TODO` markers — the port *may* resolve them but must *decide*, per §9's
Port Decisions log). Declared debt is where D7 hands off to the instance-flexible Port Decisions log.

---

## 9. Instance-flexible parts and the attachment rule

Everything above is mandatory and codebase-independent. The following vary per instantiation and
**attach without changing the mandatory core:**

| Instance part | What it is | Attaches via | If absent |
|---|---|---|---|
| **Harvest lanes enabled** | Which optional signal lanes ran: declarative-config (port-loop Phase 0), `--git-signals` (C1), `--community-signals` (issue/forum exhaust) | Adds rows to `intention_signals.parquet` / `features.parquet` with a `lane` tag; a per-run `lanes_enabled` manifest field | Core still valid; coverage notes mark the thinner harvest |
| **Target profile** | The re-implementation target's consistency + trust model (local-first event log, selective disclosure) | Read *only* by the brief renderer to emit the **target-adaptation section**, conditioned on §6.2 CM grades | System stands alone; CM grades still emitted (they describe the source), no adaptation section rendered |
| **Port Decisions log** | ADR-style record of every conscious divergence ("shift the implementation, even shift the design intent"), naming the source intention it supersedes and why (port-loop machinery #2) | New rows referencing the superseded document element by id; the port-verifier treats waived elements as expected deltas, not failures | Empty at decomposition time; populated during porting |

**The attachment rule, stated once:** instance parts may only **add rows, tags, or rendered
sections keyed by foreign key into the mandatory artifacts** — they may never rename a mandatory
field, gate a mandatory document, or feed back into the structural math. A decomposition with zero
instance parts (no declarative lane, no target profile, no port decisions) is a *complete, valid*
decomposition; instance parts strictly enrich. This is the same one-way-dependence discipline the
intention layer already obeys (intention doc §3: enrichment is *over* the schema, never redefines it).

A dedicated **`port_decisions.jsonl`** (new, instance-scoped, additive) holds the log:

```jsonc
{
  "decision_id": "...", "made_at": "...",
  "supersedes": {"document": "invariant | scenario | data_shape | interface | feature",
                 "ref": "..."},          // the mandatory-core element this diverges from
  "divergence": "...",                    // what the port does instead
  "rationale": "...",                     // why — the ADR body
  "verifier_waiver": true,                // port-verifier treats the delta as expected, not failure
  "target_profile_ref": "..."             // which target assumption drove it, or null
}
```

Distinguishing **disciplined divergence** (logged, waived, auditable) from **drift** (silent) is the
whole point (port-loop machinery #2).

---

## 10. The rendering rule — cards and briefs are views, never sources

**Cards (`subsystem_cards.jsonl`) and port briefs (`port_briefs/<subsystem>.md`) are RENDERINGS over
the seven-document set. They are never the source of truth for anything.** Concretely:

- Every field in a card and every block in a brief **traces to a backing artifact row** (the seven
  documents' artifacts: `features`, `intention_signals` + glossary, `data_shapes`, behavioral
  scenarios, `invariants`, `subsystems`/`interfaces`/`operads`, conflicts/`intention_load`). A card
  is a join; a brief is a join rendered for a reader.
- Cards and briefs are **derived and regenerable** — hand-editing either is a defect. Regenerating
  from identical backing rows + identical `prompt_version` reproduces byte-identical output (the T5
  acceptance criterion, subsystem doc §9; extended to the brief, intention doc §8).
- Determinism / digest / provenance are **inherited wholesale from
  [`ctkr-l3-artifacts.md`](./ctkr-l3-artifacts.md)**, not re-invented:
  - the four mandatory provenance fields (`llm_model`, `llm_temperature`, `prompt_version`,
    `schema_version`) on every synthesized row — no exceptions;
  - `card_id` / brief digest = blake3 over the backing digests + `prompt_version` + `llm_model`, so
    unchanged inputs mean a free re-run and any harvest change invalidates *precisely* the affected
    renderings;
  - re-runs are **additive** — a new `prompt_version` emits a new rendering that coexists with the
    old for reviewer comparison, never an in-place overwrite.

The mechanical Parquet artifacts (`features`, `data_shapes`, `invariants`, `subsystems`,
`interfaces`, `operads`) obey `ctkr-artifacts.md`: maximal-precision, `schema_version` per row,
pydantic-canonical in `ctkr/schema.py`, deterministic byte-identical re-runs. **The synthesized
JSONL is where LM judgment lives and where provenance is non-negotiable; the Parquet is where the
mechanical ground truth lives.** No document in the set is authored — every one is *produced*.

---

## 11. Worked instantiation — farmOS

How the seven mandatory documents fill from farmOS (Drupal/PHP → local-first), and what is
instance-flexible. This is the concrete test of the schema: if the seven fall out cleanly from a
real target, the contract holds.

| Document | Filled primarily from (farmOS) | Tier / notes |
|---|---|---|
| **D1 Feature Inventory** | `.info.yml` module manifests (**module ≈ feature**), routing YAML, permissions YAML → the feature list *and* its dependency graph, read declaratively (port-loop Phase 0). `source_basis: "declarative"`. | Tier S — machine-enforced; strongest possible feature harvest. `farm_harvest`, `farm_quantity`, `farm_land`… each a feature. |
| **D2 Domain Glossary** | Entity/field **annotations** + config-entity YAML (the domain's controlled vocabulary: asset, log, quantity, term, plan), A4/A3 harvest, farmOS.org/model prose as B2. | Mostly intent-I; Drupal-idiom terms (`bundle`, `entity_reference`) are intent-N, restated. |
| **D3 Data Shapes** | Drupal **field/entity annotations** (Tier S — declarative field definitions), not PHP inference. Boundary shapes = the **JSON:API** contract (farmOS.py/js/Aggregator are independent instances of it). | Boundary = JSON:API resources (must reproduce semantically); Drupal storage tables = internal, port restructures to event log. |
| **D4 Behavioral Scenarios** | farmOS test suite (S1) + observed behavior on a live instance (port-loop Phase 2), in glossary terms: "record harvest log qty X against asset A → A's yield reflects X". Storage-free by rule (§5). | intent-I. Seeds the Phase 2 semantic fixture pack. |
| **D5 Invariant Register** | Field annotations (uniqueness, required, referential) → structural invariants; **update hooks** encode migration/compat invariants; permission checks → access invariants; Drupal's ACID/unique/autoincrement assumptions → **CM-hard** grades. | The high-value document: every central-authority assumption gets a CM grade the local-first port must re-answer (convergence / coordination / weaken). |
| **D6 Seam Map** | Module boundaries + `hook_*` plugin seams + JSON:API resource boundaries as interface contracts; scip-php structural lane for the PHP call algebra. | JSON:API boundary = tier-I interface contract (external instances observe it). |
| **D7 Warnings/Conflicts** | scip-php is weakest exactly where Drupal is dynamic (hooks, plugins, magic `__get`) → intention-critical / ambiguous flags there; `@deprecated`, `TODO`/`HACK` in modules → declared debt. | The declarative lane covers the structural blind spots (port-loop Phase 0 rationale). |

**Instance-flexible for farmOS:** harvest lanes = declarative-config **on** (the whole point),
git **off** (`--git-signals` deferred), community **off** (deferred); target profile = local-first
event log + sync + selective disclosure (drives the target-adaptation section against CM-hard
invariants); Port Decisions log = populated during the Phase 4 logs+quantities vertical slice.

**The N=2 gift** (port-loop "why farmOS"): farmOS 1.x→2.x was a ground-up rewrite of the same
product, mapping written in `farm_migrate`. Diffing the two decompositions' Invariant Registers and
Feature Inventories separates intent-I (survived) from idiom (didn't) *empirically* — the one corpus
that lets the schema's judgment tags be corrected by data rather than asserted (§0 claim, subsystem
doc §1.2c).

---

## 12. Honest limits & open decisions

**Limits:**

- **The document set is a contract, not a guarantee of truth.** Each document inherits its lane's
  honesty gauge: Feature Inventory is only as good as the declarative manifest (structural-fallback
  features are proposals); Behavioral Scenarios are only as good as the original tests (intention doc
  §10); the Invariant Register can *miss* an invariant no artifact encodes (an unwritten rule enforced
  only by convention). Coverage notes mark thin spots; nothing here manufactures completeness.
- **The two new artifacts are the two riskiest.** `features.parquet` and `invariants.parquet` are
  the documents *without* an existing producer — they carry the most new extraction logic and the
  least prior calibration. Ship them behind the same dial-and-driver discipline as `D`/`R` (intention
  doc §5.3): emit the drivers, keep the thresholds dials, correct on the first real port.
- **CM grading assumes we can see the central-authority assumption.** Mechanical seeding catches
  autoincrement / unique-constraint / transaction / access-check patterns in the declarative lane;
  assumptions buried in imperative PHP without a declarative footprint are LM-adjudication-or-miss.
- **N=1 applies to every judgment tag** (portability, CM, feature-basis). farmOS's N=2 (§11) is the
  mitigation; absent a second instance the tags are honest guesses, marked as such.
- **This doc adds no new signal source.** It is a discipline over the existing lanes. If a future
  reader cites it to justify a name-based partition or a parallel non-derived card: no. Structure
  stays name-blind (intention doc §0); cards stay derived (§10).

**Open decisions (flagged, not relitigating anything upstream):**

- **(a) Corpus glossary artifact** — standalone derived `glossary.jsonl` vs. leaving glossary
  per-card only (§3). *Recommend* the thin corpus index (dedupes cross-subsystem terms; still a
  view, not a source).
- **(b) `features.parquet` producer ownership** — Python (alongside the declarative lane and Louvain
  partition) vs. TS. *Recommend* Python: it co-locates with the Phase 0 YAML/annotation walker and
  the subsystem partition it joins against.
- **(c) `invariants.parquet` — one flat register vs. per-kind sub-registers** (ordering / structural
  / value / access as separate files). *Recommend* one flat register with a `kind` column (matches
  the single-`Symbol`-table-with-`kind` precedent in `schema.md`); split only if a consumer needs it.
- **(d) `consistency_sensitivity` as a separate axis vs. folded into `portability_tier`** (§6.1).
  *Recommend* separate axes as designed — folding loses the intent-I-but-CM-hard case, which is the
  whole point of the local-first port. Flagged because the bead's phrasing ("intent-I/N/A/CM") could
  be read either way; this is the deliberate divergence and its rationale.
- **(e) Feature↔subsystem partition disagreement** (§2.1) — surface as a first-class finding in D7
  Warnings, or as a separate report? *Recommend* D7, alongside the structure↔declared-module
  disagreement it parallels.
- **(f) Port Decisions log location** — `port_decisions.jsonl` sibling of the cards vs. inside the
  brief. *Recommend* the sibling JSONL (git-diffable, additive, survives brief regeneration; the
  brief renders a view of it).
