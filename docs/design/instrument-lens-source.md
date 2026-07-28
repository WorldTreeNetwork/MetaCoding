# The instrument, the lens, the source, and the ledger

> 2026-07-29 · Design elicitation for `MetaCoding-1gt`. Written after Duke's call
> that per-command paths and a `METACODING_PORT_WORKSPACE` env var are a **code
> smell**, not a fix: *"if we do that right, we won't have to worry so much about
> specifying which project, which instruments, bunch of paths."*
>
> Follows the house form: the question, the options with tradeoffs, a
> recommendation, a rationale, and a reversal condition. Nothing here is bound.

## The measurement first

Design arguments about "tangling" are worthless without numbers, and the numbers
turned out to contradict the assumption this bead was filed on.

**The instrument is already almost clean.** The whole coupling from generic
oracle machinery to farmOS is **one import**:

```
ctkr/ctkr/oracle/recorder.py:32   from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
```

`fixtures.py`, `adapter.py`, `port_adapter.py`, `flowspec_io.py` mention farmOS
**only in prose** — zero code coupling. (An earlier count of "136 hits in
recorder.py, 81 in fixtures.py" was a bad grep: it matched domain words like
`harvest`, `animal`, `quantity` appearing in docstrings and glossary examples.
Quoted here because it nearly justified a much larger rewrite than the code
needs.)

What is genuinely target-specific but physically inside the instrument package:

| kind | files |
|---|---|
| lens code | `oracle/glossary.py`, `oracle/probes.py`, `oracle/farmos_adapter.py`, `oracle/bring-up.sh`, `drupal.py`, `farmos_diff.py`, `commands/drupal_harvest.py` |
| lens ledger | `oracle/glossary_provenance.jsonl` |
| farmOS evidence used as instrument test data | `oracle/data/core-pack/**`, `oracle/data/hardening-pack/**`, `oracle/data/farmos_*_observations.jsonl`, `oracle/data/w0_flows.json` |
| hardcoded target selection | `commands/oracle_verify.py:34` — `choices=["farmos"]`, with an inline import at :52 |

And the smell Duke named, measured: **44 commands share 7 different path-ish
flags** — `--data-dir` (11 commands), `--repo` (3), `--base-url` (2), plus
`--src`, `--root`, `--rel-root`, `--out-dir`, `--flows`, `--adapter` — and as of
yesterday one env var.

## Amendment, 2026-07-29 — the measurement above is right and misleading

"The entire coupling is one import" is true **of the adapter** and undersells the
system badly. Checking what generic code imports, rather than what it mentions,
found the real thing: the target's vocabulary is **ambient module-level state
that the core reads directly.**

- `ctkr.oracle.glossary` — the closed sets — is imported by
  `fixtures.py`, `flowspec_io.py`, `port_contract.py`, `probes.py`, `lexicon.py`,
  `propose_terms.py`, `role_gaps.py`. `fixtures.py` validates against
  `glossary.ENTITY_TERMS`, `glossary.ANIMAL_SEXES`, `glossary.FORBIDDEN_WORDS`
  at model-validation time.
- `probes.PROBE_CONTRACT` — the probe dispatch table — is imported by
  `runner.py`, `pack.py`, `port_verify.py`, `flowspec_io.py`,
  `glossary_provenance.py`.
- **`term_codegen.py` hardcodes eight instrument file paths** — `GLOSSARY`,
  `PROBES`, `STEPS`, `ADAPTER`, `FARMOS`, `RECORDER`, `FIXTURES`,
  `PORT_ADAPTER` — and generates code *into* them.

So the sharpest statement of the problem is not about flags at all:

> **Adding one farmOS word edits MetaCoding's source.** `add-term` writes into
> eight files of the instrument. A second port does not just pass different
> paths — it writes its vocabulary into the same eight files as the first.

That is precisely the thing Duke ruled out: *"it needs to handle many more ports
without having to change the source each time."* The adapter inversion is an
afternoon; **this** is the inversion.

### Decisions taken (Duke, 2026-07-29)

- **Invert.** A lens depends on ctkr; ctkr never imports a lens. N ports, zero
  instrument edits.
- **Tests keep pointing at farmOS for now.** The synthetic target is deferred,
  not cancelled — extract it once the porting code that lives in MetaCoding is
  stable. Recorded as a known temporary state: until then the instrument's suite
  depends on farmOS packs, so "target-agnostic" is a claim, not a measurement.
- **The build is not forever married to the instrumentation that delivered it.**
  The ported app gets its own repo when it ships; `build/` stays splittable and
  nothing is designed assuming ledger and build share a tree forever.
