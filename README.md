# MetaCoding

A local-first **code-graph database** built for AI coding agents.

Walk a codebase, build a typed graph of symbols and their relationships,
expose it over MCP. Replaces — or complements — vector RAG for the kind
of multi-hop architectural reasoning that agents actually need:
"who calls this?", "what implements `IFoo`?", "trace this controller to
the database."

## The wedge

Most code-RAG tools chunk source files into 1000-character windows and
toss them at a vector index. That works for "find code that mentions
rate limiting." It falls over the moment the agent needs to follow
edges the type system already knows about — interface implementers,
call graphs, dependency injection — because those edges are *invisible
to text*.

MetaCoding's bet is that the graph deserves first-class storage. Five
complementary lanes feed one embedded graph store:

| Lane | Purpose |
|---|---|
| **SCIP** | resolved symbol graph for committed code (TS / Python / Java / Go) |
| **LSP** | live overlay for dirty buffers and SCIP-missing languages |
| **Tree-sitter** | universal fallback; configs; pattern queries; bootstrap |
| **SQLite FTS5** | string DI, reflection, ORM table names, route literals — the AST blind spots |
| **Joern** (opt-in) | interprocedural dataflow / taint, on demand |

All five write into a single [ladybugdb](https://github.com/ladybugdb/ladybugdb)
graph (the maintained Kùzu fork) plus a SQLite FTS5 sidecar. One process,
two files on disk, no servers.

The graph is exposed over **MCP** as a small typed surface
(`graph_neighbors`, `graph_implementers`, `graph_callers`, `graph_path`,
`code_search`, plus live `symbol_hover` / `symbol_diagnostics`). The
agent composes — it doesn't author Cypher.

## Status

Phases 1–4 of the build plan are wired and exercised by a smoke
gauntlet:

- Tree-sitter extractor (TS + Python), SCIP loader (TS + Python), LSP
  overlay (multilspy-style), FTS5 sidecar with a code-aware splitter.
- ladybugdb store with a single swap-boundary and the Bun finalizer
  mitigation lifted from Dreamball's spike (see
  [storage-integration.md](docs/design/storage-integration.md)).
- MCP server (stdio transport) with seven graph tools and three live
  LSP tools.
- Incremental re-indexing keyed on AST hash; file watcher; branch
  auto-detect.
- `metacoding export` dumps the graph to JSONL for downstream analysis.

## CTKR — the research overlay

A second sub-project, [`ctkr/`](ctkr/), layers a structure-mining
pipeline on top of the same graph: motif mining, embeddings,
persistent-homology shape signatures, centrality, and an LLM-bridged
labeler that turns recurring graph patterns into named architectural
roles — without the user having to declare an ontology up front.

Think of MetaCoding as the **substrate** and CTKR as the
**telescope** pointed at it. CTKR is in active development; see
[`docs/design/ctkr.md`](docs/design/ctkr.md) for the vision and
[`docs/design/ctkr-artifacts.md`](docs/design/ctkr-artifacts.md) for
the concrete Layer-1 artifacts it produces.

## Quick start

```bash
bun install

# Index a codebase
bun run src/cli/main.ts index <path> --data-dir <path>/.metacoding

# Watch for changes (incremental re-index)
bun run src/cli/main.ts watch <path>

# Serve over MCP (stdio) — point Claude Code at this
bun run src/cli/main.ts serve --data-dir <path>/.metacoding

# Ad-hoc Cypher (escape hatch — prefer the typed MCP tools)
bun run src/cli/main.ts query 'MATCH (n:Symbol) RETURN count(n)'

# Dump the graph to JSONL for ctkr / external analysis
bun run src/cli/main.ts export <out-dir> --data-dir <path>/.metacoding
```

A single shipped smoke command runs every lane end-to-end against a
test fixture:

```bash
bun run smoke
```

## Design principles

- **Deterministic before probabilistic.** AST / SCIP / LSP first; LLM
  extraction only when the type system has run out of signal. The 2026
  paper that motivated this (see
  [docs/research/paper-2601.08773v1.md](docs/research/paper-2601.08773v1.md))
  found probabilistic extraction was dominated 2× to 45× on cost,
  latency, and recall. Don't add probabilistic back gratuitously.
- **Local-first, embedded.** No servers, no cloud, no Docker. One
  process, one on-disk DB. Everything Claude Code does, this does too:
  walk in, read the project, work locally.
- **Typed MCP surface.** Specific tools the agent will reach for
  (`graph_implementers`, `graph_callers`) over raw Cypher passthrough.
  Compose, don't bloat.
- **Layered fidelity.** Tree-sitter ships immediately at low fidelity;
  SCIP and LSP upgrade specific languages without reshaping the API.
- **Defer what isn't load-bearing.** No embeddings v0. No taint v0.
  Add a lane only when a class of queries fails through the existing
  ones.

## Layout

```
metacoding/
├── src/                          TypeScript / Bun — the indexer + MCP server
│   ├── extractor/                Tree-sitter walkers (TS, Python)
│   ├── scip/                     SCIP loader + runner
│   ├── lsp/                      Live LSP overlay
│   ├── store/                    ladybugdb + FTS5 single swap-boundary
│   ├── mcp/                      MCP server + tool handlers
│   └── cli/                      `metacoding` CLI entry points
├── ctkr/                         Python — the structure-mining overlay
├── docs/
│   ├── design/                   architecture, schema, MCP surface, build plan
│   └── research/                 paper notes, prior art
└── scripts/                      Smoke tests, peek-scip helpers
```

Design docs are the prose source of truth:

- [docs/design/architecture.md](docs/design/architecture.md) — the
  five-lane stack and why each lane earns its slot.
- [docs/design/schema.md](docs/design/schema.md) — graph node / edge
  schema (Joern CPG flattened) and the FTS table.
- [docs/design/mcp-surface.md](docs/design/mcp-surface.md) — concrete
  MCP tools.
- [docs/design/storage-integration.md](docs/design/storage-integration.md)
  — ladybugdb + FTS5 lifecycle, Bun finalizer mitigation, format
  compatibility notes.
- [docs/design/build-plan.md](docs/design/build-plan.md) — MVP order
  of operations and what each phase ships.
- [docs/design/ctkr.md](docs/design/ctkr.md) — the categorical
  knowledge-representation track.

## Stack

| Component | Choice |
|---|---|
| Runtime | Bun |
| Graph DB | ladybugdb (embedded Cypher; Kùzu fork) |
| Text index | SQLite FTS5 (trigram + code-aware splitter) |
| Parsers | Tree-sitter (every language) |
| Symbol resolution | SCIP indexers for HEAD; LSP for dirty / extra languages |
| Optional dataflow | Joern, out-of-band |
| Transport | MCP stdio |

## License

MIT — see [LICENSE](LICENSE).
