# Pre-Conceptual Pattern Presentation — Findings

Research spike for MetaCoding-5wi. Companion documents:
- [Approach A — Side-by-side](./preconceptual-prototype-A.md)
- [Approach B — Contrast pair](./preconceptual-prototype-B.md)
- [Approach C — Structural skeleton](./preconceptual-prototype-C.md)

---

## The pattern chosen

**The correlated tool result re-injection.**

When an LLM requests a tool call, it emits a request object with a
correlation token (universally called `tool_call_id` or equivalent). After
execution, the framework constructs a result envelope that carries the *same
token*, stamps it with a distinct role or type label, and appends it to the
shared conversation history. The next LLM call reads that history and sees
the result as a peer message correlated to the request.

Why this pattern: it is real, ubiquitous (present in five different agent
frameworks with significant repo coverage), has no canonical name, and is
genuinely pre-conceptual — most developers think of it as "how tool calling
works" rather than as a *pattern* at all, because the OpenAI API mandates it
and most frameworks conform to the mandate. But the structural regularity
exists *beneath* the API contract: correlation token + role label + append.
It appears even in frameworks (letta) that can *generate* the correlation ID
themselves rather than inheriting it from the model.

**Why it has no name:** it doesn't appear in the Gang of Four, it isn't a
design pattern in any documented sense, and "tool call handling" names the
*mechanism*, not the *structural shape*. The shape is: two typed objects
share a reference to a common identifier, one is a request and one is a
reply, and the identifier is the only structural link between them.

---

## What worked in each approach

### Approach A — Side-by-side

**What worked:**
- The table of axes (what varies vs. constant) was the single most useful
  element. Before the table, the five code slices felt like "five ways to
  do the same thing." After the table, the reader sees *which* sameness
  matters. The `annotation` layer (the axis table) did more work than the
  code.
- Showing the full chain — execute → wrap → append → LLM sees — was useful
  context. Without it, the reader doesn't know what to look for in the code.
- The prose summary at the end ("The shared ID is the structural invariant")
  named the shape without naming the pattern. That felt right: it pointed
  without labeling.

**What didn't work:**
- Five code slices in sequence is long. By the third, the reader is
  pattern-matching on surface features ("oh, another tool_call_id"), not
  perceiving the deeper structure.
- The code slices are not well-aligned. The pydantic-ai slice looks
  structurally different (two-layer wrapping) even though it fits the same
  skeleton. Without the skeleton approach to normalize it, side-by-side
  comparison risks confusing variation with non-membership.

**Prevailing feeling:** "Yes, I see something in common" — but mediated by
the annotation table, not by the code itself. Without the table, the
approach is just a bag of code snippets with a vague sense of similarity.
The annotation is load-bearing.

---

### Approach B — Contrast pair

**What worked:**
- The contrast pair is the most *immediately evocative* approach. You read
  the ag2 slice, see `tool_call_id` threading through, then read the crewAI
  slice and feel the absence before you've been told there is an absence.
  The structured comparison table confirms what you just perceived.
- The near-miss (crewAI) was well-chosen. It does the functional equivalent
  (feeds the result back) and fails the structural test (no correlation
  token, no role separation). This forces the reader to articulate *why*
  it doesn't fit, which is the same cognitive act as understanding the
  pattern.
- The final framing ("does not do the structural thing") was hard to resist
  writing but also felt honest: it's naming a property, not a pattern.

**What didn't work:**
- Two slices is probably not enough to feel the pattern — you get the
  boundary but not the interior. The pair worked *with* the memory of the
  side-by-side examples. As a standalone, it might only show "these two
  things differ" without transmitting the pattern itself.
- The table at the end (`ag2 vs crewAI`) almost names the pattern as
  "correlated reply" — that felt like naming pressure. The temptation to
  name was strongest at this point in the writing.

**Prevailing feeling:** the most visceral "aha" moment. But it's an aha
about the *boundary*, not the *center*. This approach works better as a
supplement to the side-by-side than as a standalone.

---

### Approach C — Structural skeleton

**What worked:**
- The abstract skeleton (`CALL_REQUEST → TOOL_EXECUTOR → RESULT_ENVELOPE →
  CONVERSATION → LLM_CALL_N+1`) is *precise* in a way the code isn't. It
  says exactly what is common: four node types, four edge types, one shared
  field value.
- The "what does not vary" list is more useful than the "what varies" list.
  Six invariants stated plainly are legible in a way that five varied code
  slices aren't.
- The MetaCoding typed-edge translation at the end gave a sense of how
  this would look in the actual graph schema. That felt grounded.

**What didn't work:**
- The skeleton is drained of concreteness. After reading it, a developer
  familiar with the code might say "yes, obviously." A developer unfamiliar
  might say "I don't recognize this in the code I write." It abstracts away
  the very things that make each instance recognizable.
- The note about pydantic-ai's two-layer wrapping (`ToolReturnPart` inside
  `ModelRequest`) was necessary but broke the skeleton's apparent clarity.
  Real patterns are not perfectly clean, and the skeleton approach makes
  every exception feel like a complication of the theory.
- This approach is powerful for *confirming* a pattern after you've already
  perceived it, less good for *evoking* a pattern you haven't yet seen.

**Prevailing feeling:** precise but cool. The skeleton makes the pattern
legible to analysis but not to perception. It answers "what is this?" but
not "what does this feel like?"

---

## Recommended shape for `ctkr.unnamed_patterns` MCP tool output