- **Open question 2, decided as delegated:** keep **one `farmos_lens`**. Do not
  pre-split a `drupal_lens`. The Drupal harvest and Drupal-shaped adapter would
  serve any Drupal target, but a second Drupal target does not exist and
  factoring for it now is speculative generality. **Reversal condition:** the
  moment a second Drupal-shaped target is scoped, split `drupal_lens` out —
  before its first term is bound, not after.
- **Open question 3 is moot while the toy target is deferred.** `d1l` (OIDC,
  identikey) is the second real target and is unstarted; farmOS is what ships,
  into the lightning mesh services. Landing the farmOS port outranks proving
  agnosticism.

### What the inversion has to move

| ambient today | becomes |
|---|---|
| `from ctkr.oracle import glossary` (7 modules) | vocabulary carried by the active lens |
| `from ctkr.oracle.probes import PROBE_CONTRACT` (5 modules) | probe contract carried by the active lens |
| `term_codegen`'s 8 hardcoded instrument paths | codegen targets declared by the lens |
| `recorder.py:32` `FarmOSAdapter` import | adapter factory from the lens |
| `oracle_verify.py:34` `choices=["farmos"]` | discovered lens names |

## The actual diagnosis

The flags do not proliferate because paths are hard. They proliferate because
**a port has no identity in this system.** There is no object called "the farmOS
port" that a command can be handed or can discover. There are only four
*separately addressed* piles:

1. **the source** — the pristine codebase being ported, read-only, pinned
2. **the lens** — the project-specific instrumentation that lets a generic
   instrument speak this domain: glossary, adapters, probes, oracle bring-up
3. **the ledger** — the evidence: packs, seals, `PACKS.jsonl`, provenance,
   decisions, the partition
4. **the build** — the ported code itself

Every command must be told, piecemeal, where each pile is. So every new artifact
earns a new flag, and yesterday's `METACODING_PORT_WORKSPACE` is simply the
eighth of them. Adding a ninth would be the same mistake with a longer name.

**Name the thing and the flags collapse into it.** A port is a first-class,
self-describing entity with a manifest; commands run *inside* it and discover it,
the way `git` walks up to `.git` and `cargo` to `Cargo.toml`. Paths stop being
arguments and become *facts the port already knows*. Flags survive only as
deliberate overrides for exceptional runs, which is what a flag is for.

## The second half: which way the dependency arrow points

Context discovery alone is not enough. Today the instrument reaches *down* into a
target (`recorder.py` importing `FarmOSAdapter`; `choices=["farmos"]`). While the
arrow points that way, every new target edits the instrument, and "which project"
stays a question the instrument has to ask.

**The arrow must point one way: lens → instrument.** A lens depends on ctkr and
registers itself; **ctkr never imports a lens.** With that inversion, adding the
OIDC target of `MetaCoding-d1l` touches zero instrument files.

## The enforcement — this is the part that lasts

A boundary maintained by discipline decays; this project's own record says so.
The boundary should be **measured by the test suite**:

1. **The instrument ships its own toy target.** A tiny synthetic domain (a dozen
   terms, an in-memory adapter) that ctkr's tests run against. Today ctkr's tests
   use farmOS packs as fixtures — `core-pack`, `hardening-pack`, `w0_flows.json`
   — which means farmOS *cannot leave* without gutting the suite. A synthetic
   target proves target-agnosticism by construction, and it makes "port a second
   codebase" a path the tests walk every run rather than a claim.
2. **A fitness test: the instrument may not know the word.** A check that
   `farmos|drupal|farm_` does not appear in `ctkr/ctkr/**` or `src/**` outside
   changelogs. It fails the moment the boundary is breached, which is the only
   kind of boundary this project has ever kept — *a fix ships with the evidence
   that would catch its regression.*

Without (1), farmOS is load-bearing for the instrument's own tests and the split
is cosmetic.

## The layout question — three repos or four

`port_runs` + `results` were extracted to `/Users/dukejones/work/WorldTree/farmos-port`
yesterday (history preserved, tree hashes byte-identical, no remote yet). That
settled the ledger's location but not the lens's or the build's.

**Option 1 — three repos.** instrument (`MetaCoding`) · port workspace
(lens + ledger + build, `farmos-port`) · source (`farmos-src`, upstream clone).
- **For:** matches 1gt's stated layout; one place to look for everything about a
  port; the manifest sits at the workspace root where discovery expects it.
- **Against:** conflates the *evidence* with the *product*. The build is the
  deliverable; the ledger is the proof. They have different audiences, different
  lifetimes, and — per the exit test — the build is the thing that must be able
  to leave. A port that ships gets published as a repo of its own eventually.

