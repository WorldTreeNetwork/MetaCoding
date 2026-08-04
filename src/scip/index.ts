// The scip package's PUBLIC surface.
//
// `loadScip` is not re-exported here: it is an ingest entry point that writes to
// the Store, and every ingest must go through an index session
// (src/ingest/session.ts) so a fitness verdict is persisted for it
// (docs/design/index-fitness.md). `runScip` stays — it only produces a `.scip`
// FILE and touches no Store.
//
// The absence is hygiene, not the enforcement: `loadScip` requires an
// `IngestTicket` (src/ingest/ticket.ts, bead MetaCoding-9ed) and refuses to
// write into a slice whose fitness currently reads established, however the
// caller got hold of it.
export { runScip, runScipTypescript, resolveScipBin } from "./run";
export type { RunScipOpts, RunScipResult, ScipLanguage } from "./run";
export type { LoadScipOpts, LoadScipStats } from "./loader";
