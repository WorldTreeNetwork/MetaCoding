"""Mechanical intention harvest — Stage T5a (ct-intention-extraction.md §9.2).

The **LM-free** layer of the intention channel. Downstream of the frozen
structural analysis (companion §2–§4), this module harvests every *incidental
indicator of intention* the source carries — names, docstrings, error strings,
decorators, comments, tests — attaches each to a structural element via the
frozen member set (§2), and scores where structure alone underdetermines the
spec (§5). Everything here is deterministic (graph joins + source-text regex +
FTS + parquet reads); LM judgment enters only at T5b synthesis.

Three artifacts, all byte-identical on re-run for fixed inputs:

* ``intention_signals.parquet`` — the harvest's ground truth (§9.1): one row per
  ``(element_id, element_kind, indicator_kind, tier, content, file, line_range,
  portability_tier, …)``. Everything downstream cites ``signal_id``.
* ``intention_load.parquet`` — the §5 indicator: per element the structural
  determinacy ``D``, intention richness ``R``, load class, and the drivers that
  produced them (the scores are auditable triage heuristics, not theorems §5.3).
* ``intention_conflicts.parquet`` — mechanical conflict candidates (§6.1 stage
  1): a name/doc/decorator claim contradicting a tier-I structural fact. Feeds
  T5b's LM adjudication; the table (``data/conflict_detectors.json``) proposes.

**No tree-sitter in this Python package.** The design's harvest is specified
against tree-sitter node kinds; here the same signals are recovered from the
exported typed graph (node kinds, edges, signatures), regex over source-file
slices, and the FTS index. Where a signal is a *regex approximation* of a
node-precise extraction (string literals, comment runs, error strings at raise
sites) the harvest records a coverage note rather than claiming node fidelity.
See :data:`HARVEST_COVERAGE` and the module's docstring for the deferred set.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import polars as pl
from blake3 import blake3

from ctkr.evidence import _extract_docstring  # reuse the shipped docstring heuristic
from ctkr.schema import (
    INTENTION_CONFLICTS_COLUMNS,
    INTENTION_LOAD_COLUMNS,
    INTENTION_SIGNALS_COLUMNS,
    SCHEMA_VERSION,
)

logger = logging.getLogger("ctkr.intention")

_DATA_DIR = Path(__file__).parent / "data"

# Indicators the harvest does NOT emit in T5a, with the honest reason. Surfaced
# in the run summary + manifest so a thin section reads as a known gap, not an
# absent signal (same discipline as interfaces.alphabet_coverage).
DEFERRED_INDICATORS: dict[str, str] = {
    "B2": "README/doc-fragment FTS scoring — deferred; needs the doc-file lane "
    "(companion §5.4) + FTS scoring against member names, low tier (§1 tier B).",
    "C1": "git commit subjects / blame — deferred behind --git-signals per the "
    "design's open decision (d); off in v1 (§1 tier C).",
    "C2": "local variable names — never harvested standalone; ride along in "
    "exemplar slices (§1 tier C, by design).",
    "C3": "commented-out code — not harvested as intention by design (§1 tier C).",
}

# Coverage caveats for signals we DO emit but via regex approximation rather than
# tree-sitter node kinds (the design's stated extraction). Reported per run.
HARVEST_COVERAGE: dict[str, str] = {
    "A2": "string literals classified by regex over source slices, not "
    "tree-sitter string nodes — misses multi-line / concatenated literals.",
    "S3": "error strings recovered by regex near raise/throw lines in the "
    "member slice; RAISES edges give the exception type precisely.",
    "A6": "comment runs recovered by the shipped line/JSDoc/py-docstring "
    "heuristic; marker regex is exact.",
    "A3": "const/enum default *values* parsed from the signature string when "
    "present; the declaration node kind is precise.",
}


# ───────────────────────── tokenizer + tables ─────────────────────────


@dataclass(frozen=True)
class NormTables:
    """Loaded, versioned normalization tables (``intention_normalization.json``)."""

    version: int
    convention_affixes: dict[str, list[dict]]
    marker_vocabulary: dict
    test_conventions: dict
    name_semantics: dict
    string_classifiers: dict
    scoring: dict
    portability_defaults: dict

    @property
    def marker_canonical(self) -> dict[str, list[str]]:
        return self.marker_vocabulary["canonical"]


def load_norm_tables(path: str | Path | None = None) -> NormTables:
    p = Path(path) if path else _DATA_DIR / "intention_normalization.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    return NormTables(
        version=raw["version"],
        convention_affixes=raw["convention_affixes"],
        marker_vocabulary=raw["marker_vocabulary"],
        test_conventions=raw["test_conventions"],
        name_semantics=raw["name_semantics"],
        string_classifiers=raw["string_classifiers"],
        scoring=raw["scoring"],
        portability_defaults=raw["portability_defaults"],
    )


def load_conflict_detectors(path: str | Path | None = None) -> dict:
    p = Path(path) if path else _DATA_DIR / "conflict_detectors.json"
    return json.loads(p.read_text(encoding="utf-8"))


# camelCase / PascalCase / snake_case / kebab-case → lowercased token sequence.
_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")
_SEP = re.compile(r"[_\-.:/\s]+")
_DIGIT_SPLIT = re.compile(r"([a-zA-Z])([0-9])|([0-9])([a-zA-Z])")


def tokenize_identifier(name: str) -> list[str]:
    """Split an identifier into a lowercased token sequence (§7.1(1)).

    ``getUserById`` ≡ ``get_user_by_id`` ≡ ``GetUserByID`` → ``[get, user, by,
    id]``. Handles camelCase, PascalCase, snake_case, kebab-case, dotted/`::`
    qualified segments, and digit runs. Empty tokens are dropped. Deterministic
    and pure — all A5 pattern work and cross-stack comparison run on this, never
    the raw string.
    """
    if not name:
        return []
    # Keep only the final qualified segment's morphology but tokenize the whole
    # thing: split on structural separators first, then camel boundaries.
    s = _SEP.sub(" ", name)
    s = _CAMEL_1.sub(r"\1 \2", s)
    s = _CAMEL_2.sub(r"\1 \2", s)
    out: list[str] = []
    for chunk in s.split():
        # split letter/digit boundaries (v2 → v, 2)
        parts = re.sub(_DIGIT_SPLIT, lambda m: " ".join(g for g in m.groups() if g), chunk)
        for tok in parts.split():
            t = tok.lower()
            if t:
                out.append(t)
    return out


def fold_affixes(
    tokens: Sequence[str], tables: NormTables, language: str
) -> tuple[list[str], list[tuple[str, str]]]:
    """Fold convention affixes out of a token sequence (§7.1(2)).

    Returns ``(domain_tokens, folded)`` where ``folded`` is a list of
    ``(affix, portability)`` pairs removed — the convention-carried morphemes an
    A5 pattern should *restate* (N) or *drop* (A), never copy. Domain tokens keep
    their order; a token is folded at most once.
    """
    entries = list(tables.convention_affixes.get("common", []))
    entries += list(tables.convention_affixes.get(language, []))
    toks = list(tokens)
    folded: list[tuple[str, str]] = []
    for e in entries:
        affix = e["affix"]
        where = e["where"]
        if where == "prefix" and toks and toks[0] == affix:
            # single-letter prefixes (I-interface) only fold before a real token
            if len(affix) == 1 and len(toks) < 2:
                continue
            folded.append((affix, e["portability"]))
            toks = toks[1:]
        elif where == "suffix" and toks and toks[-1] == affix:
            folded.append((affix, e["portability"]))
            toks = toks[:-1]
        elif where == "token" and affix in toks:
            folded.append((affix, e["portability"]))
            toks = [t for t in toks if t != affix]
    return toks, folded


def canonical_marker(word: str, tables: NormTables) -> str | None:
    """Map a raw marker word to its canonical form (§7.1(3)); None if not a marker."""
    w = word.strip().lower().strip(":")
    for canon, variants in tables.marker_canonical.items():
        if w == canon.lower() or w in variants:
            return canon
    return None


# ───────────────────────── row builders ─────────────────────────


def _signal_id(element_id: str, kind: str, content: str, file: str, lr: str) -> str:
    h = blake3()
    for part in (element_id, kind, content, file, lr):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest(length=12)


def _lr(start: int | None, end: int | None) -> str:
    if start is None:
        return ""
    if end is None or end == start:
        return str(start)
    return f"{start}-{end}"


@dataclass
class Sig:
    element_id: str
    element_kind: str
    indicator_kind: str
    tier: str
    content: str
    file: str
    line_start: int | None
    line_end: int | None
    portability_tier: str

    def row(self) -> dict:
        lr = _lr(self.line_start, self.line_end)
        return {
            "signal_id": _signal_id(
                self.element_id, self.indicator_kind, self.content, self.file, lr
            ),
            "element_id": self.element_id,
            "element_kind": self.element_kind,
            "indicator_kind": self.indicator_kind,
            "tier": self.tier,
            "content": self.content,
            "file": self.file,
            "line_range": lr,
            "portability_tier": self.portability_tier,
            "schema_version": SCHEMA_VERSION,
        }


# ───────────────────────── the harvester ─────────────────────────


@dataclass
class HarvestStats:
    n_signals: int = 0
    n_load_rows: int = 0
    n_conflicts: int = 0
    n_port_critical: int = 0
    n_boundary_exports: int = 0
    n_boundary_exports_tested: int = 0
    test_linkage_fraction: float = 0.0
    by_indicator: dict[str, int] = field(default_factory=dict)
    by_portability: dict[str, int] = field(default_factory=dict)
    load_classes: dict[str, int] = field(default_factory=dict)
    deferred: dict[str, str] = field(default_factory=lambda: dict(DEFERRED_INDICATORS))
    coverage: dict[str, str] = field(default_factory=lambda: dict(HARVEST_COVERAGE))
    total_seconds: float = 0.0


# read/write-implying name detection is shared by S2 hints + conflict detectors.
_PARAM_GROUP = re.compile(r"\(([^)]*)\)")
_PARAM_NAME = re.compile(r"^\s*[*&]*([A-Za-z_$][A-Za-z0-9_$]*)")
_DOC_PARAM = re.compile(
    r"(?m)^\s*(?::param\s+(\w+)|@param\s+(?:\{[^}]*\}\s+)?(\w+)|(\w+)\s*[:(]\s*\S)"
)
_STRING_LIT = re.compile(r"""(?:"([^"\n]{2,240})"|'([^'\n]{2,240})'|`([^`\n]{2,240})`)""")
_MARKER_WORD = re.compile(r"\b([A-Za-z]{2,12})\b")


