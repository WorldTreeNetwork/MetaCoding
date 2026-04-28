# Paper: AST-Derived Graphs vs LLM-Extracted KGs for Code RAG

**Source:** https://arxiv.org/html/2601.08773v1

## Summary

Benchmarks three retrieval strategies for code-RAG over three Java codebases (Shopizer, ThingsBoard, OpenMRS):

1. **No-Graph** — vanilla vector RAG, 1000-char chunks, top-k=10.
2. **LLM-KB** — at index time, batch files into an LLM and ask it to emit a JSON dependency graph.
3. **DKB (proposed)** — Tree-sitter parses every Java file; two-pass extraction emits typed edges (`injects`, `extends`, `implements`). At query time, Algorithm 1 traverses bidirectionally (successors + predecessors) plus an **interface-consumer expansion**: if a retrieved class implements `IFoo`, additionally pull every consumer of `IFoo`.

15 hand-written multi-hop architectural questions per repo, graded Correct/Partial/Incorrect.

## Headline numbers

- **Correctness (45 questions total):** DKB 43 correct, LLM-KB 38, No-Graph 31.
- **End-to-end cost (Shopizer, normalized to No-Graph):** No-Graph 1.0×, DKB 2.25×, LLM-KB 19.75×.
- **Cost on OpenMRS+ThingsBoard combined:** No-Graph 1.0×, DKB 2.13×, LLM-KB 45.64×.
- **Indexing reliability (Shopizer):** LLM-KB silently dropped 377/1210 files; per-file success 0.688. DKB chunk coverage 0.902 vs 1.0 baseline.
- **Indexing time (Shopizer):** DKB 2.81s graph build. LLM-KB 200.14s.

## Critique

- **Tiny benchmark, single grader.** 15 questions × 3 repos × 1 annotator. Headline correctness deltas (43 vs 38 vs 31) are within the noise of who wrote the questions and who graded them.
- **Single run, no variance bars on LLM-KB.** LLM-KB is the stochastic arm; one trial. The "377 SKIPPED files" is exactly the kind of metric that moves run-to-run.
- **Unfair LLM-KB construction.** Prompting an LLM to do what `tree-sitter` does natively. Stronger baseline: LLM-augmented-on-top-of-AST (AST for structure, LLM for semantic edges like string DI).
- **Java + Spring is easy mode.** Spring DI relationships are syntactically explicit (annotations, constructor params, interface types). The method's edge will narrow on Python/JS/Ruby.
- **No comparison to engineering state of the art.** Language servers, SCIP, IntelliJ index, Sourcegraph — these have been doing typed code graphs for a decade. The paper frames this as novel against an LLM strawman.
- **Questions selected to favor the method.** "Multi-hop tracing, upstream discovery, interface expansion" — exactly what Algorithm 1 was designed for. Missing: refactoring, runtime behavior, data-flow questions.
- **Coverage caveat buried.** DKB drops ~10% of code that doesn't AST-map cleanly.

## What's potent

The actual insight is small but correct: **for structured artifacts, deterministic extraction dominates probabilistic extraction on cost, latency, and recall — reach for an LLM only where structure runs out.** The interface-consumer expansion trick is the cleverest piece — it's the specific thing pure vector search can't do (controller and service are textually disjoint; only the type system links them), and it's cheap once the graph exists.

The cost numbers are more persuasive than the correctness numbers. ~2× vs 20–45× is a real engineering argument.

## Implications for our build

- The paper's core thesis (deterministic > probabilistic for structural code edges) is the design principle.
- We can do strictly better than the paper by using **resolved-symbol indexers (SCIP/LSP)** instead of raw Tree-sitter — closes the 10% chunk-coverage gap and handles generics, overrides, cross-module refs.
- The interface-consumer trick is a one-line Cypher query in our graph: `MATCH (caller)-[:DEPENDS_ON]->(iface)<-[:IMPLEMENTS]-(impl) RETURN caller`. Worth exposing as a first-class MCP tool.
- The string-DI / metaprogramming / reflection blind spot is real and isn't fixed by SCIP either. That's the FTS lane.
