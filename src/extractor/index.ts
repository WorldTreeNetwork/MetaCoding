// The extractor's PUBLIC surface.
//
// `indexDirectory` and `watch` are deliberately NOT re-exported: they are
// ingest entry points that write to the Store, and every ingest must go through
// an index session (src/ingest/session.ts) so a fitness verdict is persisted for
// it (docs/design/index-fitness.md, beads MetaCoding-0sd / ae5). `metacoding
// watch` used to reach past the gate precisely because this barrel handed the
// primitive out. src/ingest/seam.test.ts fails the suite if any module in src/
// other than the session imports them again.
export { indexFile, removeFile, detectGrammar } from "./walker";
export type { WalkOpts, WalkStats } from "./walker";
export type { WatchOpts, WatchHandle } from "./watcher";
