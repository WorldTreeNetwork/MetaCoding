"""Semantic-mining pass — propose ranked fixture CANDIDATES (bead MetaCoding-9h5.10).

The 9h5.8 signal-attribution matrix settled the golden path: the lever for the
farmOS fan-out is *fixture coverage of the non-obvious semantics*, not more
categorical machinery. Every non-obvious rule needs a fixture that exercises it —
``ce015be4`` group-reassignment-latest-wins proved this by being the ONE
discriminator among ten hardening fixtures. This module inverts the pipeline's
role: instead of writing briefs a builder ignores, it uses the deterministic
layers to FIND the non-obvious semantics a port must get right — the ones method
names cannot telegraph — and proposes them as ranked fixture candidates for
live-oracle observation.

Three mining lanes, fused:

1. **CM lane** (``mine_cm_lane``) — intent-CM seeds + strong-model adjudications
   (constraints / workflows / permissions; the UniqueBirthLog pattern). Reuses
   :mod:`ctkr.intent_cm`; adjudication defaults to gpt-5.6-luna, heuristic
   prescreen OFF (the adopted 9h5.14 default).

2. **Graph lane** (``mine_graph_lane``, LM-FREE) — mines the scoped code graph for
   semantic-bearing structures (validation constraints, hook implementations,
   workflow/state configs, Views filters, and — where the export carries them —
   the vju READS_FIELD/WRITES_FIELD field-flow edges crossing module
   boundaries). Ranked by **reach**: how many members reference the element.

3. **Source-read lane** (``mine_source_read_lane``, LLM) — the 9h5.8 pure-LLM cell
   recovered latest-wins from raw source when fixtures missed it. Give a model
   (gpt-5.6-terra via :class:`~ctkr.llm.LLMClient`) the relevant module source and
   ask for behavioral rules a re-implementer could plausibly get wrong, each with
   a ``file:line`` citation — structured pydantic output with the ``repair=`` retry.

The lanes are fused by semantic topic (``fuse_and_rank``): a candidate surfaced by
more than one lane is the strong signal and is boosted. Output is
``fixture_candidates.jsonl`` — one :class:`FixtureCandidate` per line. **No
candidate becomes a fixture without live-oracle observation** (Phase-2
discipline); this pass only PROPOSES.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import networkx as nx
from blake3 import blake3
from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Candidate schema                                                            #
# --------------------------------------------------------------------------- #
LANE_CM = "cm"
LANE_GRAPH = "graph"
LANE_SOURCE_READ = "source-read"


class ScenarioSketch(BaseModel):
    """A given/when/then DRAFT in domain terms — a sketch, not a runnable fixture.

    Deliberately natural-language: a candidate is a *proposal* for a scenario a
    port could get wrong; it is only translated into the runnable glossary DSL
    (:mod:`ctkr.oracle.fixtures`) once a human/recorder confirms it against the
    live oracle. The sketch orients that translation.
    """

    model_config = ConfigDict(extra="forbid")

    given: list[str] = Field(default_factory=list)
    when: list[str] = Field(default_factory=list)
    then: list[str] = Field(default_factory=list)


class FixtureCandidate(BaseModel):
    """One proposed fixture — a non-obvious semantic a port must get right."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = ""  # content hash over the semantic body; filled by with_id()
    title: str
    feature: str = ""  # glossary feature / owning module
    scenario: ScenarioSketch = Field(default_factory=ScenarioSketch)
    why_non_obvious: str = ""
    lanes: list[str] = Field(default_factory=list)  # {cm, graph, source-read}
    source_citation: str = ""  # file:line the semantic rests on
    rank_score: float = 0.0
    # provenance / detail (not hashed)
    topic: str = ""  # canonical semantic topic (fusion key)
    element_id: str = ""  # graph node id / cm element_id where applicable
    reach: int = 0  # graph lane: distinct referrers of the element
    lane_detail: dict[str, Any] = Field(default_factory=dict)

    def _body_for_hash(self) -> dict[str, Any]:
        return {
            "title": self.title.strip().lower(),
            "topic": self.topic,
            "citation": self.source_citation,
        }

    def content_id(self) -> str:
        canon = json.dumps(self._body_for_hash(), sort_keys=True, ensure_ascii=False)
        return "fc:" + blake3(canon.encode("utf-8")).hexdigest()[:20]

    def with_id(self) -> FixtureCandidate:
        return self.model_copy(update={"candidate_id": self.content_id()})


