// scripts/scip-php-prep.ts
//
// Prepare a PHP repo for scip-php (high-fidelity SCIP indexing) and produce an
// index.scip. Handles the two things scip-php needs that a raw checkout lacks:
//
//   1. An installed composer autoloader (composer.json + composer.lock +
//      vendor/). scip-php only indexes files reachable from the project's
//      composer `autoload` PSR-4/PSR-0 map.
//   2. For Drupal repos (farmOS et al.): Drupal modules are NOT composer-
//      autoloaded — core registers `Drupal\<module>\` namespaces at runtime.
//      We synthesize those PSR-4 entries from every `<module>.info.yml` so
//      scip-php can see the module classes.
//
// This produces an INTRA-repo-resolved index: references among the repo's own
// classes resolve; references into Drupal core / third-party deps stay external
// (that needs a full `composer install` of the site — see the memory note
// scip-php-integration). Requires Docker.
//
// Usage:
//   bun run scripts/scip-php-prep.ts <repo-path> [--out <index.scip>] [--keep]
//
// The repo is copied to a scratch working dir (never mutated in place). The
// final line prints the absolute index.scip path.

import { cpSync, existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync, mkdtempSync } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";

const SCIP_PHP_IMAGE = process.env.METACODING_SCIP_PHP_IMAGE ?? "davidrjenni/scip-php:latest";
const COMPOSER_IMAGE = process.env.METACODING_COMPOSER_IMAGE ?? "composer:latest";

interface Args { repo: string; out?: string; keep: boolean }

function parseArgs(argv: string[]): Args {
  const a: Args = { repo: "", keep: false };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i]!;
    if (v === "--out") a.out = resolve(argv[++i]!);
    else if (v === "--keep") a.keep = true;
    else if (!a.repo) a.repo = resolve(v);
  }
  if (!a.repo) throw new Error("usage: bun run scripts/scip-php-prep.ts <repo-path> [--out <index.scip>] [--keep]");
  return a;
}

// Recursively find every `<name>.info.yml` under `modules/` and map the module
// machine name (the file basename) to its sibling src/ (and tests/src/).
function synthesizeDrupalAutoload(root: string): Record<string, string> {
  const psr4: Record<string, string> = {};
  const walk = (dir: string): void => {
    let entries: string[];
    try { entries = readdirSync(dir); } catch { return; }
    for (const e of entries) {
      if (e === "vendor" || e === "node_modules" || e.startsWith(".")) continue;
      const p = join(dir, e);
      let st; try { st = statSync(p); } catch { continue; }
      if (st.isDirectory()) walk(p);
      else if (e.endsWith(".info.yml")) {
        const machine = basename(e, ".info.yml");
        const moduleDir = dirname(p);
        const src = join(moduleDir, "src");
        if (existsSync(src) && statSync(src).isDirectory()) {
          psr4[`Drupal\\${machine}\\`] = relative(root, src) + "/";
        }
        const testSrc = join(moduleDir, "tests", "src");
        if (existsSync(testSrc) && statSync(testSrc).isDirectory()) {
          psr4[`Drupal\\Tests\\${machine}\\`] = relative(root, testSrc) + "/";
        }
      }
    }
  };
  walk(join(root, "modules"));
  return psr4;
}

function isDrupal(root: string): boolean {
  if (existsSync(join(root, "modules"))) {
    // Any .info.yml under modules/ signals Drupal.
    const found = (() => {
      const stack = [join(root, "modules")];
      let n = 0;
      while (stack.length && n < 5000) {
        const d = stack.pop()!;
        let entries: string[];
        try { entries = readdirSync(d); } catch { continue; }
        for (const e of entries) {
          if (e.startsWith(".") || e === "vendor") continue;
          const p = join(d, e);
          n++;
          try {
            if (statSync(p).isDirectory()) stack.push(p);
            else if (e.endsWith(".info.yml")) return true;
          } catch {}
        }
      }
      return false;
    })();
    if (found) return true;
  }
  try {
    const cj = JSON.parse(readFileSync(join(root, "composer.json"), "utf-8"));
    return typeof cj.type === "string" && cj.type.startsWith("drupal-");
  } catch { return false; }
}

