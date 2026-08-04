# Notes

Working notes, conceptual reasoning, and forward roadmap material that doesn't belong in the polished `design/` or `research/` docs but is too valuable to lose.

Format: dated session notes for conceptual work; non-dated for living roadmap material.

## Index

- [`2026-05-28-ctkr-design-session.md`](./2026-05-28-ctkr-design-session.md) — design session establishing the CTKR phased plan: terminology corrections (strict vs. partial functors), Yoneda framing, colimit-via-community-detection, persistent-clustering as the multi-resolution generalization, language-seam decision (TS for MCP + Phase 2; Python for L1/L3), stochastic methods opening.
- [`entropy-as-dial.md`](./entropy-as-dial.md) — reframes Shannon entropy of hom-profile distributions from a hard threshold to a tunable parameter. Rate-distortion framing, persistent-clustering across dial settings, implications for Phase 2+ MCP tool signatures.
- [`ctkr-bead-roadmap.md`](./ctkr-bead-roadmap.md) — living roadmap of the full bead set for CTKR Phases 1–4. What's been created in `bd`, what's deferred-but-tracked. Update as phases ship.
- [`2026-08-04-rfc-citation-density-spike.md`](./2026-08-04-rfc-citation-density-spike.md) — measurement spike (MetaCoding-d1l.6) on RFC-citation density in fosite / zitadel-oidc / node-oidc-provider. 6.6 / 4.1 / 1.6 section citations per KLOC; 5.6% / 8.0% / 0.3% of exported symbols within 10 lines of one. Verdict: tier 1 of spec-anchored porting is a seed and an oracle, not the backbone — re-scope the epic. Script: `scripts/spike-citation-density.ts`.
- [`2026-08-04-go-js-lane-spike.md`](./2026-08-04-go-js-lane-spike.md) — output of MetaCoding-d1l.7. Per-lane, per-language edge counts for Go (`scip-go` on `ory/fosite`) and JS (`scip-typescript` on `panva/node-oidc-provider`). Go SCIP works well (CALLS 3,274 / IMPLEMENTS 586) but there is no Go lane in the code; the JS lane works through the shipped CLI unchanged; the tree-sitter + FTS fallback is dark for both languages; and `metacoding index <go-repo> --scip` exits 0 with an empty graph.
- `preconceptual-prototype-{A,B,C}.md` + `preconceptual-prototype-findings.md` — output of the Phase 3 UX prototype spike (MetaCoding-5wi). Three presentation formats tested on the correlated tool-result re-injection pattern; contrast pair won.