# --------------------------------------------------------------------------- #
# Semantic topic lexicon — the fusion key + relevance filter                  #
# --------------------------------------------------------------------------- #
# Canonical topic -> the regex signals (over lowercased text) that map to it.
# A candidate's `topic` is the first canonical topic whose signals it matches.
# Two candidates from different lanes that share a topic are FUSED (the strong
# multi-lane signal). Order matters — most specific first.
_TOPIC_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("group-membership-latest-wins",
     ("latest-wins", "latest wins", "most recent assignment", "reassign", "revoke",
      "group membership", "group assignment", "is_group_assignment", "groupmembership",
      "membership")),
    ("uniqueness-constraint",
     ("unique", "uniqueness", "one .* per", "duplicate", "de-duplicat", "birth log")),
    ("pending-contributes",
     ("pending", "draft status", "not yet done", "unrealized")),
    ("cross-kind-aggregation",
     ("across all", "all log kinds", "cross-kind", "regardless of kind", "any kind")),
    ("measure-unit-filter",
     ("measure", "unit", "mismatch", "different unit", "quantity type")),
    ("yield-aggregation",
     ("yield", "sum of", "total of", "aggregat", "fold", "reduce over")),
    ("log-status-lifecycle",
     ("status", "lifecycle", "transition", "pending", "done", "complete")),
    ("archival-retains-history",
     ("archiv", "retire", "inactive", "retain", "history preserved")),
    ("log-count-isolation",
     ("count", "isolate", "per kind", "by kind")),
    ("multi-asset-attribution",
     ("multiple assets", "two assets", "shared", "attribut", "against .* assets")),
    ("views-filter-semantics",
     ("views filter", "views data", "query alter", "exposed filter", "view")),
    ("field-flow",
     ("reads_field", "writes_field", "field write", "field read", "computed field",
      "field item list")),
)


CANONICAL_TOPICS: frozenset[str] = frozenset(t for t, _ in _TOPIC_SIGNALS)


def classify_topic(text: str) -> str:
    """Map free text to its canonical semantic topic (fusion key), or "" if none."""
    low = text.lower()
    for topic, signals in _TOPIC_SIGNALS:
        for sig in signals:
            if re.search(sig, low):
                return topic
    return ""


# --------------------------------------------------------------------------- #
# Lane 2 — graph mining (LM-free, deterministic, hermetic-testable)           #
# --------------------------------------------------------------------------- #
_REACH_EDGE_KINDS: frozenset[str] = frozenset(
    {"REFERENCES", "CALLS", "EXTENDS", "IMPLEMENTS", "OVERRIDES", "CONSTRUCTS", "INJECTS"}
)
_FIELD_FLOW_KINDS: frozenset[str] = frozenset({"READS_FIELD", "WRITES_FIELD"})

# Graph element category -> (path/name signals, why-non-obvious template, scenario
# sketch template). Signals are matched (case-insensitive) against the node's file
# path and short name. The FIRST matching category wins; order = most specific.
_GRAPH_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("validation-constraint",
     ("constraint", "validator", "/validation/")),
    ("membership-logic",
     ("membership", "groupmembership")),
    ("hook-implementation",
     ("/hook/", "hooks.php", "hooks")),
    ("views-filter",
     ("views", "viewsdata", "queryalter")),
    ("workflow-state-config",
     (".type.", "log.type", "quantity.type", "workflow", "/config/install/")),
    ("field-computed",
     ("itemlist", "computed", "fielditemlist")),
)

_TEST_SIGNALS: tuple[str, ...] = ("/test/", "/tests/", "test.php", "testbase", "/kernel/")


def _node_category(file_path: str, short_name: str) -> str:
    hay = f"{file_path}\n{short_name}".lower()
    for cat, signals in _GRAPH_CATEGORIES:
        if any(s in hay for s in signals):
            return cat
    return "domain-logic"


