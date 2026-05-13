# CTKR Layer-3 artifacts — `patterns.jsonl` + `evidence.jsonl`

Authoritative reference for the **LLM-bridged** (Layer-3) artifact set
produced by `ctkr/` labelers. L3 takes L1's mechanical outputs (motifs,
role clusters, cross-repo analogies) and pairs each with a natural-language
label, a description, and pointers to concrete code evidence.

The canonical pydantic models live in `ctkr/ctkr/schema_l3.py` — this
document is the prose companion.

## Why JSONL (not Parquet)

L3 rows are produced one at a time during LLM streaming, often hours apart
across batches. Append-friendly text is more practical than columnar:

- Append a row per LLM completion without rewriting the file.
- `git diff` over labels is meaningful — useful when humans spot-check.
- Re-running with a new prompt is *additive*: emit a new file under a new
  `prompt_version` rather than rewriting in place.

Natural-language fields don't benefit from columnar compression in the
sizes we're producing (~thousands to low tens of thousands of patterns).

## Layout

```
.metacoding/ctkr/
├── patterns.jsonl    # rows: PatternRow
└── evidence.jsonl    # rows: EvidenceRow
```

Both files live alongside the L1 Parquet outputs documented in
`ctkr-artifacts.md`.

## `patterns.jsonl` — `PatternRow`

One row per labeled structural element. Joins L1 ↔ L3.

| field | type | meaning |
|---|---|---|
| `pattern_id` | string | stable across re-runs given same `(source_kind, source_ref, prompt_version, llm_model)` |
| `source_kind` | `"motif" \| "role-cluster" \| "analogy"` | which L1 artifact this labels |
| `source_ref` | string | foreign key — `motif_id`, cluster-id, or analogy-pair id |
| `label` | string | short canonical name, ~3 words; reused downstream |
| `description` | string | one-paragraph explanation; "what this is and why it recurs" |
| `instances` | list&lt;string&gt; | symbol IDs participating (anchors for motifs) |
| `evidence_ids` | list&lt;string&gt; | optional — usually empty; primary join is by `pattern_id` |
| `confidence` | float in [0, 1] | LLM-reported or post-hoc score |
| `llm_model` | string | **MANDATORY** — e.g. `claude-opus-4-7` |
| `llm_temperature` | float | **MANDATORY** — may be `0.0` for deterministic mode |
| `prompt_version` | string | **MANDATORY** — e.g. `motif-labeler:v3` |
| `schema_version` | int | **MANDATORY** — see `SCHEMA_VERSION` in `schema_l3.py` |
| `generated_at` | datetime | ISO-8601 |

### Provenance is non-negotiable

`llm_model`, `llm_temperature`, `prompt_version`, and `schema_version` are
all mandatory and non-null. This is the only mechanism by which an old
label can be retired when:

- the prompt changes (e.g. a sharper motif-labeler prompt),
- the model changes (e.g. swap from Opus 4.6 to Opus 4.7),
- the schema changes (e.g. we add a new mandatory field).

Without these four, labels can't be invalidated reliably and the labeled
corpus rots silently. The pydantic models enforce non-null at load time.

### Pattern ID stability

`pattern_id` is deterministic given the same `(source_kind, source_ref,
prompt_version, llm_model)`. Re-running the labeler with the same prompt
+ model produces the same `pattern_id` for the same source — overwrite,
don't accumulate. Bumping `prompt_version` or `llm_model` produces a
*different* `pattern_id` for the same source — both versions coexist,
and reviewers can compare them.

## `evidence.jsonl` — `EvidenceRow`

One row per source-code snippet supporting a label. Multiple rows per
`pattern_id`; produced by L3/F3 (`Orchestrators-c0d`, evidence-retrieval).

| field | type | meaning |
|---|---|---|
| `pattern_id` | string | foreign key into `patterns.jsonl` |
| `repo` | string |  |
| `file` | string | repo-relative |
| `line_range` | `{start, end}` | inclusive line span |
| `snippet` | string | materialized code; trimmed to ~80 char wide; spans `line_range` |
| `context` | string \| null | optional enclosing-symbol qualified_name |
| `schema_version` | int |  |

### Why materialize the snippet

The snippet text is captured into the JSONL rather than re-resolved on
read. That makes `evidence.jsonl` self-contained for review (no need to
keep the original repo checkout in sync), and lets us ship labeled
artifacts independently of the source corpus.

Cost: file grows. We expect ~3 snippets per pattern × ~10 lines per
snippet × ~200 chars per line ≈ 6 KB/pattern. At 5k patterns that's
~30 MB — manageable.

## Versioning

`schema_version` (this module) and `prompt_version` (each labeler) are
independent dimensions:

- `schema_version` bumps when fields/types change. Old JSONL becomes
  un-loadable until regenerated.
- `prompt_version` bumps when a labeler's prompt template changes.
  Old JSONL stays loadable but is considered stale.

Re-runs are additive: new prompt → new `prompt_version` → new
`pattern_id` for each source → coexists with old labels in the same
`patterns.jsonl` until garbage-collected by a separate `ctkr prune`
pass (not yet built; will be its own bd issue).

## Quality gates

L3 quality checks live in `Orchestrators-gss` (multi-model consensus),
`Orchestrators-59e` (human spot-check), and `Orchestrators-9w6` (label
stability). They all consume `patterns.jsonl` directly — that's the
single source of truth for what L3 has produced.
