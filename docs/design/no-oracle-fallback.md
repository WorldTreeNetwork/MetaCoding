# No-oracle fallback policy

> Bead MetaCoding-9h5.28 (c). Written 2026-07-20, after the wave-0 pilot lost the
> live farmOS oracle mid-run and had to decide, live, what a build could honestly
> claim without it.

## The rule

**Observation is the only source of values. When the oracle is down, the pipeline
degrades what it CLAIMS — never what it invents.**

A fan-out that silently substitutes plausible values for observed ones produces
exactly the failure mode this whole method exists to prevent: the pure-LLM cell's
output was fluent, internally consistent, and wrong. That result is the standing
proof. An unavailable oracle is a *reduced claim*, not a licence to guess.

## What changes when the oracle is down

| stage | with oracle | without oracle |
|---|---|---|
| SCOPE / SURFACE / SEMANTICS | unaffected — source-derived | unaffected |
| mine-fixtures | candidates mined from source | **unaffected** — mining reads the source, not the oracle |
| OBSERVE | candidates → observed fixtures | **BLOCKED.** Candidates stay `source-derived`, explicitly flagged |
| BUILD | blind build on the kernel | unaffected — the builder never sees the oracle |
| JUDGE | value-equivalence verdict | **conformance-only verdict.** NOT a value claim |
| wave promotion | eligible | **ineligible** — a feature cannot be promoted on a conformance-only judge |

## The three prohibitions

1. **Never author a fixture value.** A fixture whose `then` values were reasoned
   out rather than observed is a fabrication wearing the costume of evidence. If
   the oracle cannot answer, the candidate stays a candidate.
2. **Never launder a conformance verdict into a value verdict.** "Passes 11/11 of
   its own tests" means the build is self-consistent and kernel-conformant. It says
   nothing about whether it does what farmOS does. Reports must say so in those
   words — the wave-0 pilot's build report is the reference wording.
3. **Never let an unobserved decision be marked resolved-by-evidence.** It may be
   `decided-for-me` with a reversal condition naming the observation that would
   settle it (e.g. w0a-2's tie-break), but the decision record must show that the
   evidence limb is outstanding.

## What IS allowed without the oracle

- Mining, scoping, surfacing, and adapter generation — all read the source.
- Blind kernel-integration builds, judged on: builds on kernel primitives; the
  prevention gates hold (registered kinds, `IdMinter`, status gates); reproduces
  the source-mined semantics on its own tests.
- Decisions with named reversal conditions, recorded as such.
- Anything that would be re-run identically once the oracle returns.

## Operational preflight

`ctkr oracle-record` and `ctkr oracle-verify` run `ctkr.oracle.health.require_oracle`
before doing any work: two short-timeout probes (`/api`, then `POST /oauth/token`),
failing in seconds with the remedy attached, exit code **2**. This exists because
the pilot's calls inherited urllib's no-timeout default and hung ~29s each, turning
an outage into a slow, ambiguous one. `--skip-preflight` exists but should not be
used in a wave.

Note the middle state the second probe catches: a fresh `farmos/farmos:4.x`
container answers `/api` long before the farm profile is installed. "Container up"
is not "oracle usable", and recording against a half-installed instance would
produce confidently wrong observations — worse than no observations.

## Recovery

The oracle is **ephemeral by design**; losing it costs a rebuild, not data.

```bash
ctkr/ctkr/oracle/bring-up.sh                       # ~2 min with images cached
uv run python -m ctkr oracle-verify \
  ctkr/oracle/data/core-pack/fixtures.jsonl --adapter farmos   # must be 7/7
```

The 7/7 self-verification is mandatory after any rebuild: it proves the new
instance is behaviorally identical to the one that recorded the existing pack. Only
then may previously-blocked observation resume. (Done 2026-07-20 after an OrbStack
restart returned zero containers — 7/7 passed, no fixtures invalidated.)

## Wave-scale throughput (open — 9h5.28 d)

One oracle instance is a single point of failure and a serialization point for a
100+ feature fan-out. Options not yet evaluated: a second instance behind the
recorder, or a post-install snapshot/restore so bring-up is seconds rather than
minutes. Until then, an oracle outage stalls OBSERVE for the whole wave, and this
policy is what keeps that stall honest instead of expensive.
