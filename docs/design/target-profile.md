# The Target Profile — an optional consistency contract for the port

Port-loop [Phase 3](./port-loop-plan.md) and the Invariant Register
([decomposition-schema.md §6.2](./decomposition-schema.md)) give every central-authority
assumption in the source an **intent-CM (consistency-model-sensitivity)** grade — mechanically
seeded, LM-adjudicated. Those grades describe the **source** and stand on their own. A *target
profile* is the **optional** other half: a small document that says what the re-implementation
target's consistency model *is*, so a port brief can render a **Target adaptation notes** section
saying how the target must re-answer each CM-graded assumption.

> **The optionality is load-bearing.** The whole intent-CM pipeline — the mechanical seed
> (`intent_cm.parquet`) and the LM adjudication (`intent_cm_adjudicated.jsonl`) — runs and is
> complete **with no target profile**. The profile conditions **only** the brief's
> target-adaptation section, never the harvest, never the intent, never the CM grade itself. A
> decomposition with no profile still emits CM grades; a port that keeps the source's central
> authority simply ignores the adaptation section. This mirrors the Phase 3 mandate: *the system
> must stand alone without a profile.*

## What a profile is

A `target_profile` is a YAML (or the `target_profile:` block of a larger YAML) with these fields:

```yaml
target_profile:
  id: farmos-local-first              # stable slug, used in brief headers + Port Decisions
  name: farmOS local-first port       # human name
  consistency_model: eventual         # eventual | causal | strong (the target's baseline)
  architecture:                       # the shape the port is built on
    - event-log
    - materialized-views
  sync: selective-disclosure          # one line: how replicas exchange state
  summary: >                          # a paragraph the brief can quote verbatim
    Offline-first single-tenant replicas. State is an append-only event log;
    reads are materialized views projected from it. Replicas sync by exchanging
    events with selective disclosure (a replica shares only what it chooses).
  capabilities:                       # what the target CAN do — informs the decision menu
    convergence_rules: [crdt, lww]    # available convergence primitives
    coordination_layer: false         # is there an authority a hard invariant can escalate to?
    disclosure_layer: true            # is there a sync/disclosure layer to move access into?
  decision_menu:                      # sensitivity class → ordered options the port must choose from
    hard:
      - preserve-via-convergence-rule
      - move-to-coordination-layer
      - weaken-to-eventual
    soft:
      - preserve-as-eventual-invariant
      - move-to-disclosure-layer
    none:
      - port-verbatim
```

Only `id` is strictly required; every other field has a sensible default (`decision_menu` defaults
to the Phase 3 menu — *preserve-via-convergence-rule / weaken-to-eventual / move-to-disclosure-layer*).
A profile with just an `id` still produces a labeled adaptation section using the defaults.

## How it conditions the brief

For each intent-CM-tagged element with an adjudicated sensitivity of **hard** or **soft**, the
Target adaptation notes section renders three things, **clearly labeled as target-conditioned
judgment and never mixed into source-derived INTENT**:

1. **Source assumption** — what central-authority behavior the source leans on (from the CM
   category: transaction / unique-constraint / autoincrement-id / access-check / revision-lock).
2. **Sensitivity** — the adjudicated class (`hard` = cannot hold under eventual consistency without
   a chosen strategy; `soft` = holds eventually, transient violation tolerable).
3. **Decision menu** — the profile's ordered options for that class. Choosing one is a **Port
   Decision** (port-loop cross-cutting machinery #2); the port-verifier then treats the choice as an
   expected delta, not a failure.

A different target profile re-renders the same CM grades into a different adaptation section — the
grades are the invariant, the profile is the lens.

## CM is a separate axis from portability (do not fold them)

Per [decomposition-schema.md §6.1](./decomposition-schema.md) (open decision (d), resolved:
*separate*): an invariant can be **intent-I** (survives any stack verbatim) *and* **CM-hard**
(assumes central authority). Folding CM into the I/N/A portability enum would lose exactly the case
that matters most — a universal domain rule a distributed target must re-answer. The target profile
reads the CM axis; it never touches the portability axis.

## Producing the grades (recap)

```bash
# 1. mechanical seed (deterministic, no LLM) → intent_cm.parquet
ctkr intent-cm --source-root /path/to/source --data-dir .metacoding

# 2. + strong-model adjudication over the flagged (CM-hard/CM-soft) subset
ctkr intent-cm --source-root /path/to/source --data-dir .metacoding --adjudicate

# 3. preview the target-conditioned adaptation notes (optional profile)
ctkr intent-cm --source-root /path/to/source --data-dir .metacoding --adjudicate \
  --target-profile docs/design/target-profiles/farmos-local-first.yaml
```

The worked example — the actual farmOS local-first port profile — is
[`target-profiles/farmos-local-first.yaml`](./target-profiles/farmos-local-first.yaml).
