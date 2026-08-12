# Enforceability: what makes a gate real here, and what to do with the ones that aren't

**Status:** observed, 2026-08-12. Written after two gates were built in three days and
neither was wired to anything. Duke: *"Either get rid of them or wire them properly.
Or maybe they inform our philosophy — but we're looking for things that are
enforceable."* This is the attempt to answer that from the record rather than from
taste.

## The measurement that starts it

**There is no CI and there are no git *repo* hooks. In either repo.**

**Correction, same day:** the first draft of this document stopped there and concluded
the surface was three things. It missed one, and it is the most valuable one — Claude
Code's own `PreToolUse`/`PostToolUse` hooks in `.claude/settings.json`. Those *do*
execute, unconditionally, before every matching tool call, for the main session and
for every subagent. A process-observing agent caught the omission and proposed the
first one: a refusal of `cd <path> && <interpreter>`, which is the only failure this
week with a purely syntactic signature and would have prevented `hy6.52` outright.
It is now live and proven to fire. **Tool hooks are the strongest surface available
here — stronger than the import path, because an agent cannot route around them.**

```
.github/workflows        — absent, MetaCoding and farmos-port
.git/hooks               — samples only, both repos
husky / lefthook         — absent
```

So the execution surface of this project is exactly four things:

1. what a human or an agent types,
2. `bun test` and `bun run smoke`, which are typed often enough to count as habit,
3. **the import path** — code you cannot avoid running, because it is how the job
   gets done at all,
4. **Claude Code tool hooks** (`.claude/settings.json`) — see the correction above.

Nothing else runs. Ever. A "gate" outside those four is a document with an exit
code.

## What has actually enforced something

Four mechanisms in this project have demonstrably refused real work. All four sit on
one of those surfaces, and two of them sit on the import path:

| mechanism | surface | what it caught |
|---|---|---|
| `tools/ledger.py` raising on an ungated probe | **import path** — a build cannot probe without it | an under-declared preflight, live, at S0 (`hy6.28`) |
| `test/kernel-pin.test.ts` | **`bun test`** | a `file:` dependency silently resolving to a different kernel |
| `discriminate()` throwing | **import path** — the verb you reach for | a refused pair leaving its test green (`3ad`) |
| the `cd`+interpreter refusal | **tool hook** — before every Bash call, main session and subagents alike | proven to fire on the shape that caused `hy6.52`; an agent cannot route around it |

And the counter-examples, both built deliberately, both correct, both never run:

| mechanism | intended surface | status |
|---|---|---|
| `elenchus.py --require-current` | "wave-close sealing" | **nothing calls it** (`3oe`) |
| `verdict_currency.py` | "wave-close sealing" | **nothing calls it** (`hy6.54`) |

The shared cause is worth stating plainly, because both were designed by someone who
had just finished writing down the lesson they were about to break: **the call site
they were told to hook does not exist.** There is no wave-close command. Sealing a
wave is a human act with no code path, so "make it a precondition of sealing" was
never implementable — it only sounded implementable.

## The rule this gives us

> A gate is real if it lies on a path someone must traverse to do the work, or
> inside a command they already type. A gate that lives beside the work is a
> document, whatever its exit code.

`oracle_preflight.py` is the proof in both directions. As a standalone script it was
run by one build in five. Moved onto the import path — `ledger.py` calls it and
raises — it became unavoidable, and immediately caught a live under-declaration
nobody had noticed. **The same code. The difference was entirely where it sat.**

## The three dispositions

Every proposed gate gets one of these, chosen deliberately and recorded:

**1. Put it on the path.** Best. Make it something the job cannot be done without.
The test: can a competent, hurried person do the work and skip this? If yes, it is
not on the path.

**2. Put it in `bun test`.** Good, and the only option when there is no natural
import path — which is the case for anything that inspects the *workspace as a
whole* rather than a single call. Cost: it must be green essentially always, or it
gets deleted. See the ratchet below.

**3. Admit it is philosophy, and delete the executable pretence.** Legitimate, and
under-used. Some things genuinely cannot be mechanized: whether an Elenchus is
*needed*, whether an interpretation is honest, whether a question is the right one.
For these, the executable form is worse than useless — it implies an enforcement
that isn't there, and it decays into a counter to satisfy. Write the philosophy
down, keep the flags advisory, and stop pretending.

The `elenchus.py` flags already do this correctly and on purpose: they exit 0
whatever they find, and that property is mutation-tested. What is *not* correct is
`--require-current`, which pretends to gate a step that does not exist in code.

## The ratchet, for gates that would be permanently red

A gate that fails today over real, accepted debt cannot be disposition 2 — a
permanently red test is deleted within the week, and is exactly as useful as one
that never fires. The fix is not to weaken the check; it is to change what it
asserts:

> Record today's failing set as a baseline, with a reason per entry. The check
> fails when the set **grows**, or when an entry's reason goes stale.

That is enforceable, honest about the debt, and it refuses the actual failure mode —
silent growth. `verdict_currency` is the immediate candidate: 12 identity builds
currently lack a verdict, all of them for known reasons, and what nobody should be
able to do is add a thirteenth without saying why.

## How this can still be faked

Asked honestly, because the document that skips this section is the one that gets
believed:

- **`bun test` can be run selectively.** `bun test src/testkit/` does not run the
  ratchet. Only the habitual full run does, and habits are not mechanisms.
- **A baseline can be rubber-stamped.** Adding an entry with the reason "known" is
  syntactically fine and epistemically empty. The reason field is only as good as
  the review of the diff that adds it.
- **Disposition 3 is an escape hatch.** "It's philosophy" is available to anyone who
  doesn't want to do the wiring. The check on it: philosophy is for things that
  *cannot* be mechanized, not things that are *inconvenient* to mechanize — and the
  burden is on the person claiming it.
- **None of this survives without CI.** Every surface here depends on a person or
  agent typing a command. The honest summary is that this project has no
  enforcement, only strong habits with good ergonomics. Adding CI would change the
  analysis more than any mechanism in this document.

## What this says about the two unwired gates

- `verdict_currency.py` → **disposition 2, as a ratchet.** It inspects the workspace
  as a whole, so it has no import path; `bun test` is the only surface it can sit on.
- `elenchus.py --require-current` → **disposition 3.** The irreversible step it
  guards is a human decision with no code path, and the flags already carry the
  advisory role correctly. Recommend deleting `--require-current` rather than
  leaving a gate that cannot fire, and saying in the charter that the Elenchus is
  convened consciously — which is what Duke already called it: a sadhana, not a
  trigger.

Either outcome is fine. What is not fine is a third gate next week whose commit
message says it will be wired as a precondition of wave-close sealing.
