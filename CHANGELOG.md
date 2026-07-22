# Changelog

## 0.2.0 (2026-07-22)

Six weeks of work: PHP support across the whole pipeline, a large expansion of the CTKR
categorical-knowledge toolset (subsystems, roles, operads, functor search, port
verification), a value-equivalence oracle for cross-framework porting, and index/serve
reliability fixes.

### Language support
- PHP tree-sitter extraction lane: symbols, containment, tokens (MetaCoding-8sh)
- High-fidelity PHP SCIP lane via `scip-php`, plus CLI support for pre-built PHP SCIP
  indexes (`--load-scip`)
- PHP LSP (language server) support
- PHP inheritance edges (`EXTENDS`/`IMPLEMENTS`/`USES_TRAIT`) and a tree-sitter
  field-access heuristic lane with edge provenance
- Drupal-aware extraction: declarative-config intention lane, Drupal PHP file
  extension detection (`.module`/`.install`/`.theme`/`.profile`/`.engine`)

### CTKR (categorical structural analysis)
- New pipeline stages: subsystem partitioning (Stage A), boundary-morphism/interface
  extraction (Stage B), role inventory (Stage C), operad recovery (Stage C), spec-deck
  NL rendering (Stage D/E) — each with an MCP tool
- Functor discovery: search, eval harness, artifact emission (`functors.parquet`),
  hom-profiles (opt-in 2-hop WL-refinement, per-edge-kind weighting), and the
  `functor_between` MCP tool
- Port-verifier: functor-as-acceptance-test with §6.2 normalization
- Glossary tooling: `propose-terms`, `glossary-gaps` vocabulary diff, glossary binding
  gate with spec-driven term codegen, term-incidence graph, role-gaps sweep
- Lexicon-bind: multiple wave-1/wave-2 term bindings across log-family features
  (birth_mother, lot_number, delete_quantity, material_quantity, equipment_used, and
  others)
- CTKR Observatory: live visualization of islands, entropy, twins, and the port
  bipartite graph
- Entropy/marginal-entropy harness with `--kind-weight` support

### Port-loop / value-equivalence oracle
- Value-equivalence oracle: glossary, fixtures, farmOS driver, recorder, runner, CLI
- Intention harvest (mechanical + LLM-assisted), calibration pipeline
  (`calibration.parquet`, ingest CLI, dial sweep), target-conditioned port briefs
- Kernel evolution v1 → v1.3: frozen shared-decision elements, fold library
  (`FoldReduce`, `GSet`, `GuardedFirstWrite`), status split, staleness pin
- Trust model refactor: authority / no-pen / no-answer; epistemology charter replacing
  the "courtroom" model with dialectic
- `metacoding doctor`: reports active lanes and tooling gaps

### Index / serve reliability
- Read-only opens now coexist with a running index (epic MetaCoding-gh0)
- `serve` reopens on refresh — picks up a reindex without restart
- Index-state observability: distinguish "not indexed" from "no results"
- `serve` exits on client disconnect so the LSP child can't orphan
- Watch-mode resolver hydration scoped to needed names (perf)
- `--per-commit-identity` re-reads HEAD per watch event

### Fixes
- SCIP no longer clobbers tree-sitter structural fields on field-level merge
- Namespace-qualified `CONSTRUCTS` edges + denylist
- `ANNOTATES` emission for imported/unresolved decorators; new `RAISES` edge kind
- `CALLS` edges now derived from callable `REFERENCES` in the PHP SCIP lane
- Declared `scipy` as a runtime dependency (networkx pagerank/eigenvector requires it)
- `DataFieldCard.type` populated for scalar fields; worktree path normalization

## 0.1.4 (2026-06-09)

Previous release.
