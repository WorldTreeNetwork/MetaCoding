# CTKR Layer-1 artifacts — `.metacoding/ctkr/` schema

Authoritative reference for the **mechanical** (Layer-1) artifact set produced
by `ctkr/` (the Python sub-project under MetaCoding). All L1 code reads from
and writes to these shapes; downstream L3 labelers and the CLI rely on them
unchanged.

The canonical pydantic models live in `ctkr/ctkr/schema.py` — this document
is the prose companion. If the two ever disagree, the pydantic models win and
this doc gets a fix.

## Why Parquet (and one JSON file)

Layer-1 outputs are large, columnar, machine-consumed, and rarely human-read.
Parquet gives us:

- Columnar I/O — node2vec dumps 300k × 128 floats; reading only `vec` or only
  `symbol_id` is cheap.
- Typed schemas — `float32` vectors stay `float32`, not `float64`.
- Polars / Arrow / DuckDB compatibility — ad-hoc queries from any of these
  without re-encoding.

The one exception is `manifest.json` at the directory root: it's a single
record, hand-readable, and consulted before every load to discover what's
present. JSON serves that better than Parquet.

## Layout

```
.metacoding/ctkr/
├── manifest.json            # ArtifactManifest — what's present, when, version
├── embeddings.parquet       # rows: EmbeddingRow
├── motifs.parquet           # rows: MotifRow
├── motif_instances.parquet  # rows: MotifInstanceRow
├── shape_pds.parquet        # rows: ShapePDRow
├── wasserstein_h1.parquet   # rows: WassersteinH1Row (pairwise topo distances)
├── centrality.parquet       # rows: CentralityRow
├── spectral_clusters.parquet # rows: SpectralClusterRow
└── nn_index/                # opaque ANN-index dir
    ├── nn_index.bin         # FAISS or hnswlib serialized index
    └── nn_index.meta.json   # NNIndexMeta sidecar
```

## Artifacts

### `manifest.json` — `ArtifactManifest`

Top-level pointer file. Records presence flags, counts, and the schema
version this directory's contents were validated against. Read this before
attempting to load any other artifact — it's cheap and authoritative.

Fields: `schema_version`, `generated_at`, `metacoding_data_dir`, presence
booleans (`embeddings`, `motifs`, `motif_instances`, `shape_pds`,
`wasserstein_h1`, `centrality`, `spectral_clusters`, `nn_index`),
`embedding_dim`, `n_symbols`, `n_motifs`, `n_motif_instances`, `notes`.

Presence booleans use bare names (e.g. `embeddings`, not `embeddings_present`)
— it reads better in the model and matches how every other CTKR field is
named. The pydantic model in `schema.py` is the contract; this doc trails it.

### `embeddings.parquet` — `EmbeddingRow`

One row per indexed symbol. Produced by L1/C1 (`Orchestrators-7u7`,
node2vec / GraphSAGE).

| column | type | meaning |
|---|---|---|
| `symbol_id` | string | matches `Symbol.id` in MetaCoding's TS store |
| `repo` | string | e.g. `cline`, `crewAI`; the cross-repo dimension |
| `qualified_name` | string | denormalized for human-readable nearest-neighbor output |
| `vec` | list&lt;float32&gt; | dimension fixed across the file; see `manifest.embedding_dim` |
| `schema_version` | int | row-level guard against silent version drift |

All vectors in a single file share a dimension. Regenerate the whole file
when the dimension changes (cheap; node2vec on 300k symbols is minutes).

### `motifs.parquet` — `MotifRow`

One row per discovered frequent typed subgraph. Produced by L1/C2
(`Orchestrators-k97`, gSpan / VF3-frequent-subgraph variant).

| column | type | meaning |
|---|---|---|
| `motif_id` | string | stable across runs given the same input graph + miner config |
| `signature` | string | canonical typed-edge-list serialization; the join key |
| `size_nodes` | int | node count in the subgraph pattern |
| `size_edges` | int | edge count |
| `support` | int | total corpus-wide occurrences |
| `repo_coverage` | list&lt;string&gt; | repos containing ≥1 instance |
| `edge_kinds` | list&lt;EdgeKind&gt; | distinct edge kinds present |
| `schema_version` | int |  |

Cross-repo coverage is the most informative cell for the synthesis we
actually care about: a motif with `repo_coverage` of 12+ is a candidate
**isomorphic pattern** in the CTKR sense.

### `motif_instances.parquet` — `MotifInstanceRow`

One row per concrete occurrence of a motif. Joins to `motifs.parquet` by
`motif_id`, and to `evidence.jsonl` (L3 artifact) by `(motif_id, symbol_id)`
via the L3/F3 evidence-retrieval module.

| column | type | meaning |
|---|---|---|
| `motif_id` | string | foreign key into `motifs.parquet` |
| `symbol_id` | string | anchor — the first node in `signature` order |
| `repo` | string |  |
| `file` | string | repo-relative |
| `line` | int | 1-based |
| `schema_version` | int |  |

### `shape_pds.parquet` — `ShapePDRow`

Persistent-homology shape signatures, one row per `(repo, dim)`. Produced
by L1/S1 (`Orchestrators-vbj`, gudhi).