def _is_test_node(file_path: str, short_name: str) -> bool:
    low = f"{file_path} {short_name}".lower()
    return any(s in low for s in _TEST_SIGNALS)


_GRAPH_SKETCH: dict[str, tuple[str, ScenarioSketch]] = {
    "validation-constraint": (
        "A server-side validation constraint enforces an invariant at write time. A "
        "port over an append-only/eventual store cannot enforce it globally and must "
        "pick an explicit resolution — the semantic no method name conveys.",
        ScenarioSketch(
            given=["two records that would each independently satisfy creation"],
            when=["both are created (concurrently / offline) so both violate the constraint"],
            then=["the system's convergence behavior for the constraint is observed and asserted"],
        ),
    ),
    "membership-logic": (
        "Membership is derived from the LATEST assignment event, not the set of all "
        "assignments — a reassignment REVOKES the prior membership. An additive "
        '"is there any assignment" read (the natural port) gets this wrong.',
        ScenarioSketch(
            given=["an asset A and two groups G1, G2"],
            when=["A is assigned to G1, then re-assigned to G2"],
            then=["A is a member of G2 only; membership in G1 is revoked (latest-wins)"],
        ),
    ),
    "hook-implementation": (
        "A hook fires a side effect on an entity lifecycle event. A re-implementer who "
        "models only the primary write can miss the derived state the hook maintains.",
        ScenarioSketch(
            given=["the entity state the hook keys on"],
            when=["the lifecycle event that triggers the hook occurs"],
            then=["the hook's derived side effect is observable at the value boundary"],
        ),
    ),
    "views-filter": (
        "A Views query/filter shapes what a read returns (visibility, ordering, "
        "exclusion). The filter semantics are invisible from the read's method name.",
        ScenarioSketch(
            given=["records that the filter would include and exclude"],
            when=["the filtered read is taken"],
            then=["only the included records are returned, in the filter's order"],
        ),
    ),
    "workflow-state-config": (
        "A config declares a state machine / bundle behavior (statuses, defaults). The "
        "allowed transitions and default status are behavioral rules a port must match.",
        ScenarioSketch(
            given=["an entity of the configured type"],
            when=["it is created / transitioned per the configured workflow"],
            then=["its status follows the declared default and allowed transitions"],
        ),
    ),
    "field-computed": (
        "A computed field list derives its value from other state rather than storing "
        "it. A port that stores it as a plain field diverges when the source state changes.",
        ScenarioSketch(
            given=["the underlying state the computed field derives from"],
            when=["that state changes"],
            then=["the computed field reflects the change without a separate write"],
        ),
    ),
    "domain-logic": (
        "A high-reach domain class concentrates behavior many members depend on; its "
        "non-obvious rules are load-bearing for a faithful port.",
        ScenarioSketch(
            given=["the domain state this class operates on"],
            when=["its primary operation is exercised"],
            then=["the value it computes / maintains is observed at the boundary"],
        ),
    ),
}


def _in_scope(file_path: str, prefixes: Sequence[str]) -> bool:
    if not prefixes:
        return True
    low = file_path.lower()
    return any(p.lower() in low for p in prefixes)


def _module_of(file_path: str) -> str:
    """A coarse owning-module label from a farmOS-style path (…/modules/<area>/<mod>/…)."""
    parts = file_path.split("/")
    if "modules" in parts:
        i = parts.index("modules")
        tail = parts[i + 1 : i + 3]
        return "/".join(tail) if tail else file_path
    return parts[0] if parts else file_path


def compute_reach(g: nx.MultiDiGraph, node_ids: Iterable[str]) -> dict[str, int]:
    """Reach = number of DISTINCT referrer nodes pointing at each node via a
    semantic-bearing edge (REFERENCES/CALLS/EXTENDS/IMPLEMENTS/OVERRIDES/
    CONSTRUCTS/INJECTS). Counts referrers anywhere in the graph — "how many
    members reference the element" (bead §graph lane), not just scoped ones."""
    wanted = set(node_ids)
    reach: dict[str, set[str]] = defaultdict(set)
    for src, dst, k in g.edges(keys=True):
        if dst in wanted and k in _REACH_EDGE_KINDS:
            reach[dst].add(src)
    return {n: len(reach.get(n, ())) for n in wanted}