function docker(args: string[], label: string): void {
  const proc = Bun.spawnSync(["docker", ...args], { stdout: "pipe", stderr: "pipe" });
  if (proc.exitCode !== 0) {
    throw new Error(`${label} failed (exit ${proc.exitCode}):\n${proc.stderr.toString()}`);
  }
}

async function main(): Promise<void> {
  const args = parseArgs(Bun.argv.slice(2));
  if (!existsSync(args.repo)) throw new Error(`repo not found: ${args.repo}`);

  const work = mkdtempSync(join(tmpdir(), "scip-php-prep-"));
  console.error(`[prep] copying ${args.repo} -> ${work} (excluding .git/vendor)`);
  cpSync(args.repo, work, {
    recursive: true,
    filter: (src) => {
      const b = basename(src);
      return b !== ".git" && b !== "vendor" && b !== "node_modules";
    },
  });

  const drupal = isDrupal(work);
  let psr4Map: Record<string, string> = {};
  if (drupal) {
    const psr4 = synthesizeDrupalAutoload(work);
    psr4Map = psr4;
    console.error(`[prep] Drupal detected — synthesized ${Object.keys(psr4).length} PSR-4 autoload entries`);
    const composer = {
      name: "metacoding/scip-shim",
      type: "project",
      version: "1.0.0",
      require: {},
      autoload: { "psr-4": psr4 },
    };
    writeFileSync(join(work, "composer.json"), JSON.stringify(composer, null, 2));
    rmSync(join(work, "composer.lock"), { force: true });
  } else if (!existsSync(join(work, "composer.json"))) {
    throw new Error("no composer.json and not a Drupal repo — cannot prepare autoload for scip-php");
  }

  console.error(`[prep] composer install (${COMPOSER_IMAGE})`);
  docker(
    ["run", "--rm", "-v", `${work}:/app`, "-w", "/app", COMPOSER_IMAGE,
      "install", "--ignore-platform-reqs", "--no-interaction", "--no-progress", "--no-scripts"],
    "composer install",
  );

  // scip-php v0.0.1 crashes when installed.php root.reference is null (path
  // projects have no VCS reference). Backfill a placeholder so it proceeds.
  const installedPhp = join(work, "vendor", "composer", "installed.php");
  if (existsSync(installedPhp)) {
    const patched = readFileSync(installedPhp, "utf-8").replace(
      /('root' => array\([\s\S]*?'reference' => )(null|false)/,
      "$1'0000000000000000000000000000000000000000'",
    );
    writeFileSync(installedPhp, patched);
  }

  console.error(`[prep] running scip-php (${SCIP_PHP_IMAGE})`);
  docker(
    ["run", "--rm", "-v", `${work}:/src`, "-w", "/src", "--entrypoint", "scip-php",
      SCIP_PHP_IMAGE, "--memory-limit=2G"],
    "scip-php",
  );

  const produced = join(work, "index.scip");
  if (!existsSync(produced)) throw new Error("scip-php did not produce index.scip");

  let outPath = args.out ?? join(args.repo, "index.php.scip");
  cpSync(produced, outPath);
  const bytes = statSync(outPath).size;

  // Sidecar PSR-4 map: loadScip uses it to recover real file paths from
  // scip-php's namespace-derived relative_path (see phpRealFile).
  const psr4Path = `${outPath}.psr4.json`;
  writeFileSync(psr4Path, JSON.stringify(psr4Map, null, 2));

  if (!args.keep) rmSync(work, { recursive: true, force: true });
  else console.error(`[prep] kept working dir: ${work}`);

  console.error(`[prep] done — ${bytes} bytes. Load with: loadScip(store, "<path>", { language: "php", repo: "<name>" })`);
  // Final stdout line = the artifact path (SANDBOX unless --out points at prod).
  console.log(outPath);
}

main().catch((e) => { console.error("scip-php-prep FAILED:", e.message); process.exit(1); });