Based on this spike, the output that best supports pre-conceptual perception
is a composition of approaches B and A, with C as optional metadata:

```typescript
interface UnnamedPatternResult {
  // Identity
  pattern_id: string;            // stable hash, not a name
  source_kind: "unnamed";
  min_support: number;           // how many repo instances back this
  repo_coverage: string[];       // which repos

  // Approach B first: the contrast pair
  // One strong exemplar + one near-miss that shares functional purpose
  // but fails the structural test.
  contrast_pair: {
    positive: CodeSlice;         // fits the pattern
    negative: CodeSlice;         // nearly fits; explain why it doesn't
    structural_difference: string;  // one sentence, not a name
  };

  // Approach A second: the exemplar set
  // 3-6 slices, with annotation axes
  exemplars: CodeSlice[];
  annotation_axes: AnnotationAxis[];  // what varies vs. constant

  // Approach C as metadata: the skeleton
  // Not shown by default; available for deep inspection
  skeleton?: {
    nodes: SkeletonNode[];       // typed roles (not concrete names)
    edges: SkeletonEdge[];       // typed relationships
    invariants: string[];        // what stays constant across all exemplars
    variations: string[];        // what legitimately varies
    metacoding_edge_schema: string;  // typed-edge translation
  };

  // Explicitly no label field.
  // If a label is wanted, that is Phase 3 Layer 3's job — not this tool.
  // Optionally: hints toward naming without committing.
  labeling_pressure?: string;    // e.g. "the word 'correlation' kept
                                 //  appearing in the contrast pair analysis"
}

interface CodeSlice {
  repo: string;
  file: string;
  start_line: number;
  end_line: number;
  content: string;               // the actual code
  annotations: string[];         // what to look at (sparse, not a label)
}

interface AnnotationAxis {
  axis: string;                  // e.g. "correlation token"
  verdict: "constant" | "varies" | "absent";
  notes?: string;
}
```

### Key design decisions

**Contrast pair first.** The contrast pair is the highest-leverage entry
point. A reader who understands the boundary already understands most of the
pattern. Put it before the full exemplar set.

**No label field.** The point of this tool is to surface patterns that
resist labeling. A `label: null` field is still a label slot — it invites
filling. Remove the field entirely. If naming is wanted, it's a separate
workflow (`ctkr.pattern_search` with an LLM labeling pass).

**`labeling_pressure` as an escape valve.** During analysis (including this
spike), names kept trying to form. "Correlated reply," "request-reply
correlation," "tool result envelope." These aren't the pattern; they're
symptoms of it. Capturing the pressure as a metadata note (without
committing to any of those names) preserves the observation without
foreclosing perception.

**Annotation axes, not prose.** The axis table from Approach A was more
useful than prose summaries. The output should carry structured axes, not
free-text descriptions.

**Skeleton as opt-in depth.** The skeleton is useful for Phase 2/3
integration (typed-edge graphs, functor discovery) but drains perceptual
concreteness. Make it available, not default.

---

## Open questions and concerns

**1. The annotation problem.** Every approach required annotations — the
axis table, the structural difference sentence, the "what to look at" hints.
Annotations are pre-conceptual acts of pointing. Who writes them? For the
prototype, I wrote them by hand. For the MCP tool, they'd need to come from
structural analysis (which invariants are truly invariant across all
exemplars) plus possibly a constrained LLM pass that points without naming.
The constraint "do not propose a name; describe what stays constant" is
probably achievable but untested.

**2. Near-miss selection is hard.** The crewAI contrast was obvious in this
case because ReAct style is well-understood and structurally different.
In general, selecting a good near-miss requires knowing the boundary of the
pattern — which is what the presentation is supposed to help the human
discover. This is circular. One partial solution: generate near-misses by
finding exemplars that share most of the skeleton edges but not all, ranked
by how many they share (high = good near-miss, low = just different).

**3. Named patterns that the field thinks are unnamed.** This particular
pattern (`tool_call_id` correlation) is half-named — the OpenAI API spec
describes the mechanism, and developers who have read the spec recognize it.
The pattern is pre-conceptual for developers who haven't internalized the
spec. The tool needs to handle this: some "unnamed" patterns are named in
a spec document somewhere, just not in the *design pattern* literature. The
distinction matters for whether L3 labeling is redundant or additive.

**4. The temptation to name was strongest at Approach C.** The skeleton
(`CALL_REQUEST → RESULT_ENVELOPE via shared token`) almost named itself:
"correlated-reply envelope pattern." This is a finding about the approach:
abstraction creates naming pressure. Showing structured skeletons to humans
will generate names faster than showing code. If the goal is pre-conceptual
presentation, skeletons are the most powerful but also the most
name-inducing approach. Handle with awareness.

**5. What "pre-conceptual" means in practice.** The spike clarified this:
pre-conceptual doesn't mean before perception — the exemplars do evoke
perception. It means before *verbal crystallization*: the human sees the
shape before any word is attached to it. The best presentation approaches
extend the gap between perception and naming. Approach B (contrast pair)
extended it longest: the reader had the "aha" feeling and then had to find
words for it. That's the target state.

---

## Status

Research spike, not production. Files created:
- `preconceptual-prototype-A.md` — side-by-side comparison
- `preconceptual-prototype-B.md` — contrast pair
- `preconceptual-prototype-C.md` — structural skeleton
- `preconceptual-prototype-findings.md` — this file

Not committed per task constraint.
