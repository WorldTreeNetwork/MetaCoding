# Schema

Graph in ladybugdb (Cypher), text index in SQLite FTS5. Schemas are sketches, not final.

## Graph nodes

Single polymorphic `Symbol` label with a `kind` property (avoids per-language label explosion).

```cypher
CREATE NODE TABLE Symbol (
  id            STRING PRIMARY KEY,    -- stable hash: language + qualified_name + signature
  kind          STRING,                -- file | module | class | interface | enum
                                       -- function | method | field | parameter
                                       -- annotation | type_alias | namespace
  language      STRING,                -- ts | py | java | go | rust | ...
  qualified_name STRING,               -- e.g. com.shopizer.OrderService.findById
  short_name    STRING,                -- findById
  file          STRING,                -- relative to repo root
  line          INT,
  col           INT,
  end_line      INT,
  end_col       INT,
  signature     STRING,                -- function/method signature if applicable
  visibility    STRING,                -- public | private | protected | internal
  is_abstract   BOOLEAN,
  is_static     BOOLEAN,
  ast_hash      STRING,                -- for incremental re-indexing (source-atlas trick)
  branch        STRING,                -- for branch-aware multi-tenancy
  source        STRING                 -- scip | lsp | tree_sitter | joern
);
```

The `source` property records which lane produced the node so we can prefer high-fidelity sources when lanes disagree.

## Graph edges

```cypher
CREATE REL TABLE CALLS         FROM Symbol TO Symbol (count INT);   -- aggregated per caller-callee
CREATE REL TABLE REFERENCES    FROM Symbol TO Symbol (count INT);   -- non-call refs
CREATE REL TABLE EXTENDS       FROM Symbol TO Symbol;
CREATE REL TABLE IMPLEMENTS    FROM Symbol TO Symbol;
CREATE REL TABLE OVERRIDES     FROM Symbol TO Symbol;
CREATE REL TABLE INJECTS       FROM Symbol TO Symbol;               -- DI: constructor params, @Inject fields
CREATE REL TABLE CONTAINS      FROM Symbol TO Symbol;               -- file→class, class→method, etc.
CREATE REL TABLE IMPORTS       FROM Symbol TO Symbol;               -- file/module → file/module
CREATE REL TABLE ANNOTATES     FROM Symbol TO Symbol;               -- annotation → annotated symbol
CREATE REL TABLE TYPE_OF       FROM Symbol TO Symbol;               -- field/param → declared type

-- Behavior-capturing edges (bead MetaCoding-e54).
-- Purpose: raise the typed-edge Shannon entropy above the 4.0-bit Phase 2a
-- threshold by discriminating accessor patterns that collapse under REFERENCES.
CREATE REL TABLE READS_FIELD   FROM Symbol TO Symbol;               -- method/function reads a field
CREATE REL TABLE WRITES_FIELD  FROM Symbol TO Symbol;               -- method/function writes a field
CREATE REL TABLE RETURNS_TYPE  FROM Symbol TO Symbol;               -- function/method → its return type symbol
CREATE REL TABLE CONSTRUCTS    FROM Symbol TO Symbol;               -- function/method instantiates a class
```

**Behavior-capturing edge semantics (MetaCoding-e54).**

| Edge | Source | Target | Extracted from |
|------|--------|--------|---------------|
| `READS_FIELD` | method / function | field | SCIP `ReadAccess` occurrence role |
| `WRITES_FIELD` | method / function | field | SCIP `WriteAccess` occurrence role |
| `RETURNS_TYPE` | method / function | type symbol | SCIP `is_type_definition` relationship on a callable |
| `CONSTRUCTS` | method / function | class / constructor | SCIP occurrence targeting a constructor method (`constructor(+).`) or class type descriptor, without read/write roles |

`READS_FIELD` and `WRITES_FIELD` replace the less discriminating `REFERENCES` edge for field-access occurrences.  Plain occurrences on fields (no role flags) still emit `REFERENCES` for backward compatibility.

`RETURNS_TYPE` is emitted instead of `TYPE_OF` when the source symbol is a function or method.  `TYPE_OF` is reserved for field/parameter → declared-type relationships.

`CONSTRUCTS` is emitted when an occurrence targets a constructor symbol (`constructor(+).` pattern in scip-typescript, `__init__().` in scip-python) or a bare class type symbol referenced without read/write roles.

**Why aggregated CALLS counts and not per-callsite edges.** A `Logger` class can have 5,000 call sites; you don't want each as an edge. Aggregate per caller-symbol with a count and store callsite locations in a side table queryable by `(caller_id, callee_id)`.

```cypher
CREATE NODE TABLE Callsite (
  id        STRING PRIMARY KEY,
  caller_id STRING,
  callee_id STRING,
  file      STRING,
  line      INT,
  col       INT
);
```

## FTS schema (SQLite)

```sql
CREATE VIRTUAL TABLE tokens USING fts5(
  text,                  -- the token or string content
  kind UNINDEXED,        -- literal | identifier | comment | annotation_arg | config_value
  file UNINDEXED,
  line UNINDEXED,
  col UNINDEXED,
  symbol_id UNINDEXED,   -- nullable: link back to graph node when known
  tokenize='trigram'
);
```

Code-aware splitter applied at write time: `OrderService` → emit `OrderService`, `Order`, `Service`, `order`, `service`. So `service` and `order_service` and `OrderService` all hit.

**Tokens to index:**
- Identifier occurrences (every reference to a name).
- String literals — verbatim, plus tokenized.
- Annotation/decorator argument strings.
- Comments (single-line and block).
- Config values from YAML/properties/HCL files (string fields only).

## Joern lane (out of band, optional)

Stored separately — generated on demand, not loaded into ladybugdb by default.

```cypher
-- Materialized only when an agent calls graph_taint:
CREATE REL TABLE FLOWS_TO FROM Symbol TO Symbol (path JSON, source STRING);
```

Joern's CPG has REACHING_DEF, CDG, DOMINATES — we don't ingest these wholesale. Instead, when an agent asks for a flow, we run the Joern query and write the resulting `FLOWS_TO` paths back into the graph as derived edges with provenance.

## Identity and incrementality

- **Symbol ID = stable hash** of `(language, qualified_name, signature_normalized)`. Robust against line/column drift across edits.
- **`ast_hash` per file** — when a file changes, recompute the AST hash. If unchanged, skip re-indexing. If changed, recompute symbols and diff.
- **Branch-aware** — every node has a `branch` property. Queries default to current branch; cross-branch queries are explicit.

## What we don't store

- Full source text (read from disk; symbol nodes carry positions).
- Raw AST bytes (Tree-sitter re-parses on demand cheap enough).
- Per-callsite edges as graph edges (use the `Callsite` side table).
- LLM-extracted "soft" edges (deferred per [architecture.md](architecture.md)).
