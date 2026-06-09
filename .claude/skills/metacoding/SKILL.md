---
name: metacoding
description: >-
  Query a codebase's structure through the MetaCoding MCP server — typed
  graph navigation (callers, implementers, neighbors), full-text search over
  the AST blind spots, live LSP info, and the CTKR categorical-knowledge tools
  (motifs, structural embeddings, cross-repo "same role" equivalence, repo
  topology). Use when the user wants to explore how code is connected, find
  who calls/implements a symbol, locate string/DI/reflection usages, or ask
  cross-repo structural questions — instead of grepping blindly. Triggers:
  "who calls", "what implements", "graph", "callers", "same role",
  "role-equivalent", "metacoding", "ctkr", "across repos", "structural".
---

# Using the MetaCoding MCP

MetaCoding indexes a codebase into a typed graph + FTS sidecar + (optionally)
the CTKR cross-repo artifacts, and serves them read-only over MCP (server name
`metacoding`, stdio). This skill is the decision layer: which tool to reach for,
in what order, and the gotchas that make a tool return nothing.

**Read-only.** Nothing here mutates code or the graph. Tool outputs return
symbol envelopes (`{id, qualified_name, file, line, kind}`) — fetch source with
`Read` when you need bodies.

## Step 0 — discover, don't assume

Call **`describe_api`** first if you're unsure what's available. It returns the
live tool list with exact input schemas, plus the valid `edge_kinds` /
`token_kinds`. The surface evolves; `describe_api` is authoritative (a drift
guard keeps it in sync with the live registrations).

If the `metacoding` MCP tools aren't connected, the server is launched as
`metacoding serve --data-dir <repo>/.metacoding` (see repo README for the
`mcpServers` entry). The `ctkr.*` tools additionally need
`METACODING_CTKR_DATA_DIR` set in the server's environment — see CTKR gotchas
below.

## Tool-selection guide

| You want… | Use | Notes |
|---|---|---|
| What a symbol touches / what touches it | `graph_neighbors` | `direction` in/out/both, filter `edge_kinds`. The workhorse. |
| Who calls/references a symbol | `graph_callers` | **Needs a SCIP pass** — empty on Tree-sitter-only indexes. |
| What implements/extends an interface/class | `graph_implementers` | The interface-consumer query. |
| String literals, DI keys, reflection, route paths, comments | `code_search` | FTS5 syntax (phrase, prefix `x*`, `NEAR`). Catches AST blind spots. |
| What changed between two indexed commits | `graph_diff` | **Needs both snapshots present** — index with `--per-commit-identity`. |
| A query no typed tool covers | `graph_cypher` | Escape hatch. Prefer typed tools; promote common patterns. |
| Live type/sig/docs at a cursor | `lsp_hover` | Reflects unsaved edits. Positions are **0-indexed**. |
| Live go-to-def / find-refs | `lsp_definition` / `lsp_references` | Use refs when `graph_callers` may be stale post-edit. |
| Current type errors / lints | `lsp_diagnostics` | Poll after edits; `wait_ms` default 3000. |

### CTKR — cross-repo categorical knowledge

| You want… | Use |
|---|---|
| Recurring typed subgraphs (structural motifs) across the corpus | `ctkr.motif_search` |
| k nearest symbols by **learned** structural embedding | `ctkr.nearest_symbols` |
| k symbols playing the **same structural role** (raw typed-edge shape) | `ctkr.role_equivalent` |
| L3-labeled patterns + evidence (motifs, role-clusters, analogies) | `ctkr.pattern_search` |
| Topological distance between whole repos | `ctkr.shape_distance` |
| Per-symbol centrality + spectral clusters | `ctkr.centrality_query` |

**`nearest_symbols` vs `role_equivalent`** — both are cosine-KNN over a symbol,
but they answer different questions:
- `nearest_symbols` uses **learned** embeddings (DeepWalk/GraphSAGE) — "things
  that sit in a similar position in the learned space."
- `role_equivalent` uses the **raw hom-profile** — the integer count of each
  typed edge by direction, at maximal precision. It's the categorically-honest
  "same role" predicate: matches turn purely on the shape of a symbol's
  typed-edge neighbourhood, independent of name or a repo's naming conventions.
  Pass `cross_repo_only: true` for the cross-repo role-equivalence query
  (Phase 2a), and `scope: "<repo>"` to disambiguate a `qualified_name` that
  appears in several repos.

## Composition patterns

Compose small tools; don't ask for a bespoke endpoint.

- **"Controllers that call services touching the orders table"** →
  `code_search` the table/string → `graph_callers` up to the services →
  `graph_neighbors`/`graph_callers` up to the controllers.
- **"Is there a class like this one elsewhere?"** →
  `ctkr.role_equivalent` with `cross_repo_only: true` on the seed symbol →
  `Read` the top matches' files to confirm.
- **"What pattern is this an instance of?"** →
  `ctkr.pattern_search` with `instances_in_repo: "<repo>"` → inspect evidence.

## Gotchas

- **`graph_callers` empty?** The repo was indexed without SCIP — Tree-sitter
  alone can't resolve cross-file references. Re-index with `--scip` or fall
  back to `lsp_references`.
- **`graph_diff` returns nothing for the older sha?** Only the latest snapshot
  exists unless the repo was indexed with `--per-commit-identity`.
- **`ctkr.*` errors with a data-dir message?** Those tools resolve their data
  from `METACODING_CTKR_DATA_DIR` (the path to a `.metacoding/` that has a
  populated `ctkr/` dir) — there is **no implicit corpus fallback**. The
  `serve --data-dir` flag wires the graph/LSP tools, not the CTKR artifacts.
- **`ctkr.shape_distance` returns -1?** That repo pair is absent from the
  artifact (one repo likely lacks a `shape_pds` entry) — not an error.
- **LSP positions are 0-indexed** (line and col).
- **Symbol refs accept id _or_ qualified_name** for `graph_*`; a 16-char hash
  is an id. CTKR seed tools take `symbol_id` or `qualified_name`.

## Reference

- Surface + input shapes: `docs/design/mcp-surface.md`
- CTKR artifacts on disk: `docs/design/ctkr-artifacts.md`
- CTKR vision / the four-phase ladder: `docs/design/ctkr.md`
- Granularity-as-a-dial (why hom-profiles stay raw): `docs/notes/entropy-as-dial.md`