class Harvester:
    """Stateful harvest over one loaded graph + its structural artifacts."""

    def __init__(
        self,
        g: nx.MultiDiGraph,
        *,
        members_df: pl.DataFrame,
        interfaces_df: pl.DataFrame | None,
        data_shapes_df: pl.DataFrame | None,
        presentations_df: pl.DataFrame | None,
        repo_root: Path,
        tables: NormTables,
        detectors: dict,
        exclude_prefixes: Sequence[str] = (".claude/",),
        fts_path: str | Path | None = None,
    ) -> None:
        self.g = g
        self.repo_root = repo_root
        self.tables = tables
        self.detectors = detectors
        self.exclude_prefixes = tuple(exclude_prefixes)
        self.fts_path = Path(fts_path) if fts_path else None
        self.body_window = 50  # forward lines read when end_line is unreliable (dial)
        self.sym2sub: dict[str, str] = {}
        self.sub2repo: dict[str, str] = {}
        for r in members_df.iter_rows(named=True):
            self.sym2sub[r["symbol_id"]] = r["subsystem_id"]
            self.sub2repo[r["subsystem_id"]] = r["repo"]
        self.interfaces_df = interfaces_df
        self.data_shapes_df = data_shapes_df
        self.presentations_df = presentations_df
        self._slice_cache: dict[str, list[str] | None] = {}
        # CONTAINS descendants — test edges land on nested members (methods),
        # not the top-level export, so linkage must roll down the containment tree.
        self._contains_children: dict[str, list[str]] = defaultdict(list)
        for u, v, k in g.edges(keys=True):
            if k == "CONTAINS":
                self._contains_children[u].append(v)
        self._test_files = self._detect_test_files()
        self._test_symbols = self._collect_test_symbols()

    def excluded(self, sid: str) -> bool:
        """True if a symbol lives under an excluded path prefix (e.g. worktree copies)."""
        f = self._nd(sid).get("file") or self._nd(sid).get("file_path") or ""
        return any(f.startswith(p) for p in self.exclude_prefixes)

    def _descendants(self, sid: str, limit: int = 2000) -> list[str]:
        out: list[str] = []
        stack = list(self._contains_children.get(sid, []))
        seen: set[str] = set()
        while stack and len(out) < limit:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            stack.extend(self._contains_children.get(cur, []))
        return out

    # ---- source access ----

    def _nd(self, sid: str) -> dict:
        return self.g.nodes.get(sid, {})

    def _read_slice(self, sid: str, ctx: int = 2) -> tuple[list[str], int]:
        """Return (lines, start_line_1indexed) for a symbol's source window."""
        d = self._nd(sid)
        repo = d.get("repo")
        file = d.get("file") or d.get("file_path")
        line = d.get("line")
        if not repo or not file or not line:
            return [], 0
        # end_line is frequently stale/absent in the export (0 or < line). When it
        # is unusable, read a bounded forward BODY window so body-dependent signals
        # (A2 literals, A6 comments, S3 error strings) see more than the def line.
        raw_end = int(d.get("end_line") or 0)
        end = raw_end if raw_end > int(line) else int(line) + self.body_window
        key = f"{repo}/{file}"
        if key not in self._slice_cache:
            path = self.repo_root / repo / file
            try:
                self._slice_cache[key] = path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                self._slice_cache[key] = None
        alllines = self._slice_cache[key]
        if alllines is None:
            return [], 0
        start = max(1, int(line) - ctx)
        stop = min(len(alllines), int(end) + ctx)
        return alllines[start - 1 : stop], start

    # ---- test detection (S1) ----

    def _detect_test_files(self) -> set[str]:
        globs = self.tables.test_conventions["path_globs"]
        regexes = [re.compile(_glob_to_re(gp)) for gp in globs]
        files: set[str] = set()
        for _, d in self.g.nodes(data=True):
            f = d.get("file") or d.get("file_path")
            if not f or any(f.startswith(p) for p in self.exclude_prefixes):
                continue
            if any(rx.search(f) for rx in regexes):
                files.add(f)
        return files

    def _collect_test_symbols(self) -> set[str]:
        out: set[str] = set()
        for n, d in self.g.nodes(data=True):
            f = d.get("file") or d.get("file_path")
            if f in self._test_files:
                out.add(n)
        return out

    def _tests_linking(self, sym_id: str) -> list[tuple[str, str]]:
        """Test symbols reaching an export via reverse edges + FTS complement (§1 S1).

        Rolls DOWN the containment tree — a test calls a method, not the top-level
        export — and complements structural linkage with an FTS pass over the
        export's short name restricted to test files (the 22.7% structurally-
        isolated floor applies to test linkage too, hence the FTS complement in
        the design). Returns ``(test_symbol_id_or_'fts', evidence_string)`` pairs.
        """
        targets = {sym_id, *self._descendants(sym_id)}
        out: dict[str, str] = {}
        for t in targets:
            for src, _, k in self.g.in_edges(t, keys=True):
                if k in ("CALLS", "REFERENCES") and src in self._test_symbols:
                    td = self._nd(src)
                    out[src] = td.get("qualified_name") or src
        if not out:
            out.update(self._fts_test_hits(sym_id))
        return sorted(out.items())

    def _fts_test_hits(self, sym_id: str) -> dict[str, str]:
        """FTS complement: the export's short name appearing in a test file."""
        if self.fts_path is None or not self.fts_path.exists():
            return {}
        d = self._nd(sym_id)
        short = d.get("short_name") or (d.get("qualified_name") or "").split("::")[-1]
        if not short or len(short) < 4:
            return {}
        from ctkr.graph_loader import search_tokens

        try:
            df = search_tokens(self.fts_path, f'"{short}"', limit=40)
        except Exception:
            return {}
        hits: dict[str, str] = {}
        for r in df.iter_rows(named=True):
            f = r.get("file") or ""
            if f in self._test_files and not any(f.startswith(p) for p in self.exclude_prefixes):
                key = f"fts:{f}:{r.get('line')}"
                hits[key] = f"{f}:{r.get('line')}"
        return hits

    # ---- per-symbol harvest ----

    def harvest_symbol(self, sid: str, element_kind: str) -> list[Sig]:
        d = self._nd(sid)
        sigs: list[Sig] = []
        file = d.get("file") or d.get("file_path") or ""
        line = d.get("line")
        end = d.get("end_line") or line
        qn = d.get("qualified_name") or sid
        short = d.get("short_name") or (qn.split("::")[-1] if qn else sid)
        lang = d.get("language") or ""
        pdef = self.tables.portability_defaults

        # S2 — interface identifier + parameter names
        if element_kind == "interface-export":
            sigs.append(Sig(sid, element_kind, "S2", "S", short, file, line, line, pdef["S2"]))
            for pname in self._param_names(d.get("signature")):
                sigs.append(
                    Sig(sid, element_kind, "S2", "S", f"param:{pname}", file, line, line, pdef["S2"])
                )

        # A1 — decorator / annotation names (ANNOTATES out-edges)
        for _, dst, k in self.g.out_edges(sid, keys=True):
            if k == "ANNOTATES":
                dqn = self._nd(dst).get("short_name") or self._nd(dst).get("qualified_name") or dst
                sigs.append(Sig(sid, element_kind, "A1", "A", f"@{dqn}", file, line, line, pdef["A1"]))

        # S3 — raised exception types (RAISES out-edges) + error strings near raises
        raised = [
            self._nd(dst).get("short_name") or self._nd(dst).get("qualified_name") or dst
            for _, dst, k in self.g.out_edges(sid, keys=True)
            if k == "RAISES"
        ]
        for rt in sorted(set(raised)):
            sigs.append(Sig(sid, element_kind, "S3", "S", f"raises:{rt}", file, line, line, pdef["S3-type"]))

        # A3 — const/enum policy value from the signature, if this is a constant
        if d.get("kind") in ("const", "constant", "variable", "enum_member", "field") and d.get("signature"):
            val = _default_value(d.get("signature"))
            if val is not None:
                sigs.append(Sig(sid, element_kind, "A3", "A", f"{short}={val}", file, line, line, pdef["A3"]))

        # B3 — import sources (IMPORTS out-edges to external packages)
        if element_kind in ("interface-export", "subsystem"):
            for _, dst, k in self.g.out_edges(sid, keys=True):
                if k == "IMPORTS":
                    dqn = self._nd(dst).get("qualified_name") or dst
                    sigs.append(Sig(sid, element_kind, "B3", "B", f"imports:{dqn}", file, line, line, pdef["B3"]))

        # B1 — path prose (directory + file name tokens)
        if element_kind == "interface-export" and file:
            path_toks = [t for t in tokenize_identifier(file) if t not in ("ts", "tsx", "js", "py")]
            if path_toks:
                sigs.append(
                    Sig(sid, element_kind, "B1", "B", " ".join(path_toks), file, line, line, pdef["B1"])
                )

        # Source-derived: S4 docstring, A2 string literals, A6 comments/markers.
        lines, start = self._read_slice(sid)
        if lines:
            snippet = "\n".join(lines)
            doc = _extract_docstring(snippet, lang)
            if doc:
                sigs.append(
                    Sig(sid, element_kind, "S4", "S", _clip(doc, 400), file, line, end, pdef["S4"])
                )
            # A2 — classified string literals
            for cls, text, lno in self._classify_strings(lines, start):
                port = "I"
                sigs.append(
                    Sig(sid, element_kind, "A2", "A", f"{cls}:{_clip(text, 200)}", file, lno, lno, port)
                )
            # S3 — error strings on lines mentioning raise/throw
            for text, lno in self._error_strings(lines, start):
                sigs.append(
                    Sig(sid, element_kind, "S3", "S", f"errmsg:{_clip(text, 200)}", file, lno, lno, pdef["S3-message"])
                )
            # A6 — WHY / marker comments
            for content, _marker, lno in self._comments(lines, start):
                sigs.append(Sig(sid, element_kind, "A6", "A", content, file, lno, lno, pdef["A6"]))

        # S1 — test linkage (behavioral intention), only meaningful for exports
        if element_kind == "interface-export":
            for tkey, tname in self._tests_linking(sid):
                if tkey.startswith("fts:"):
                    tfile = tname.rsplit(":", 1)[0]
                    tline = _safe_int(tname.rsplit(":", 1)[1])
                    sigs.append(
                        Sig(sid, element_kind, "S1", "S", f"test~{tname}", tfile, tline, tline, pdef["S1"])
                    )
                else:
                    td = self._nd(tkey)
                    tfile = td.get("file") or td.get("file_path") or ""
                    tline = td.get("line")
                    sigs.append(
                        Sig(sid, element_kind, "S1", "S", f"test:{tname}", tfile, tline, tline, pdef["S1"])
                    )
        return sigs

    def _param_names(self, signature: str | None) -> list[str]:
        if not signature:
            return []
        m = _PARAM_GROUP.search(signature)
        if not m:
            return []
        out: list[str] = []
        for part in m.group(1).split(","):
            part = part.strip()
            if not part or part in ("self", "cls"):
                continue
            nm = _PARAM_NAME.match(part)
            if nm:
                out.append(nm.group(1))
        return out

    def _classify_strings(self, lines: list[str], start: int) -> list[tuple[str, str, int]]:
        out: list[tuple[str, str, int]] = []
        classes = self.tables.string_classifiers["classes"]
        seen: set[tuple[str, str]] = set()
        for i, ln in enumerate(lines):
            for m in _STRING_LIT.finditer(ln):
                text = next((g for g in m.groups() if g), "")
                if len(text) < self.tables.string_classifiers["min_length"]:
                    continue
                for c in classes:
                    if re.search(c["pattern"], text):
                        key = (c["kind"], text)
                        if key in seen:
                            break
                        seen.add(key)
                        out.append((c["kind"], text, start + i))
                        break
        return out

    def _error_strings(self, lines: list[str], start: int) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for i, ln in enumerate(lines):
            if re.search(r"\b(raise|throw)\b", ln):
                for m in _STRING_LIT.finditer(ln):
                    text = next((g for g in m.groups() if g), "")
                    if len(text) >= 4:
                        out.append((text, start + i))
        return out

    def _comments(self, lines: list[str], start: int) -> list[tuple[str, str | None, int]]:
        out: list[tuple[str, str | None, int]] = []
        why_lead = self.tables.marker_vocabulary["why_lead"]
        for i, ln in enumerate(lines):
            stripped = ln.strip()
            comment = None
            if stripped.startswith("#"):
                comment = stripped.lstrip("#").strip()
            elif stripped.startswith("//"):
                comment = stripped.lstrip("/").strip()
            if not comment:
                continue
            marker = None
            for w in _MARKER_WORD.findall(comment):
                cm = canonical_marker(w, self.tables)
                if cm:
                    marker = cm
                    break
            is_why = any(lead in comment.lower() for lead in why_lead)
            if marker:
                out.append((f"[{marker}] {_clip(comment, 200)}", marker, start + i))
            elif is_why:
                out.append((f"[WHY] {_clip(comment, 200)}", None, start + i))
        return out


