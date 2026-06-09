// Side-effect module: ensures @ladybugdb/core's native binary is in place
// before the package is required.
//
// @ladybugdb/core ships an `install.js` postinstall that copies
// lbugjs.node from the matching @ladybugdb/core-<platform>-<arch> package
// into @ladybugdb/core/. Bun blocks postinstalls by default, and
// `trustedDependencies` is ignored for global installs, so users would
// otherwise have to run `bun pm trust @ladybugdb/core` by hand. We do the
// copy ourselves on first run.
//
// Importing this module statically isn't enough — @ladybugdb/core is CJS
// and is evaluated during the ESM link phase, before sibling ESM imports
// get to run their top-level code. The bin wrapper (src/cli/bin.ts) runs
// this first and only then dynamic-imports the rest of the CLI.

import { existsSync, copyFileSync, symlinkSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const req = createRequire(import.meta.url);

try {
  const coreDir = dirname(req.resolve("@ladybugdb/core/package.json"));
  const target = join(coreDir, "lbugjs.node");
  if (!existsSync(target)) {
    const platformPkg = `@ladybugdb/core-${process.platform}-${process.arch}`;
    const platformDir = dirname(req.resolve(`${platformPkg}/package.json`));
    const source = join(platformDir, "lbugjs.node");
    if (existsSync(source)) {
      try { symlinkSync(source, target); }
      catch { copyFileSync(source, target); }
    }
  }
} catch {
  // Package or platform variant not installed — let the normal load
  // error surface a more meaningful message at use time.
}