def mine_field_flow_edges(
    g: nx.MultiDiGraph, prefixes: Sequence[str]
) -> list[dict[str, Any]]:
    """The vju READS_FIELD/WRITES_FIELD field-flow lane: writes whose source and
    target field cross a module boundary (a data-flow the port must preserve).

    Present only when the export carries the tree-sitter heuristic edges (bead
    MetaCoding-e54); the scip-php export has zero — this returns [] and the graph
    lane degrades gracefully to the structural categories."""
    out: list[dict[str, Any]] = []
    for src, dst, k in g.edges(keys=True):
        if k not in _FIELD_FLOW_KINDS:
            continue
        s_attr = g.nodes.get(src, {})
        d_attr = g.nodes.get(dst, {})
        s_file = str(s_attr.get("file", ""))
        d_file = str(d_attr.get("file", ""))
        if not (_in_scope(s_file, prefixes) or _in_scope(d_file, prefixes)):
            continue
        if _module_of(s_file) == _module_of(d_file):
            continue  # same-module writes are not the cross-boundary signal
        out.append({
            "kind": k, "src": src, "dst": dst,
            "src_file": s_file, "dst_file": d_file,
            "src_name": s_attr.get("short_name") or s_attr.get("qualified_name"),
            "dst_name": d_attr.get("short_name") or d_attr.get("qualified_name"),
        })
    return out


def mine_graph_lane(
    g: nx.MultiDiGraph,
    *,
    subsystem_prefixes: Sequence[str],
    min_reach: int = 1,
    max_candidates: int = 40,
    include_tests: bool = False,
) -> list[FixtureCandidate]:
    """Mine the scoped graph for semantic-bearing structures, ranked by reach.

    Considers scoped ``class``/``interface`` nodes (the behavior carriers) plus
    ``file`` nodes for workflow/state config (``*.type.*`` yml). Each becomes a
    candidate tagged with its semantic category and its reach; the scenario sketch
    is category-templated. LM-FREE and deterministic — the same graph yields the
    same candidates in the same order.
    """
    # 1. Collect scoped structural nodes.
    struct_ids: list[str] = []
    config_nodes: list[tuple[str, dict]] = []
    for n, d in g.nodes(data=True):
        file_path = str(d.get("file", "") or "")
        if not _in_scope(file_path, subsystem_prefixes):
            continue
        short = str(d.get("short_name") or d.get("qualified_name") or "")
        if not include_tests and _is_test_node(file_path, short):
            continue
        kind = d.get("kind")
        if kind in ("class", "interface"):
            struct_ids.append(n)
        elif kind == "file" and (".type." in file_path or "/config/install/" in file_path):
            config_nodes.append((n, d))

    reach = compute_reach(g, struct_ids)

    cands: list[FixtureCandidate] = []
    for n in struct_ids:
        d = g.nodes[n]
        file_path = str(d.get("file", "") or "")
        short = str(d.get("short_name") or d.get("qualified_name") or "")
        r = reach.get(n, 0)
        cat = _node_category(file_path, short)
        # A high-reach domain class is worth surfacing even without a keyword;
        # low-reach uncategorised classes are noise.
        if r < min_reach and cat == "domain-logic":
            continue
        why, sketch = _GRAPH_SKETCH[cat]
        line = d.get("line") or 0
        citation = f"{file_path}:{line}"
        title = f"[{cat}] {short}"
        # Classify from the ELEMENT identity (name + path), never the generic
        # why-template — otherwise a template phrase ("lifecycle") would assign a
        # spurious canonical topic and wrongly fuse distinct elements.
        topic = classify_topic(f"{short} {file_path}") or cat
        cands.append(FixtureCandidate(
            title=title, feature=_module_of(file_path), scenario=sketch,
            why_non_obvious=why, lanes=[LANE_GRAPH], source_citation=citation,
            topic=topic, element_id=n, reach=r,
            lane_detail={"graph": {"category": cat, "short_name": short, "reach": r}},
        ).with_id())

    # Workflow/state config (file nodes) — reach not meaningful, fixed small weight.
    for n, d in config_nodes:
        file_path = str(d.get("file", "") or "")
        why, sketch = _GRAPH_SKETCH["workflow-state-config"]
        stem = Path(file_path).name
        cands.append(FixtureCandidate(
            title=f"[workflow-state-config] {stem}",
            feature=_module_of(file_path), scenario=sketch, why_non_obvious=why,
            lanes=[LANE_GRAPH], source_citation=f"{file_path}:0",
            topic="workflow-state-config", element_id=n, reach=0,
            lane_detail={"graph": {"category": "workflow-state-config", "short_name": stem}},
        ).with_id())

    # Field-flow (vju) edges, when present.
    for e in mine_field_flow_edges(g, subsystem_prefixes):
        why, sketch = _GRAPH_SKETCH["field-computed"]
        cands.append(FixtureCandidate(
            title=f"[field-flow] {e['src_name']} {e['kind']} {e['dst_name']}",
            feature=_module_of(e["src_file"]), scenario=sketch,
            why_non_obvious=(
                "A field write crosses a module boundary (vju "
                f"{e['kind']}): {e['src_name']} writes {e['dst_name']}. A port that "
                "keeps the modules independent loses this coupling."),
            lanes=[LANE_GRAPH], source_citation=f"{e['src_file']}:0",
            topic="field-flow", element_id=e["src"], reach=0,
            lane_detail={"graph": {"category": "field-flow", "edge": e}},
        ).with_id())

    # Rank graph-internal by reach so the cap keeps the highest-reach elements.
    cands.sort(key=lambda c: (-c.reach, c.source_citation))
    return cands[:max_candidates]


