# MetaCoding — Vision

> *MetaCoding exists to truly grok code, programs, and the flows and shapes that make computers do things. To use category theory to extract the essence of knowledge — knowledge that often cannot be put into words, that does not yet have concepts, that may not be fully conceptualizable.*

This is the strategic layer. The design docs under [`design/`](./design/) say how; this says what for and why.

## The thesis

A codebase is not *like* a category — it **is** one.

- Symbols are objects.
- Typed edges (CALLS, IMPLEMENTS, IMPORTS, REFERENCES, EXTENDS, OVERRIDES, INJECTS, CONTAINS, ANNOTATES, TYPE_OF) are morphisms.
- Edge-path concatenation is composition.

A corpus of N codebases is a disjoint union of N categories, plus the inter-corpus edges (shared dependencies, ported subsystems, role analogies) that connect them. Once you take this seriously, the question changes from *"what does this code do?"* to *"what is the shape of what this code is?"* — and category theory turns out to have the right vocabulary for that question.

The deeper claim: there are essences in programs that cannot be cleanly named. They're patterns that haven't been written down, idioms a community has converged on without noticing, structural roles that don't map to any documented design pattern. They show up as **isomorphisms between sub-categories**: this Zig hot loop and that TypeScript stream pipeline are the same shape, even though no one would describe them with the same words. MetaCoding's job is to surface those shapes — to grok the code by reading its structure, not its prose.

## What "grokking" means here

Three concrete capabilities, in increasing depth:

1. **See the same role under different names.** `crewAI.Agent`, `autogen.ConversableAgent`, `mastra.Agent` should cluster — not because their names rhyme but because their hom-profiles match (Yoneda). The framework name is accidental; the role is essential.

2. **Find isomorphisms between categories.** Given two repos, discover the maximal structure-preserving map (functor) between them. That map *is* the explanation of how the two designs correspond — typed, audit-trail, exact. No prose required.

3. **Extract the essence — the colimit.** Given N repos solving similar problems, compute the minimal shared ontology they all instantiate. That's the *abstract pattern* the field has converged on, recovered from behavior rather than declared by anyone.

These are not metaphors for what we want. They are the **constructions** we want to compute.

## Why this, why now

Vector RAG and FTS handle "find me the chunk that mentions X." MetaCoding's existing graph + FTS surface handles "find me the symbols related to X." Neither answers: *what is X categorically? What role does it play in the corpus? What's its essence?* That gap is what CTKR fills.

There is also a practical lever: foundation models can label structural discoveries with natural language. Layer 1 (cheap structural mining) + Layer 2 (categorical machinery) + Layer 3 (LLM enrichment) gives us an emergent pattern library that is **both** rigorously grounded **and** legible to humans. Structure first, meaning second.

## The ladder

Four phases, each independently shippable, each upgrading what came before. Details in [`design/ct-pipeline.md`](./design/ct-pipeline.md).

- **Phase 1 — Make L1 queryable.** Expose the already-built mining artifacts (motifs, embeddings, centrality, shape signatures, learned patterns) through typed MCP tools. Immediate utility, no new math.
- **Phase 2 — Layer 2: categorical machinery.** Hom-profile computation, functor discovery, colimit construction, operad recovery. This is where MetaCoding becomes what its name claims.
- **Phase 3 — Essence extraction.** L2 finds the shapes; L3 names them. Patterns that don't yet have words get them. Patterns that already have words (Factory, Observer) get confirmed structurally. New patterns surface for the first time.
- **Phase 4 — Infrastructure for scale.** Multi-tier embeddings with unified KNN, incremental index maintenance, provenance + immutability, worktree-aware reads. Makes the system usable continuously rather than as a one-shot batch.

## What this is not

- **Not a code search engine.** Those exist and are good at what they do.
- **Not a documentation generator.** Documentation is the *output* of grokking, not the goal.
- **Not a pattern-detection tool that matches against a hardcoded list of Design Patterns.** No top-down ontology. The patterns are *discovered*, not *recognized*.
- **Not an LLM wrapper.** LLMs label what structural analysis finds. They don't drive the analysis.

## Related projects

MetaCoding is part of a small constellation:

- **[Dreamball](https://github.com/worldtree/Dreamball)** — signed, evolvable, aspect-oriented containers (`look`/`feel`/`act`). Memory Palace is its composed-application archiform. CTKR discoveries (patterns, functor maps, essence extractions) are natural Memory Palace inscriptions.
- **Orchestrators / harness-bench-a** — the self-evolving harness. Uses MetaCoding's FTS5 corpus for Kan-lift sensing; its evolution loop generates iterations and reflections that MetaCoding can index as another corpus member. MetaCoding's job is understanding code; the harness's job is evolving code.

The boundary: MetaCoding owns code understanding. Orchestrators owns evolution-loop state. Dreamball owns the container protocol. They compose; they do not merge.

## Open horizons

Things this vision implies but does not yet prescribe:

- **Time as a dimension.** Every edge has a git-history birth/death. Persistent homology over the temporal filtration reveals architectural drift, refactoring waves, deprecation patterns. The schema can carry it; the analyses come later.
- **Cross-language essence.** Does the categorical structure of an idea survive translation between languages? The Yoneda hypothesis says yes — same hom-profile, same role, regardless of syntax. Empirical question.
- **Closed refinement loops.** Once L3 labels feed back as priors for L2 functor search, the labeling loop becomes self-improving. The mathematics of that fixed point are interesting.
- **Pre-conceptual knowledge.** The frontier: can we surface essences that have no natural-language name yet, present them in a way humans can perceive (visualizations, exemplars, contrast pairs), and let *conceptualization* happen on the human side? This is the deepest version of "grok."

## Status

The bones exist: the indexed code-graph (Layer 0), the L1 mining pipeline (motifs, embeddings, persistent homology, centrality), and an L3 motif-labeling loop. What's missing is the categorical machinery (Layer 2), an MCP surface for the CTKR artifacts, and the incremental infrastructure that lets the whole thing run continuously.

That's the work. The phased plan in [`design/ct-pipeline.md`](./design/ct-pipeline.md) lays it out.
