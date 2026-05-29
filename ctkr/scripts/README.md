# ctkr/scripts — CTKR Codegen Pipeline

Two-step pipeline that generates TypeScript types from the pydantic schemas in
`ctkr/ctkr/schema.py` (L1) and `ctkr/ctkr/schema_l3.py` (L3), with a structural
diff against the hand-written mirror types.

## Pipeline overview

```
ctkr/ctkr/schema.py          ┐
ctkr/ctkr/schema_l3.py       ┘  (single source of truth)
        │
        ▼  Step 1 — emit_json_schema.py (uv run python)
.metacoding/ctkr/schemas/
    ArtifactManifest.json
    CentralityRow.json
    EmbeddingRow.json
    EvidenceRow.json
    LineRange.json
    MotifInstanceRow.json
    MotifRow.json
    NNIndexMeta.json
    PatternRow.json
    ShapePDRow.json
    SpectralClusterRow.json
    WassersteinH1Row.json
        │
        ▼  Step 2 — codegen-ctkr-types.ts (quicktype-core)
src/ctkr/types.gen.ts        (generated, do not edit)
        │
        ▼  Step 3 — structural diff
Console report: missing/extra types and field mismatches vs types.ts
```

## Scripts

| npm script | What it does |
|---|---|
| `bun run codegen:ctkr-types` | Full pipeline: emit schemas → generate TS → diff report |
| `bun run codegen:check` | Same as above, then runs `tsc --noEmit` on the generated file |

## Step 1: `emit_json_schema.py`

Imports every pydantic `BaseModel` subclass listed in `__all__` from both schema
modules, calls `.model_json_schema()`, and writes one JSON Schema file per model
to `.metacoding/ctkr/schemas/`. Each file also carries:

- `$schema_version` — the value of `SCHEMA_VERSION` from `schema.py` (currently `1`)
- `$source_module` — the dotted module name the model came from

Design choice: **one file per model** rather than a single bundle. This lets
quicktype-core assign independent top-level names and avoids name-collision
issues with combined `$defs`.

Run standalone:
```sh
cd ctkr
uv run python scripts/emit_json_schema.py [--out-dir PATH]
```

## Step 2: `codegen-ctkr-types.ts`

Uses the `quicktype-core` programmatic API (not the CLI) to read each JSON
Schema and emit a single `src/ctkr/types.gen.ts`. Configuration:

- `just-types: true` — interfaces only, no conversion helpers
- `prefer-unions: true` — union types over discriminated union wrappers
- Field names: **snake_case preserved** (pydantic default; no renaming)
- Enums inferred (e.g. `EdgeKind`, `SourceKind`, `Backend`, `Metric`)
- No date-time, UUID, or integer-string inference

## Step 3: Structural diff

A lightweight regex-based parser extracts `export interface Foo { ... }` blocks
from both files and reports:

- Types present in `types.ts` but missing from `types.gen.ts`
- Types present in `types.gen.ts` but not in `types.ts`
- Per-type field mismatches (missing / extra)

### Known benign diffs

| Diff | Reason |
|---|---|
| `NNLabelRow` missing from generated | Hand-written only — not a pydantic model |
| `LineRangeObject` extra in generated | quicktype deduplication artefact; same shape as `LineRange` |
| `backend: Backend` vs `backend: "faiss" \| "hnswlib"` | quicktype extracts named type alias; semantically identical |
| `metric: Metric` vs `metric: "cosine" \| "l2" \| "ip"` | Same |
| `source_kind: SourceKind` vs inline union | Same |
| `null \| string` vs `string \| null` | Union order; semantically identical |

## Adding new models

1. Add the pydantic model to `schema.py` or `schema_l3.py` and list it in `__all__`.
2. Run `bun run codegen:ctkr-types` — the new JSON Schema and TS interface appear automatically.
3. Update `src/ctkr/types.ts` (hand-written mirror) if needed, then swap to `types.gen.ts` in a follow-up.

## Requirements

- Python 3.12 with `uv` (the `.venv` in `ctkr/` is used automatically)
- `pydantic>=2.8` (already in `ctkr/pyproject.toml`)
- `quicktype-core` npm package (already in root `package.json`)