# --------------------------------------------------------------------------- #
# Lane 1 — CM mining (reuse intent_cm; adjudicate with gpt-5.6-luna)          #
# --------------------------------------------------------------------------- #
_CM_SCENARIO: dict[str, ScenarioSketch] = {
    "unique-constraint": ScenarioSketch(
        given=["two records that each satisfy a server-side uniqueness invariant in isolation"],
        when=["both are created independently (offline / concurrent replicas)"],
        then=["the port's convergence rule for the uniqueness violation is observed and asserted"],
    ),
    "transaction": ScenarioSketch(
        given=["a multi-write operation the source performs atomically in one transaction"],
        when=["the writes are applied on an eventual store where partial arrival is possible"],
        then=["the intermediate/partial states a reader can observe are asserted"],
    ),
    "autoincrement-id": ScenarioSketch(
        given=["two entities created independently that would each get the next serial id"],
        when=["both are created without a central id authority"],
        then=["ids do not collide and ordering assumptions from serial ids are checked"],
    ),
    "access-check": ScenarioSketch(
        given=["an actor and a resource with a server-side access rule"],
        when=["the resource is read/written under the eventual, selective-disclosure model"],
        then=["the value visible to the actor matches the source's access decision"],
    ),
    "revision-lock": ScenarioSketch(
        given=["a record two writers update from the same base revision"],
        when=["both updates are applied without a central lock"],
        then=["the converged value and the fate of the lost update are asserted"],
    ),
}


def cm_candidate_from_adjudicated(adj: Any) -> FixtureCandidate:
    """Build a :class:`FixtureCandidate` from an :class:`~ctkr.intent_cm.AdjudicatedCM`
    row (hard/soft sensitivity). ``adj`` is duck-typed so tests can pass a stub."""
    categories = list(getattr(adj, "categories", []) or [])
    cat0 = categories[0] if categories else ""
    citation = ""
    cites = list(getattr(adj, "citations", []) or [])
    if cites:
        citation = cites[0]
    scenario = _CM_SCENARIO.get(cat0, ScenarioSketch(
        given=["the source assumption the CM detector flagged"],
        when=["it is re-expressed on the eventual-consistency target"],
        then=["the convergence/visibility behavior is observed and asserted"],
    ))
    sensitivity = getattr(adj, "sensitivity", "")
    element_id = getattr(adj, "element_id", "")
    short = element_id.split(":")[1] if ":" in element_id else element_id
    why = (
        f"intent-CM graded this {cat0} site '{sensitivity}': "
        + (getattr(adj, "rationale", "") or "")
    )
    title = f"[cm/{cat0}] {short}"
    topic = classify_topic(f"{cat0} {short} {why}") or (
        "uniqueness-constraint" if cat0 == "unique-constraint" else cat0
    )
    return FixtureCandidate(
        title=title, feature=_module_of(citation.split(":")[0] if citation else short),
        scenario=scenario, why_non_obvious=why, lanes=[LANE_CM],
        source_citation=citation, topic=topic, element_id=element_id,
        lane_detail={"cm": {"category": cat0, "sensitivity": sensitivity,
                            "categories": categories}},
    ).with_id()