| column | type | meaning |
|---|---|---|
| `repo` | string |  |
| `dim` | int | homology dimension (0, 1, 2 typically) |
| `birth` | list&lt;float32&gt; | parallel arrays — `birth[i]` and `death[i]` are the same pair |
| `death` | list&lt;float32&gt; |  |
| `schema_version` | int |  |

Encoded as parallel flat lists rather than `list<struct<...>>` because
Parquet's nested-struct-in-list support varies across readers (polars,
duckdb, pyarrow each behave slightly differently on `list<struct>`).

### `wasserstein_h1.parquet` — `WassersteinH1Row`

One row per ordered repo pair (`repo_a < repo_b` lexicographically). The
upper triangle only — the metric is symmetric, so the lower triangle is
implied. Produced by `ctkr shape` (L1/S1) alongside `shape_pds.parquet`.

| column | type | meaning |
|---|---|---|
| `repo_a` | string | lexicographically-smaller repo |
| `repo_b` | string | the other repo |
| `distance` | float | bottleneck distance between H₁ persistence diagrams |
| `schema_version` | int | row-level guard |

Naming caveat: the file says "wasserstein" but the implementation uses
the **bottleneck distance** (L∞-Wasserstein) via `gudhi.bottleneck_distance`.
The bottleneck distance is the L∞ variant of p-Wasserstein and doesn't
require `pot` (Python Optimal Transport), so it ships under the `topo`
extra alone. The file name is kept for compatibility with external callers
that already reference it.

The on-disk artifact produced before this schema doc landed lacks the
`schema_version` column; pydantic will default it on read. Next regen will
emit the column natively (writer changes are tracked alongside this doc).

### `centrality.parquet` — `CentralityRow`

One row per symbol in the global cross-repo graph. Produced by
`ctkr centrality` (L1/S2, `Orchestrators-2an`).

| column | type | meaning |
|---|---|---|
| `symbol_id` | string |  |
| `repo` | string |  |
| `qualified_name` | string | denormalized for human-readable output |
| `pagerank` | float | normalized PageRank score (≥ 0) |
| `betweenness` | float | (approximate, sampled-`k`) betweenness centrality (≥ 0) |
| `eigenvector` | float | eigenvector centrality (≥ 0) |
| `schema_version` | int |  |

Betweenness is approximate when `k < |N|` — the sample size used is
recorded in `ArtifactManifest.notes` when the writer runs.

### `spectral_clusters.parquet` — `SpectralClusterRow`

One row per symbol with its per-repo community assignment. Produced by
`ctkr centrality` (L1/S2 alongside `centrality.parquet`).

| column | type | meaning |
|---|---|---|
| `symbol_id` | string |  |
| `repo` | string |  |
| `qualified_name` | string |  |
| `cluster_id` | int | scoped to `repo` — not meaningful cross-repo |
| `cluster_size` | int | size of the symbol's cluster in its repo |
| `schema_version` | int |  |

The implementation uses **Louvain modularity** rather than literal spectral
clustering — the two correlate strongly on real-world graphs and Louvain
avoids the sklearn dependency for a P3 lane. See the module docstring in
`ctkr/centrality.py` for the swap-in path if literal spectral becomes
necessary.

### `nn_index/` — opaque, with `NNIndexMeta` sidecar

Approximate-nearest-neighbor index over the rows in `embeddings.parquet`.
Produced by L1/C3 (`Orchestrators-1l9`, FAISS or hnswlib). The `.bin`
file is backend-specific and not human-readable; `nn_index.meta.json`
exists so callers don't have to introspect it.

`NNIndexMeta` records: `backend`, `metric`, `embedding_dim`, `n_symbols`,
`built_at`, `embeddings_source` (used to detect staleness when
`embeddings.parquet` is regenerated without rebuilding the index).

## Regeneration

Each artifact is regenerated by its owning bd issue's CLI subcommand
(see `Orchestrators-4y4`):

| Artifact | Subcommand | Owning issue |
|---|---|---|
| `embeddings.parquet` | `ctkr embed` | `Orchestrators-7u7` |
| `motifs.parquet` + `motif_instances.parquet` | `ctkr mine-motifs` | `Orchestrators-k97` |
| `shape_pds.parquet` + `wasserstein_h1.parquet` | `ctkr shape` | `Orchestrators-vbj` |
| `centrality.parquet` + `spectral_clusters.parquet` | `ctkr centrality` | `Orchestrators-2an` |
| `nn_index/` | `ctkr build-nn` | `Orchestrators-1l9` |
| `manifest.json` | written by every command after a successful write | — |

## Versioning

`schema_version` lives at module level (`SCHEMA_VERSION` in `ctkr/schema.py`)
and is duplicated into every row of every artifact. Rules:

1. Adding a **new optional** field → no version bump needed (parquet readers
   tolerate missing columns gracefully).
2. Adding a **new mandatory** field → bump `SCHEMA_VERSION`. Old artifacts
   fail loud on load until regenerated.
3. **Renaming or retyping** a field → bump and rewrite all consumers.

Round-trip tests in `tests/test_schema.py` pin column orderings (via the
`*_COLUMNS` tuples in `schema.py`) — accidental reorderings fail loudly in
CI before they reach a downstream miner.
