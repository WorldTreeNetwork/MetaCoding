# CTKR Observatory

An interactive visualization of the categorical knowledge representation:
the repo graph, its concept islands, and the dials that carve them.

```sh
bun run viz     # → http://localhost:4177
```

## What you can feel

**Territory** — the whole indexed graph (18k symbols, 30k typed edges) as a
force layout, with every knob from `docs/notes/entropy-as-dial.md` live:

- **Edge alphabet** toggles: which of the 15 relation kinds count. Islands and
  entropy recompute as you flip them.
- **Louvain resolution** (0.3–2.0): watch islands merge and shatter. Mirrors
  `ctkr subsystems` (same seed-42 determinism, same contains/references
  weighting).
- **CONTAINS / REFERENCES weights**: structure vs usage as the shaping force.
- **Granularity k** (1–12): the rate–distortion slider from `label_roles.py`.
  The entropy gauges replay `entropy_check.py`'s gates (≥4.0 bits, top-5
  coverage <50% proceed / >70% blocked) and the curve shows where you sit.
- **Color by boundary confidence**: the canonical 12-subsystem sweep's
  `boundary_confidence` as a diverging ramp — blue = solid member, red =
  judgment-call seam.
- **Click (or search) a symbol** → its name-blind role-equivalent twins by
  cosine over hom-profiles, with the ambiguity margin shown honestly:
  margin <0.01 is flagged as a coin-flip tie, per the functor-search
  `ambiguity_mass` caveat.

**The Port** — the porting layer's bipartite feature × event-kind graph
(`ctkr feature-kinds`): emit vs fold edges, status-gated folds, the kernel
surface at a tunable cross-feature degree threshold, and the freeze-kernel
toggle that collapses the serialized wave plan into parallel singletons.
CM decision registry (kernel v1.3) alongside.

## Data sources (all read-only)

| Route | Source |
|---|---|
| `/api/graph` | `.metacoding/ctkr/export/{nodes,edges}.jsonl` |
| `/api/profiles` | `.metacoding/ctkr/hom_profiles.parquet` |
| `/api/subsystems` | `.metacoding/ctkr/{subsystems,subsystem_members}.parquet` + `subsystem_cards.jsonl` |
| `/api/port` | `eval/ctkr/results/feature-kind-graph-data/graph_real.json` + `eval/ctkr/port_runs/kernel-9h5.24/build/cm-decisions.jsonl` |

The only write is the layout cache `.metacoding/viz-layout.json`
(ForceAtlas2, ~5 min cold, instant after). Regenerate the export with
`metacoding export .metacoding/ctkr/export` after a reindex, and delete the
layout cache to force a fresh layout.

All island/role/entropy computation runs client-side in a web worker
(graphology Louvain + profile quantization), so the dials respond in
hundreds of milliseconds without touching the store.
