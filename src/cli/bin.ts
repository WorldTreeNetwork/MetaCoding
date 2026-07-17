#!/usr/bin/env bun
// Wrapper entry point. Runs the ladybug-fixup side-effect module first,
// then dynamically imports the rest of the CLI.
//
// Why a wrapper: @ladybugdb/core is CJS, so Bun evaluates it during the
// ESM link phase, before any static-import side effects can run. A
// dynamic import defers main.ts's whole dep graph (which transitively
// pulls in @ladybugdb/core) until after the fixup completes.

import "../bootstrap/ladybug-fixup";
const { run } = await import("./main");
run();