def mine_cm_lane(adjudicated: Sequence[Any]) -> list[FixtureCandidate]:
    """Turn hard/soft adjudicated CM rows into candidates (none-graded rows dropped)."""
    out: list[FixtureCandidate] = []
    for adj in adjudicated:
        if getattr(adj, "sensitivity", "") in ("hard", "soft"):
            out.append(cm_candidate_from_adjudicated(adj))
    return out


# --------------------------------------------------------------------------- #
# Lane 3 — source-read (LLM, gpt-5.6-terra, structured + repair)              #
# --------------------------------------------------------------------------- #
class SourceRule(BaseModel):
    """One behavioral rule a re-implementer could plausibly get wrong."""

    model_config = ConfigDict(extra="forbid")

    rule: str = Field(description="The behavioral rule, stated as an observable value semantic.")
    why_non_obvious: str = Field(
        description="Why a competent re-implementer working from method names could get "
        "this wrong."
    )
    citation: str = Field(description="file:line in the provided source the rule rests on.")
    given: list[str] = Field(default_factory=list, description="Domain setup, one clause per item.")
    when: list[str] = Field(default_factory=list, description="Action(s) taken.")
    then: list[str] = Field(default_factory=list, description="The value(s) asserted.")
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="0..1 confidence this is a real, non-obvious, port-relevant rule.",
    )


class SourceReadOut(BaseModel):
    """The model's extracted behavioral rules for one module's source."""

    model_config = ConfigDict(extra="forbid")

    rules: list[SourceRule] = Field(default_factory=list)


_SOURCE_READ_SYS = (
    "You are auditing SOURCE code that is being re-implemented for a local-first, "
    "eventually-consistent target (append-only event log + materialized views). Your "
    "job is to surface the BEHAVIORAL RULES a competent re-implementer, working only "
    "from method/field NAMES and the obvious happy path, could plausibly get WRONG — "
    "the non-obvious value semantics. Examples of the genre: an aggregate that sums "
    "across categories its name implies it excludes; a 'latest-wins' read modelled as "
    "additive; a status filter that is absent where one is assumed; a uniqueness or "
    "ordering assumption. For EACH rule give a one-line observable value semantic, why "
    "it is non-obvious, a file:line citation into the provided source, and a "
    "given/when/then sketch. Ignore pure framework plumbing, DI wiring, and cosmetic "
    "code. Prefer few high-signal rules over many shallow ones."
)


def build_module_source_prompt(
    module_name: str, source_with_lines: str, *, max_chars: int = 60000
) -> str:
    body = source_with_lines
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... [truncated]"
    return (
        f"# Module: {module_name}\n\n"
        "The source below is line-numbered as `<lineno>| <code>` and prefixed with "
        "`=== FILE: <relpath> ===` per file — cite as `<relpath>:<lineno>`.\n\n"
        f"{body}\n\n"
        "Emit a SourceReadOut: the non-obvious behavioral rules a port could get wrong."
    )


def read_module_source(
    module_root: str | Path, *, suffixes: tuple[str, ...] = (".php", ".module", ".inc"),
    max_files: int = 40,
) -> str:
    """Concatenate a module's source with per-file headers + line numbers for citation."""
    root = Path(module_root)
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix in suffixes and "/tests/" not in str(p).lower()
        and "/test/" not in str(p).lower()
    )[:max_files]
    chunks: list[str] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(root)
        numbered = "\n".join(f"{i + 1}| {ln}" for i, ln in enumerate(text.splitlines()))
        chunks.append(f"=== FILE: {rel} ===\n{numbered}")
    return "\n\n".join(chunks)


