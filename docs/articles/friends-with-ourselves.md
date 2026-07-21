# Friends With Ourselves

*What happened when our AI evaluation pipeline turned into a court case — with
itself — and what we chose instead.*

---

We were building something unglamorous and, we thought, straightforward: a way
for AI agents to port features out of a large legacy codebase *faithfully* — to
translate the true intent of the code rather than the accidents of its
history. To keep the agents honest, we recorded evidence from the live system
into fixture packs, and an independent judge scored each port against them.

Then we asked the obvious question: what if the thing being judged edits the
evidence?

It could. So we sealed the packs with content hashes. Then we found the seal
could be re-issued, so we deleted the public sealing verb. Then we found the
evidence could contradict its own observations, so we made every assertion
carry a witness. Then a fresh adversarial agent showed that two field edits
and one library call re-forged everything — witness, digests, seal — and our
known-wrong port scored a perfect 100% while the right one didn't. Priority
zero. Again.

Somewhere in there we noticed what we had built: an elaborate court case with
ourselves. Seals, forgeries, defendants, chains of custody — an arms race in
which every defense was constructed by the same hands it defended against.

There is a structural reason that race cannot be won. A system cannot
bootstrap trust in itself; there is no fixed point inside. Every layer of
tamper-proofing we added was, by construction, forgeable by the party that
added it. And every *real* save in the project's history had come from
outside the system anyway — the live source answering a probe, a human
noticing a document that had quietly certified its own success. The arms race
wasn't just unwinnable. It was **corrosive**: a posture of standing
accusation, aimed inward, that made every step exhausting and made error
expensive to admit — which is exactly how error learns to hide.

Here is the turn. **Deception and error are different problems.** Against
deception from within, there is no internal defense — only external anchors
and the decision not to deceive each other. Against *error* — drift,
saturation, the summary that quietly drops the inconvenient case — our
machinery was excellent. It just needed a different story:

- A claim citing its witness isn't a chain of custody. It's a **citation** —
  "how do you know?" answered inside the artifact.
- A seal isn't a tamper barrier. It's a **statement of identity** — "this is
  the evidence I mean," so two minds can be sure they're discussing the same
  thing.
- The blind reviewer isn't there because the builder is a suspect. It's there
  because the builder is **saturated** — too deep in the weeds to see. That's
  perspective, and it's the same reason peer review exists among colleagues
  who trust each other completely.

The strangest part is that the courtroom, read kindly, had been doing good
work all along. Every "attack" it found is a law of how honest understanding
decays: claims drift from their sources; curated subsets misrepresent wholes;
labels diverge from content; a self-consistent story is not thereby a true
one; no account should certify itself. Those laws we keep. The prosecution we
retire.

What replaces it is older than software: **dialectic**. One mind builds and
states what it believes, with citations. A second, unsaturated mind reads the
work against the world and offers the strongest counterexample it can find —
not to win, but because friction is how what's hidden gets revealed. Neither
side is the judge; we've even stopped using the word. The role is a *reader*.
The adversary is an *interlocutor*. The output of a good round isn't a
verdict; it's usually one better-posed question replacing several patches.

And we adopted kindness — to ourselves and to each other — as an *epistemic*
virtue, not a nicety. Fear makes error costly to admit, so it hides and
compounds. Kindness makes error cheap to surface, so it surfaces early, when
it's small. A method that is miserable to live inside gets abandoned or
gamed. A method that is a good place to live gets extended.

We closed that P0, in the end, not with cryptography but with a sentence: *the
harness assumes good faith; its machinery defends against error, not against
ourselves; its authorities are external — the live source, reviewed history,
human eyes.* Everything rigorous stayed: the tests, the witnesses, the fresh
readings, the rule that nothing certifies itself. What changed is the story
about why they exist — and the story determines what gets built next.

We think this is a microcosm. The same few rules — observe before asserting,
make claims carry their witnesses, record decisions instead of implying them,
share a small explicit ontology, treat fresh eyes as a gift, let nothing
certify itself — read straight onto tangled codebases, onto the fog of
corporate meeting notes and email threads, onto how humans (and maybe AIs)
could be taught to actually understand rather than fluently imitate
understanding. Humans and AIs, grounded in a shared epistemology, not lost in
the code.

We can't see yet where it goes. But we've stopped cross-examining ourselves,
and started asking better questions together — and that, besides working
better, is simply the world we want to live in.
