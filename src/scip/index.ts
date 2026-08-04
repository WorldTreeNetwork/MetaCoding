// The scip package's PUBLIC surface.
//
// `loadScip` is deliberately NOT re-exported: it is an ingest entry point that
// writes to the Store, and every ingest must go through an index session
// (src/ingest/session.ts) so a fitness verdict is persisted for it
// (docs/design/index-fitness.md). `runScip` stays — it only produces a `.scip`
// FILE and touches no Store.
export { runScip, runScipTypescript, resolveScipBin } from "./run";
export type { RunScipOpts, RunScipResult, ScipLanguage } from "./run";
export type { LoadScipOpts, LoadScipStats } from "./loader";