# ───────────────────────── glue helpers ─────────────────────────


def _glob_to_re(glob: str) -> str:
    # Minimal glob→regex. ``**/`` matches zero or more leading path segments (so
    # ``**/test_*.py`` matches both ``test_x.py`` and ``a/b/test_x.py``); ``**``
    # matches any chars; ``*`` matches within a segment.
    out = re.escape(glob)
    out = out.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return out.replace(r"\?", ".") + r"$"


def _clip(s: str, n: int) -> str:
    s = s.strip().replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _safe_int(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _default_value(signature: str) -> str | None:
    if "=" in signature:
        return signature.split("=", 1)[1].strip()[:80] or None
    if ":" in signature:
        return signature.split(":", 1)[1].strip()[:80] or None
    return None


def _read_implying(tokens: Sequence[str], tables: NormTables) -> list[str]:
    rd = set(tables.name_semantics["read_implying"])
    return [t for t in tokens if t in rd]


def _write_implying(tokens: Sequence[str], tables: NormTables) -> list[str]:
    wr = set(tables.name_semantics["write_implying"])
    return [t for t in tokens if t in wr]


def _saturate(x: float, scale: float) -> float:
    """1 - exp(-x/scale): a monotone [0, ∞)→[0,1) saturating map (a dial via scale)."""
    if scale <= 0:
        return 0.0
    return 1.0 - math.exp(-max(0.0, x) / scale)


def _norm_entropy(counts: Iterable[int]) -> float:
    """Shannon entropy of a distribution, normalized to [0,1] by log2(k). 0 = coherent."""
    cs = [c for c in counts if c > 0]
    total = sum(cs)
    if total <= 0 or len(cs) <= 1:
        return 0.0
    h = -sum((c / total) * math.log2(c / total) for c in cs)
    return h / math.log2(len(cs))


# ───────────────────────── A5 naming pattern ─────────────────────────


def naming_pattern(
    member_names: Sequence[str], tables: NormTables, language: str
) -> tuple[str, float]:
    """A5: the shared naming morphology of a role class + its coherence entropy.

    Returns ``(content, entropy)``. ``content`` states the dominant head token
    ("members follow ``*Validator`` (11/14)") plus shared tokens and folded
    affixes; ``entropy`` ∈ [0,1] over the head-token distribution (0 = perfectly
    coherent, feeds the R coherence multiplier §5.2). Operates on folded token
    sequences, never raw strings (§7.1).
    """
    heads: list[str] = []
    all_tokens: Counter = Counter()
    affixes: Counter = Counter()
    n = 0
    for name in member_names:
        toks = tokenize_identifier(name.split("::")[-1])
        domain, folded = fold_affixes(toks, tables, language)
        for a, _ in folded:
            affixes[a] += 1
        if not domain:
            continue
        n += 1
        heads.append(domain[-1])
        for t in set(domain):
            all_tokens[t] += 1
    if n == 0:
        return "no domain tokens (all convention affixes)", 0.0
    head_counts = Counter(heads)
    top_head, top_n = head_counts.most_common(1)[0]
    shared = sorted(t for t, c in all_tokens.items() if c >= max(2, (n + 1) // 2))
    ent = _norm_entropy(head_counts.values())
    parts = [f"head *{top_head} ({top_n}/{n})"]
    if shared:
        parts.append(f"shared={shared}")
    if affixes:
        parts.append(f"affixes={sorted(affixes)}")
    parts.append(f"coherence_entropy={ent:.2f}")
    return "; ".join(parts), ent


# ───────────────────────── D / R scoring ─────────────────────────


def _profile_mass(g: nx.MultiDiGraph, sid: str, weights: dict) -> tuple[float, int]:
    """Discriminativeness-weighted incident-edge mass + distinct-kind count for D."""
    default = weights.get("_default", 0.6)
    mass = 0.0
    kinds: set[str] = set()
    for _, _, k in g.out_edges(sid, keys=True):
        mass += weights.get(k, default)
        kinds.add(k)
    for _, _, k in g.in_edges(sid, keys=True):
        mass += weights.get(k, default)
        kinds.add(k)
    return mass, len(kinds)


def _determinacy_export(
    g: nx.MultiDiGraph, sid: str, tables: NormTables, is_boundary: bool
) -> tuple[float, list[str]]:
    sc = tables.scoring
    weights = sc["kind_discriminativeness"]
    mass, nkinds = _profile_mass(g, sid, weights)
    d_mass = _saturate(mass, sc["d_mass_saturation"])
    d_div = min(1.0, nkinds / 6.0)
    w = sc["d_diversity_weight"]
    d = (1 - w) * d_mass + w * d_div
    drivers = [f"profile mass {mass:.1f} (d_mass={d_mass:.2f})", f"{nkinds} edge kinds"]
    if is_boundary:
        d = min(1.0, d + sc["d_boundary_bonus"])
        drivers.append(f"boundary export (+{sc['d_boundary_bonus']})")
    return round(d, 4), drivers


def _determinacy_role(row: dict, tables: NormTables) -> tuple[float, list[str]]:
    sc = tables.scoring
    persistence = float(row.get("persistence") or 0.0)
    centroid = row.get("profile_centroid") or []
    mass = float(sum(abs(x) for x in centroid))
    d_mass = _saturate(mass, sc["d_mass_saturation"])
    boundary = bool(row.get("interface_participation"))
    d = 0.4 * persistence + 0.3 * d_mass + (0.3 if boundary else 0.0)
    drivers = [
        f"persistence {persistence:.2f}",
        f"centroid mass {mass:.1f} (d_mass={d_mass:.2f})",
        "interface-participating" if boundary else "internal role",
    ]
    return round(min(1.0, d), 4), drivers


def _richness(
    sigs: Sequence[Sig], tables: NormTables, coherence_entropy: float | None
) -> tuple[float, list[str]]:
    sc = tables.scoring
    tw = sc["tier_weights"]
    weighted = sum(tw.get(s.tier, 0.1) for s in sigs)
    r = _saturate(weighted, sc["r_saturation"])
    drivers: list[str] = []
    by_tier = Counter(s.tier for s in sigs)
    drivers.append(f"tier-weighted signal {weighted:.1f} ({dict(by_tier)})")
    # coherence multiplier (role classes only)
    if coherence_entropy is not None:
        if coherence_entropy <= sc["r_coherence_entropy_hi"]:
            r *= sc["r_coherence_hi"]
            drivers.append(f"coherent naming (entropy {coherence_entropy:.2f}, ×{sc['r_coherence_hi']})")
        else:
            r *= sc["r_coherence_lo"]
            drivers.append(f"incoherent naming (entropy {coherence_entropy:.2f}, ×{sc['r_coherence_lo']})")
    # test-linkage floor-raiser
    if any(s.indicator_kind == "S1" for s in sigs):
        n_tests = sum(1 for s in sigs if s.indicator_kind == "S1")
        r = max(r, sc["r_test_linkage_floor"])
        drivers.append(f"{n_tests} test(s) pin behavior (floor {sc['r_test_linkage_floor']})")
    return round(min(1.0, r), 4), drivers


def _classify(d: float, r: float, tables: NormTables, port_critical: bool) -> str:
    sc = tables.scoring
    if d >= sc["d_hi"] and not port_critical:
        return "structure-clear"
    if r >= sc["r_min"]:
        return "intention-critical"
    return "ambiguous"


# ───────────────────────── conflict detection ─────────────────────────


def _detect_conflicts(
    h: Harvester,
    sid: str,
    element_kind: str,
    sigs: Sequence[Sig],
    *,
    is_boundary: bool,
) -> list[dict]:
    """Run the mechanical conflict-detector table (§6.1 stage 1) over one element."""
    g, tables = h.g, h.tables
    d = h._nd(sid)
    short = d.get("short_name") or (d.get("qualified_name") or sid).split("::")[-1]
    file = d.get("file") or d.get("file_path") or ""
    line = d.get("line")
    tokens = tokenize_identifier(short)
    read_toks = _read_implying(tokens, tables)
    write_toks = _write_implying(tokens, tables)
    sub = h.sym2sub.get(sid)

    docstrings = [s.content for s in sigs if s.indicator_kind == "S4"]
    doc_blob = " ".join(docstrings).lower()
    decorators = [s.content.lower() for s in sigs if s.indicator_kind == "A1"]

    def write_edges(kinds: Sequence[str], *, boundary: bool) -> dict[str, int]:
        """Out-edges of the given kinds (optionally only those crossing the
        subsystem boundary). Honors the detector's declared ``write_edge_kinds``
        so the table — not this code — decides what counts as a write."""
        want = set(kinds)
        acc: dict[str, int] = defaultdict(int)
        for _, dst, k in g.out_edges(sid, keys=True):
            if k in want and (not boundary or h.sym2sub.get(dst) not in (None, sub)):
                acc[k] += 1
        return acc

    out: list[dict] = []
    for det in h.detectors["detectors"]:
        check = det["check"]
        if check == "name_implies_read_but_writes":
            if not read_toks or write_toks:
                continue
            writes = write_edges(
                det.get("write_edge_kinds", ["WRITES_FIELD", "CONSTRUCTS"]),
                boundary=bool(det.get("require_boundary")),
            )
            n = sum(writes.values())
            if n < det.get("min_write_edges", 1):
                continue
            kinds = ",".join(sorted(writes))
            claim = f"read-implying name (tokens {read_toks})"
            fact = f"{n} {kinds} edge(s)" + (" across boundary" if det.get("require_boundary") else "")
            out.append(_conflict_row(sid, element_kind, det, claim, fact, file, line))
        elif check == "docstring_claims_pure_but_writes":
            claim_phrase = next(
                (p for p in tables.name_semantics["pure_claiming"] if p in doc_blob), None
            )
            if not claim_phrase:
                continue
            writes = write_edges(
                det.get("write_edge_kinds", ["WRITES_FIELD"]),
                boundary=bool(det.get("require_boundary")),
            )
            n = sum(writes.values())
            if n < det.get("min_write_edges", 1):
                continue
            kinds = ",".join(sorted(writes))
            out.append(
                _conflict_row(
                    sid, element_kind, det, f"docstring claims '{claim_phrase}'",
                    f"{n} {kinds} write edge(s)", file, line,
                )
            )
        elif check == "deprecated_but_has_callers":
            is_dep = any("deprecated" in dec for dec in decorators) or any(
                re.search(p, doc_blob) for p in det.get("doc_patterns", [])
            )
            if not is_dep:
                continue
            caller_kinds = set(det.get("caller_edge_kinds", ["CALLS", "REFERENCES"]))
            callers: dict[str, int] = defaultdict(int)
            for _src, _, k in g.in_edges(sid, keys=True):
                if k in caller_kinds:
                    callers[k] += 1
            n = sum(callers.values())
            if n < det.get("min_callers", 1):
                continue
            kinds = ",".join(sorted(callers))
            out.append(
                _conflict_row(
                    sid, element_kind, det, "marked @deprecated",
                    f"{n} caller(s) via {kinds}", file, line,
                )
            )
        elif check == "docstring_arity_vs_signature":
            sig_params = h._param_names(d.get("signature"))
            if not docstrings:
                continue
            doc_params = _doc_param_count(" \n".join(s for s in docstrings))
            if doc_params == 0 or not sig_params:
                continue
            delta = abs(doc_params - len(sig_params))
            if delta < det.get("min_delta", 1):
                continue
            out.append(
                _conflict_row(
                    sid, element_kind, det, f"docstring documents {doc_params} param(s)",
                    f"signature declares {len(sig_params)}", file, line,
                )
            )
    return out


def _doc_param_count(doc: str) -> int:
    names = set()
    for m in _DOC_PARAM.finditer(doc):
        nm = m.group(1) or m.group(2) or m.group(3)
        if nm and nm.lower() not in ("returns", "return", "raises", "yields", "note", "example"):
            names.add(nm)
    return len(names)


def _conflict_row(sid, element_kind, det, claim, fact, file, line) -> dict:
    msg_claim = _clip(claim, 200)
    msg_fact = _clip(fact, 200)
    lr = _lr(line, line)
    h = blake3()
    for part in (sid, det["id"], msg_claim, msg_fact):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return {
        "conflict_id": h.hexdigest(length=12),
        "element_id": sid,
        "element_kind": element_kind,
        "detector_id": det["id"],
        "severity": det["severity"],
        "claim": msg_claim,
        "structural_fact": msg_fact,
        "file": file,
        "line_range": lr,
        "schema_version": SCHEMA_VERSION,
    }


# ───────────────────────── orchestration ─────────────────────────


def compute_intention(
    g: nx.MultiDiGraph,
    *,
    members_df: pl.DataFrame,
    interfaces_df: pl.DataFrame | None,
    data_shapes_df: pl.DataFrame | None,
    presentations_df: pl.DataFrame | None,
    repo_root: str | Path,
    tables: NormTables | None = None,
    detectors: dict | None = None,
    view: str = "similarity",
    max_role_members: int = 40,
    exclude_prefixes: Sequence[str] = (".claude/",),
    fts_path: str | Path | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, HarvestStats]:
    """Run the full mechanical harvest (§9.2). Returns
    ``(signals_df, load_df, conflicts_df, stats)``, all deterministically sorted
    so re-runs over the same inputs are byte-identical.
    """
    start = time.perf_counter()
    tables = tables or load_norm_tables()
    detectors = detectors or load_conflict_detectors()
    root = Path(repo_root).expanduser().resolve()
    h = Harvester(
        g,
        members_df=members_df,
        interfaces_df=interfaces_df,
        data_shapes_df=data_shapes_df,
        presentations_df=presentations_df,
        repo_root=root,
        tables=tables,
        detectors=detectors,
        exclude_prefixes=exclude_prefixes,
        fts_path=fts_path,
    )

    all_sigs: list[Sig] = []
    load_rows: list[dict] = []
    conflict_rows: list[dict] = []
    port_critical_elems: set[str] = set()

    # ── boundary exports (the primary element; S1 test-linkage acceptance) ──
    export_syms: list[str] = []
    if interfaces_df is not None and interfaces_df.height:
        prov = interfaces_df.filter(pl.col("direction") == "provides")
        seen: set[str] = set()
        for r in prov.iter_rows(named=True):
            ex = r.get("internal_export_symbol_id") or r.get("internal_symbol_id")
            if ex and ex not in seen and g.has_node(ex) and not h.excluded(ex):
                seen.add(ex)
                export_syms.append(ex)
    export_syms.sort()

    n_tested = 0
    for sid in export_syms:
        sigs = h.harvest_symbol(sid, "interface-export")
        all_sigs.extend(sigs)
        conflicts = _detect_conflicts(h, sid, "interface-export", sigs, is_boundary=True)
        conflict_rows.extend(conflicts)
        pc = any(c["severity"] == "port-critical" for c in conflicts)
        if pc:
            port_critical_elems.add(sid)
        d, d_drv = _determinacy_export(g, sid, tables, is_boundary=True)
        r, r_drv = _richness(sigs, tables, coherence_entropy=None)
        cls = _classify(d, r, tables, pc)
        if any(s.indicator_kind == "S1" for s in sigs):
            n_tested += 1
        load_rows.append(
            {
                "element_id": sid,
                "element_kind": "interface-export",
                "structural_determinacy": d,
                "intention_richness": r,
                "load_class": cls,
                "port_critical_conflict": pc,
                "drivers": d_drv + r_drv,
                "schema_version": SCHEMA_VERSION,
            }
        )

    # ── role classes (A5 naming pattern + member docstrings/tests → R) ──
    if presentations_df is not None and presentations_df.height:
        roles = presentations_df.filter(pl.col("view") == view)
        for r in roles.iter_rows(named=True):
            role_id = r["role_id"]
            members = [m for m in (r.get("members") or []) if not h.excluded(m)]
            if not members:
                continue
            lang = ""
            names: list[str] = []
            for m in members:
                nd = h._nd(m)
                lang = lang or (nd.get("language") or "")
                names.append(nd.get("short_name") or (nd.get("qualified_name") or m).split("::")[-1])
            content, ent = naming_pattern(names, tables, lang)
            file0 = h._nd(members[0]).get("file") if members else ""
            role_sigs: list[Sig] = [
                Sig(role_id, "role-class", "A5", "A", content, file0 or "", None, None,
                    tables.portability_defaults["A5"])
            ]
            # member docstrings + test linkage (capped) → richness
            for m in sorted(members)[:max_role_members]:
                md = h._nd(m)
                mfile = md.get("file") or md.get("file_path") or ""
                mline = md.get("line")
                lines, st = h._read_slice(m)
                if lines:
                    doc = _extract_docstring("\n".join(lines), md.get("language") or "")
                    if doc:
                        role_sigs.append(
                            Sig(role_id, "role-class", "S4", "S", _clip(doc, 300), mfile, mline, md.get("end_line") or mline, tables.portability_defaults["S4"])
                        )
                for tkey, tname in h._tests_linking(m):
                    if tkey.startswith("fts:"):
                        continue  # FTS complement is export-scoped; skip for role members
                    td = h._nd(tkey)
                    role_sigs.append(
                        Sig(role_id, "role-class", "S1", "S", f"test:{tname}",
                            td.get("file") or "", td.get("line"), td.get("line"), tables.portability_defaults["S1"])
                    )
            all_sigs.extend(role_sigs)
            d, d_drv = _determinacy_role(r, tables)
            rich, r_drv = _richness(role_sigs, tables, coherence_entropy=ent)
            cls = _classify(d, rich, tables, False)
            load_rows.append(
                {
                    "element_id": role_id,
                    "element_kind": "role-class",
                    "structural_determinacy": d,
                    "intention_richness": rich,
                    "load_class": cls,
                    "port_critical_conflict": False,
                    "drivers": d_drv + r_drv,
                    "schema_version": SCHEMA_VERSION,
                }
            )

    # ── data shapes (A4 type + field names) ──
    if data_shapes_df is not None and data_shapes_df.height:
        boundary = data_shapes_df.filter(pl.col("boundary"))
        seen_types: set[str] = set()
        for r in boundary.iter_rows(named=True):
            tid = r["type_symbol_id"]
            if h.excluded(tid):
                continue
            tqn = r.get("type_qualified_name") or tid
            td = h._nd(tid)
            file = td.get("file") or ""
            line = td.get("line")
            if tid not in seen_types:
                seen_types.add(tid)
                all_sigs.append(
                    Sig(tid, "data-shape", "A4", "A", f"type:{tqn.split('::')[-1]}", file, line, line,
                        tables.portability_defaults["A4"])
                )
            fn = r.get("field_name")
            if fn:
                all_sigs.append(
                    Sig(tid, "data-shape", "A4", "A", f"field:{fn}", file, line, line,
                        tables.portability_defaults["A4"])
                )

    # ── deterministic sort + frames ──
    sig_dicts = [s.row() for s in all_sigs]
    sig_dicts.sort(key=lambda d: (d["element_kind"], d["element_id"], d["indicator_kind"], d["content"], d["file"], d["line_range"]))
    load_rows.sort(key=lambda d: (d["element_kind"], d["element_id"]))
    conflict_rows.sort(key=lambda d: (d["element_id"], d["detector_id"], d["claim"], d["structural_fact"]))

    signals_df = pl.DataFrame(sig_dicts, schema=_signals_schema()).select(INTENTION_SIGNALS_COLUMNS)
    load_df = pl.DataFrame(load_rows, schema=_load_schema()).select(INTENTION_LOAD_COLUMNS)
    conflicts_df = pl.DataFrame(conflict_rows, schema=_conflicts_schema()).select(INTENTION_CONFLICTS_COLUMNS)

    stats = HarvestStats(
        n_signals=signals_df.height,
        n_load_rows=load_df.height,
        n_conflicts=conflicts_df.height,
        n_port_critical=sum(1 for c in conflict_rows if c["severity"] == "port-critical"),
        n_boundary_exports=len(export_syms),
        n_boundary_exports_tested=n_tested,
        test_linkage_fraction=round(n_tested / len(export_syms), 4) if export_syms else 0.0,
        by_indicator=dict(Counter(s["indicator_kind"] for s in sig_dicts)),
        by_portability=dict(Counter(s["portability_tier"] for s in sig_dicts)),
        load_classes=dict(Counter(r["load_class"] for r in load_rows)),
        total_seconds=round(time.perf_counter() - start, 3),
    )
    return signals_df, load_df, conflicts_df, stats


# ───────────────────────── schemas + writers ─────────────────────────


def _signals_schema() -> dict:
    return {
        "signal_id": pl.Utf8, "element_id": pl.Utf8, "element_kind": pl.Utf8,
        "indicator_kind": pl.Utf8, "tier": pl.Utf8, "content": pl.Utf8,
        "file": pl.Utf8, "line_range": pl.Utf8, "portability_tier": pl.Utf8,
        "schema_version": pl.Int64,
    }


def _load_schema() -> dict:
    return {
        "element_id": pl.Utf8, "element_kind": pl.Utf8,
        "structural_determinacy": pl.Float64, "intention_richness": pl.Float64,
        "load_class": pl.Utf8, "port_critical_conflict": pl.Boolean,
        "drivers": pl.List(pl.Utf8), "schema_version": pl.Int64,
    }


def _conflicts_schema() -> dict:
    return {
        "conflict_id": pl.Utf8, "element_id": pl.Utf8, "element_kind": pl.Utf8,
        "detector_id": pl.Utf8, "severity": pl.Utf8, "claim": pl.Utf8,
        "structural_fact": pl.Utf8, "file": pl.Utf8, "line_range": pl.Utf8,
        "schema_version": pl.Int64,
    }


def write_intention_signals(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(INTENTION_SIGNALS_COLUMNS).write_parquet(p)


def write_intention_load(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(INTENTION_LOAD_COLUMNS).write_parquet(p)


def write_intention_conflicts(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(INTENTION_CONFLICTS_COLUMNS).write_parquet(p)


def write_manifest(
    data_dir: str | Path,
    *,
    n_signals: int,
    n_load: int,
    n_conflicts: int,
    generated_at: str | None = None,
) -> Path:
    """Merge intention-harvest presence + counts into ``<data_dir>/ctkr/manifest.json``."""
    from datetime import UTC, datetime

    base = Path(data_dir).expanduser().resolve()
    manifest_path = base / "ctkr" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = {
        **existing,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(tz=UTC).isoformat(),
        "metacoding_data_dir": str(base),
        "intention_signals": True,
        "intention_load": True,
        "intention_conflicts": True,
        "n_intention_signals": int(n_signals),
        "n_intention_load": int(n_load),
        "n_intention_conflicts": int(n_conflicts),
    }
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "NormTables",
    "Harvester",
    "load_norm_tables",
    "load_conflict_detectors",
    "tokenize_identifier",
    "fold_affixes",
    "canonical_marker",
    "compute_intention",
    "HarvestStats",
    "write_intention_signals",
    "write_intention_load",
    "write_intention_conflicts",
    "write_manifest",
]
