# Wave-0 pilot artifacts (rescued 2026-07-20)

These are the wave-0 pilot's real outputs. They were produced in a **previous
session's `/tmp` scratchpad** and were never committed — one `/tmp` sweep from
being lost, with the pilot report referencing files that no longer existed
anywhere in the repo. Recovered from
`/private/tmp/claude-501/.../7c92fede-.../scratchpad/wave0/`.

| file | what it is |
|---|---|
| `w0a-fixture_candidates.jsonl` | 50 mined semantic candidates — farm_inventory |
| `w0b-fixture_candidates.jsonl` | 13 mined semantic candidates — farm_animal lifecycle |
| `w0{a,b}-adapter_contract.{json,md}` | generated adapter surfaces (`ctkr propose-adapter`) |
| `w0{a,b}-propose.log` | propose-adapter run logs |
| `w0a-build/` | the blind kernel-integration build (11/11 own tests, conformance-only judged) |
| `w0{a,b}-src/` | the scoped source slices the stages read |

**These candidates are UNOBSERVED.** Their `then` clauses are prose descriptions
of what to assert, not values — the OBSERVE stage never ran (oracle was down).
Nothing here may be treated as evidence of farmOS behavior until recorded against
the live oracle; see `docs/design/no-oracle-fallback.md`.

Lesson (CLAUDE.md §"Reporting data-dir scope"): artifacts a later stage depends on
belong in the repo, not a session scratchpad.
