# MCP surface

Small, typed, opinionated. Specific tools the agent will actually call rather than a Cypher passthrough that requires the agent to author graph queries.

## Core graph tools

### `graph_neighbors`
```
input:  symbol (id or qualified_name), direction (in|out|both), kind? (filter), depth=1
output: list of Symbol with edge metadata
```
The workhorse. "What does this touch / what touches this."

### `graph_implementers`
```
input:  interface_or_class (id or qualified_name), include_subtypes=true
output: list of Symbol implementing or extending it
```
The interface-consumer trick from the 2026 paper, first-class. "Which classes implement `IOrderService`?"

### `graph_callers`
```
input:  symbol, depth=1, include_overrides=true
output: list of Symbol that call (transitively if depth>1) this one
```
"Who depends on this function?" Common upstream-discovery query.

### `graph_callees`
```
input:  symbol, depth=1
output: list of Symbol called from this one
```
"What does this function depend on?"

### `graph_path`
```
input:  from_symbol, to_symbol, max_hops=5, edge_kinds? (filter)
output: paths as ordered Symbol lists with edge labels
```
"How does this controller reach the database?"

### `graph_cypher`
```
input:  cypher_query, params
output: rows
```
Escape hatch. Don't lean on it; if a query type is common, promote it to a typed tool.

## Text / FTS tools

### `code_search`
```
input:  query, kind? (literal|identifier|comment|annotation_arg|config_value), languages?, limit=50
output: list of {file, line, col, kind, snippet, symbol_id?}
```
The string-blind-spot lane. "Find every place 'orderService' appears as a literal."

### `code_search_regex`
```
input:  pattern, kind? filter
output: same shape as code_search
```
For when FTS isn't enough. Backed by ripgrep against the indexed file set, not full FTS.

## LSP-only tools (live information)

### `symbol_hover`
```
input:  file, line, col
output: hover markdown (signatures, docs, types)
```
Reads the live LSP. Useful for "what is this?" without parsing.

### `symbol_diagnostics`
```
input:  file? (or whole project)
output: list of diagnostics with severity, message, range
```
Current type errors and lints. The agent should poll this after edits.

### `symbol_signature`
```
input:  file, line, col
output: signature info, parameters, current parameter index
```

## Optional / out-of-band

### `graph_taint`
```
input:  source_symbol, sink_symbol, max_hops=10
output: list of flow paths (Symbol sequences with line numbers)
```
Spawns Joern, runs `reachableByFlows`, returns paths. Slow (10s–minutes). Use sparingly.

## Tools we deliberately do NOT expose

- `vector_search` — see [architecture.md](architecture.md). Defer until proven needed.
- `extract_with_llm` — out of scope. The graph is deterministic.
- Generic `db_query` — let the agent compose typed tools instead of writing SQL/Cypher.
- Anything write-side — this is read-only by design. If we want refactoring tools later (rename, extract), they go through the LSP's `workspace/applyEdit`, not raw graph mutations.

## Design notes

- **Keep the surface small.** The temptation will be 20 tools. The agent will reliably use 5. Ship the small set, watch which the agent reaches for, promote common patterns from `graph_cypher` to typed tools.
- **Return symbol IDs, not full content.** Let the agent fetch source via `Read` if needed. Tool outputs should fit comfortably in context.
- **Compose, don't bloat.** "Find all controllers that call services that touch the orders table" should be the agent composing `graph_callers` + `code_search` + `graph_neighbors`, not a single `find_orders_controllers` tool.
- **Predictable shapes.** Every result that references a symbol returns the same `{id, qualified_name, file, line, kind}` envelope.
