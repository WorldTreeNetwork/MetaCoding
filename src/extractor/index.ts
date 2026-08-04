// The extractor's PUBLIC surface.
//
// `indexDirectory` and `watch` are not re-exported here: they are ingest entry
// points that write to the Store, and every ingest must go through an index
// session (src/ingest/session.ts) so a fitness verdict is persisted for it
// (docs/design/index-fitness.md, beads MetaCoding-0sd / ae5).
//
// THAT ABSENCE IS HYGIENE, NOT THE ENFORCEMENT (bead MetaCoding-9ed). A fresh
// judge reached the primitives anyway through nine import shapes — aliasing,
// namespaces, `await import()`, `require`, a re-export chain — and `indexFile`,
// exported RIGHT HERE, needed no evasion at all. So the seam is no longer a
// question of what a barrel exports: every one of these functions now requires
// an `IngestTicket` (src/ingest/ticket.ts) and refuses to write into a slice
// whose fitness currently reads established. `indexFile` stays public because
// exporting it is no longer the same thing as handing out a write capability.
export { indexFile, removeFile, detectGrammar } from "./walker";
export type { WalkOpts, WalkStats } from "./walker";
export type { WatchOpts, WatchHandle } from "./watcher";