def source_rule_to_candidate(rule: SourceRule, module_name: str) -> FixtureCandidate:
    topic = classify_topic(f"{rule.rule} {rule.why_non_obvious}") or "source-rule"
    return FixtureCandidate(
        title=f"[source] {rule.rule[:80]}",
        feature=module_name,
        scenario=ScenarioSketch(given=rule.given, when=rule.when, then=rule.then),
        why_non_obvious=rule.why_non_obvious,
        lanes=[LANE_SOURCE_READ], source_citation=rule.citation, topic=topic,
        lane_detail={"source_read": {"module": module_name, "rule": rule.rule,
                                     "confidence": rule.confidence}},
    ).with_id()


def mine_source_read_lane(
    module_sources: Mapping[str, str],
    client: Any,
    *,
    model: str,
    provider: str | None = None,
    max_tokens: int = 4000,
    reasoning_effort: str | None = None,
) -> tuple[list[FixtureCandidate], float]:
    """Ask the model for non-obvious behavioral rules per module. Returns
    ``(candidates, total_cost_usd)``. Degrades one module on failure rather than
    aborting; uses the ``repair=`` structured retry."""
    cands: list[FixtureCandidate] = []
    total_cost = 0.0
    for module_name, src in module_sources.items():
        if not src.strip():
            continue
        prompt = build_module_source_prompt(module_name, src)
        try:
            res = client.complete_structured(
                prompt, schema=SourceReadOut, model=model, provider=provider,
                system=_SOURCE_READ_SYS, max_tokens=max_tokens,
                reasoning_effort=reasoning_effort, repair=True,
            )
        except Exception:  # noqa: BLE001 — degrade this module, keep the batch
            continue
        total_cost += res.cost_estimate_usd
        for rule in res.parsed.rules:
            cands.append(source_rule_to_candidate(rule, module_name))
    return cands, round(total_cost, 6)


# --------------------------------------------------------------------------- #
# Fusion + ranking                                                            #
# --------------------------------------------------------------------------- #
class RankWeights(BaseModel):
    """Deterministic rank-score dials (documented in the module docstring)."""

    model_config = ConfigDict(extra="forbid")

    cm_hard: float = 1.0
    cm_soft: float = 0.6
    source_base: float = 0.5  # scaled by the rule's confidence
    graph_reach_cap: int = 20  # reach normaliser (reach/cap, clamped to 1)
    graph_weight: float = 0.7  # graph lane's max standalone contribution
    fusion_bonus: float = 0.5  # per extra lane a candidate is surfaced by
    reach_bonus: float = 0.15  # added * reach_norm on top


def _lane_base_score(c: FixtureCandidate, w: RankWeights) -> float:
    scores: list[float] = []
    if LANE_CM in c.lanes:
        sens = c.lane_detail.get("cm", {}).get("sensitivity", "")
        scores.append(w.cm_hard if sens == "hard" else w.cm_soft)
    if LANE_SOURCE_READ in c.lanes:
        conf = float(c.lane_detail.get("source_read", {}).get("confidence", 0.5))
        scores.append(w.source_base + 0.5 * conf)
    if LANE_GRAPH in c.lanes:
        reach_norm = min(c.reach / max(w.graph_reach_cap, 1), 1.0)
        scores.append(w.graph_weight * reach_norm)
    return max(scores) if scores else 0.0