**Option 2 — four repos.** As above, but the build separates from the ledger.
- **For:** the deliverable can leave with its own history, which the exit test
  wants; the ledger stays an audit trail nobody has to vendor.
- **Against:** a fourth clone to keep in sync for work that is currently one
  person's; cross-repo commits (build + the pack proving it) stop being atomic,
  and this project's discipline is that a fix and its evidence land together.

**Option 3 — two repos.** instrument · everything-per-port, source vendored in.
- **For:** fewest moving parts.
- **Against:** breaks source-pristine. The source must stay upstream's, unedited
  and re-clonable at a pin; vendoring invites the one write that poisons the
  witness.

**Recommendation: Option 1 now, with the build in a top-level `build/` directory
so Option 2 is a later `git subtree split` and not a migration.** The atomicity
argument is decisive while one person holds both sides: a build and the pack that
scores it should land in one commit. Revisit when the farmOS port is something
someone else runs — that is the reversal condition.

## What the manifest declares

One file at the workspace root — `port.toml` — replacing the flag pile:

```toml
[port]
name = "farmos"

[source]
path = "../farmos-src"                                     # pristine, read-only
pin  = "3fe0ce7e23de807be9b8bc97a211ce934327db39"          # farmOS 4.0.4

[lens]
package = "farmos_lens"        # depends on ctkr; ctkr never imports it

[oracle]
base_url = "http://localhost:8095"
images   = { farmos = "sha256:2c0ed3ed…", postgres = "sha256:33f923b0…" }

[ledger]
packs     = "port_runs/PACKS.jsonl"
decisions = "port_runs/kernel-9h5.24/build/cm-decisions.jsonl"

[build]
path = "build"

[cache]
path = ".metacoding"           # derived only; one command regenerates it
```

Three properties this must have, each learned the hard way:

- **The pin lives here, not in a script.** A floating tag re-based 43 packs onto
  an unrecorded source for six days without an error (`4b6829f`).
- **`[cache]` is never load-bearing.** The `u00` lesson: the graph export was
  cited by the partition, then vanished from `/tmp` with nothing able to tell.
  Anything under `[cache]` must be reconstructible from `[source]` + the ledger
  by one command, and the instrument should say so when it is missing rather than
  degrade silently.
- **The registry path stays fixed *within* the workspace.** Only the root is
  discovered. A movable decisions registry re-opens the self-certification hole
  `port_contract.py`'s INVARIANT 2 exists to refuse — a port must not get to
  nominate the file that grades it.

## Migration sequence

Each step leaves the suite green and is independently revertible.

1. **Invert the arrow.** Replace `recorder.py:32` and `oracle_verify.py`'s
   `choices=["farmos"]` with lens resolution. One import, one flag. *(The whole
   code-level coupling.)*
2. **Add the synthetic target + the fitness test**, with farmOS still in place.
   Now the boundary is measured, and step 3 cannot silently half-happen.
3. **Move the lens** — glossary, provenance, probes, `farmos_adapter`, `drupal`,
   `farmos_diff`, `drupal_harvest`, `bring-up.sh` — into `farmos-port` as a
   `farmos_lens` package depending on ctkr. Repoint ctkr's tests at the synthetic
   target; move the farmOS packs out of `oracle/data/` with the rest of the ledger.
4. **Introduce `port.toml` + discovery**, and delete the flags it subsumes —
   including `METACODING_PORT_WORKSPACE`, which exists only to be deleted here.
5. **Give `farmos-port` a remote and push it**, then delete
   `eval/ctkr/{port_runs,results}` from MetaCoding. **Not before:** until that
   push, MetaCoding holds the only pushed copy of 43 sealed packs.

Steps 1–2 are worth doing regardless of how the layout question lands: they are
the parts that make the boundary real rather than declared.

## Open questions for Duke

1. **Layout — Option 1, 2 or 3?** Recommendation above is 1-with-`build/`-ready-to-split.
2. **Does the lens belong to the *source family* rather than the port?** The
   Drupal harvest and the Drupal-shaped adapter would serve any Drupal target,
   not just farmOS. Splitting `drupal_lens` from `farmos_lens` is more correct and
   is speculative generality until the second Drupal target exists. I would keep
   one `farmos_lens` and split when something forces it.
3. **Is the toy target worth its keep?** It is real code with no user. My claim is
   that it is the only thing that makes the boundary testable, and that a
   second real target (`d1l`'s OIDC) does not substitute — it arrives later, is
   heavier, and needs network.