def _merge(into: FixtureCandidate, other: FixtureCandidate) -> FixtureCandidate:
    """Fuse ``other`` into ``into``: union lanes, take the richer citation/reach,
    keep the more specific (non-graph) title/scenario when available."""
    lanes = list(dict.fromkeys(into.lanes + other.lanes))
    detail = {**into.lane_detail, **other.lane_detail}
    reach = max(into.reach, other.reach)
    citation = into.source_citation or other.source_citation
    # Prefer a CM/source title+scenario over a graph one (more semantic content).
    primary, secondary = into, other
    if into.lanes == [LANE_GRAPH] and other.lanes != [LANE_GRAPH]:
        primary, secondary = other, into
    return primary.model_copy(update={
        "lanes": lanes, "lane_detail": detail, "reach": reach,
        "source_citation": citation,
        "element_id": primary.element_id or secondary.element_id,
        "why_non_obvious": (
            primary.why_non_obvious
            + ("" if secondary.topic == primary.topic and secondary.lanes == primary.lanes
               else f"  [also surfaced by {'/'.join(secondary.lanes)}: "
                    f"{secondary.why_non_obvious[:160]}]")
        ),
    })


def fuse_and_rank(
    lanes: Sequence[Sequence[FixtureCandidate]],
    *,
    weights: RankWeights | None = None,
) -> list[FixtureCandidate]:
    """Fuse candidates across lanes by (topic, feature) and rank by score.

    Fusion key = (canonical topic, owning module). Candidates that share it — the
    strong multi-lane agreement signal — are merged into one, its lanes unioned. A
    candidate with no classified topic ("" ) fuses only by exact (title) so distinct
    source rules stay distinct. Score (deterministic):

        base   = max over lanes of {cm: hard 1.0/soft 0.6;
                                     source: 0.5 + 0.5*confidence;
                                     graph: 0.7 * min(reach/cap, 1)}
        score  = base + fusion_bonus*(n_lanes-1) + reach_bonus*min(reach/cap,1)

    so a two-lane candidate always outranks either lane alone, and reach breaks
    ties among single-lane graph candidates.
    """
    w = weights or RankWeights()
    buckets: dict[tuple[str, str], FixtureCandidate] = {}
    order: list[tuple[str, str]] = []
    for lane_cands in lanes:
        for c in lane_cands:
            # Fuse ONLY on a canonical semantic topic (the strong cross-lane
            # agreement signal). A category-fallback topic (e.g. "domain-logic",
            # "hook-implementation") is NOT canonical: those candidates stay
            # distinct, keyed by element/title, so many high-reach classes in one
            # module are not collapsed into a single row.
            if c.topic in CANONICAL_TOPICS:
                key = (c.topic, c.feature)
            else:
                key = ("", c.element_id or c.title.lower())
            if key in buckets:
                buckets[key] = _merge(buckets[key], c)
            else:
                buckets[key] = c
                order.append(key)

    ranked: list[FixtureCandidate] = []
    for key in order:
        c = buckets[key]
        base = _lane_base_score(c, w)
        n_lanes = len(c.lanes)
        reach_norm = min(c.reach / max(w.graph_reach_cap, 1), 1.0)
        score = base + w.fusion_bonus * (n_lanes - 1) + w.reach_bonus * reach_norm
        ranked.append(c.model_copy(update={"rank_score": round(score, 4)}).with_id())

    ranked.sort(key=lambda c: (-c.rank_score, -c.reach, c.candidate_id))
    return ranked


# --------------------------------------------------------------------------- #
# IO                                                                          #
# --------------------------------------------------------------------------- #
def write_candidates(cands: Iterable[FixtureCandidate], path: str | Path) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as fh:
        for c in cands:
            c = c if c.candidate_id else c.with_id()
            fh.write(json.dumps(c.model_dump(), default=str) + "\n")
            n += 1
    return n


def load_candidates(path: str | Path) -> list[FixtureCandidate]:
    out: list[FixtureCandidate] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(FixtureCandidate.model_validate_json(line))
    return out


__all__ = [
    "LANE_CM", "LANE_GRAPH", "LANE_SOURCE_READ",
    "ScenarioSketch", "FixtureCandidate", "RankWeights",
    "SourceRule", "SourceReadOut",
    "classify_topic", "compute_reach", "mine_graph_lane", "mine_field_flow_edges",
    "mine_cm_lane", "cm_candidate_from_adjudicated",
    "mine_source_read_lane", "read_module_source", "build_module_source_prompt",
    "source_rule_to_candidate",
    "fuse_and_rank", "write_candidates", "load_candidates",
]
