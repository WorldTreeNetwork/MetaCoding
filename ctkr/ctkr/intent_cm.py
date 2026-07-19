"""Intent-CM (consistency-model-sensitivity) tag — port-loop Phase 3.

A source app built on a central authority silently assumes ACID transactions,
unique constraints, autoincrement ids, server-side access checks, and revision
locks (port-loop-plan.md Phase 3; decomposition-schema.md §6.2). This module tags
every such site with a **consistency-model-sensitivity** grade so a local-first /
eventually-consistent port knows exactly which invariants it must re-answer.

Two layers, mirroring the T5a/T5b split:

* **Mechanical seed** (:func:`scan_cm`, LM-free) — a versioned regex detector table
  (``data/cm_detectors.json``) over the source tree emits one ``intent_cm`` row per
  hit: ``(element_id, category, detector_id, cm_seed, evidence file:line, severity)``.
  Deterministic, byte-identical on re-run (no timestamps; content-addressed ids).
  Written to ``intent_cm.parquet``.
* **LM adjudication** (:func:`adjudicate_cm`, strong model) — for the seeded
  candidates, classify sensitivity ``{hard | soft | none}`` with a cited rationale,
  reusing the T5b structured-call + on-disk-cache pattern (evidence digest → cache
  key, so unchanged seeds re-run free). Written to ``intent_cm_adjudicated.jsonl``.

The **CM grade conditions only the brief's target-adaptation section, nothing else**
(Phase 3 mandate): it never alters the harvest or the intent. A run **with no target
profile still emits CM grades** — they describe the *source's* assumptions; the
optional target profile (:class:`TargetProfile`) only decides how the brief
*responds* to them (:func:`build_target_adaptation_notes`).

CM is a **separate axis from portability_tier** (decomposition-schema.md §6.1, open
decision (d)): an invariant can be intent-I (survives any stack) *and* CM-hard
(assumes central authority). This module never folds the two.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import blake3
import polars as pl
from pydantic import BaseModel, Field, field_validator

from ctkr.llm import LLMClient

logger = logging.getLogger("ctkr.intent_cm")

_DATA_DIR = Path(__file__).parent / "data"

SCHEMA_VERSION = 1

# Output artifact filenames under ``<data_dir>/ctkr/``.
INTENT_CM_FILE = "intent_cm.parquet"
INTENT_CM_ADJUDICATED_FILE = "intent_cm_adjudicated.jsonl"

INTENT_CM_COLUMNS: tuple[str, ...] = (
    "cm_id",
    "element_id",
    "element_kind",
    "category",
    "detector_id",
    "cm_seed",
    "language",
    "evidence",
    "file",
    "line_range",
    "schema_version",
    "source",  # "pattern" | "framework-implied"
)

# The strong adjudication model — same class the T5b conflict adjudication uses
# ("contradiction-finding is exactly where cheap models rubber-stamp", §8). Falls
# back to ``model`` when None so the mock/offline path stays single-model.
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_PROMPT_VERSION = "intent-cm:v1"
DEFAULT_TEMPERATURE = 0.0

# language → filename suffixes (lowercased). Kept small + explicit; a scan only
# reads files whose suffix maps to a language a detector declares.
_LANG_SUFFIXES: dict[str, tuple[str, ...]] = {
    "php": (".php", ".module", ".install", ".inc", ".theme"),
    "python": (".py",),
    "ts": (".ts", ".tsx"),
    "js": (".js", ".jsx", ".mjs", ".cjs"),
    "yaml": (".yml", ".yaml"),
    "sql": (".sql",),
}

# Directories never scanned (vendored deps, VCS, build output, worktree copies).
# Third-party code is not the source under decomposition — a uniqueness kwarg in
# numpy or a `SERIAL` token in a SQL lexer is not the SOURCE's CM assumption.
_SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        ".claude",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "__pycache__",
        # python virtualenvs / installed deps
        ".venv",
        "venv",
        "env",
        "site-packages",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
        # rust / other build output
        "target",
        ".next",
        "coverage",
    }
)

_CM_RANK = {"CM-hard": 0, "hard": 0, "CM-soft": 1, "soft": 1, "CM-none": 2, "none": 2, "": 3}


# ───────────────────────── detector table ─────────────────────────


@dataclass(frozen=True)
class Detector:
    id: str
    category: str
    languages: frozenset[str]
    pattern: re.Pattern[str]
    cm_seed: str
    element_kind_hint: str
    message: str
    file_globs: tuple[re.Pattern[str], ...]

    def file_ok(self, rel_path: str) -> bool:
        if not self.file_globs:
            return True
        return any(rx.search(rel_path) for rx in self.file_globs)


def _glob_to_re(glob: str) -> str:
    out = re.escape(glob)
    out = out.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return out.replace(r"\?", ".") + r"$"


def load_cm_detectors(path: str | Path | None = None) -> list[Detector]:
    p = Path(path) if path else _DATA_DIR / "cm_detectors.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    dets: list[Detector] = []
    for d in raw["detectors"]:
        dets.append(
            Detector(
                id=d["id"],
                category=d["category"],
                languages=frozenset(d["languages"]),
                pattern=re.compile(d["pattern"]),
                cm_seed=d["cm_seed"],
                element_kind_hint=d.get("element_kind_hint", "symbol"),
                message=d["message"],
                file_globs=tuple(re.compile(_glob_to_re(g)) for g in d.get("file_globs", [])),
            )
        )
    return dets


# ───────────────────────── enclosing-symbol anchoring ─────────────────────────

# PHP: nearest preceding `function name(` or `class/trait/interface Name`.
_PHP_FN = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_PHP_TYPE = re.compile(r"\b(?:class|trait|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
# Python: `def name(` / `class Name`.
_PY_FN = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_PY_TYPE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)")
# TS/JS: function/method/class.
_JS_FN = re.compile(
    r"\bfunction\s+([A-Za-z_$][\w$]*)|(?:^|\s)([A-Za-z_$][\w$]*)\s*(?:=\s*(?:async\s*)?\()"
)
_JS_TYPE = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")


def _enclosing_symbol(lines: Sequence[str], idx: int, language: str) -> tuple[str, str]:
    """Best-effort (name, kind) of the symbol enclosing 0-indexed line ``idx``.

    Regex over source, not a parser — a coverage approximation. Walks backwards to
    the nearest function, then class, then falls back to the file-level scope. Kind
    is ``php-function``/``php-class``/``function``/``class``/``config`` etc.
    """
    fn_re, type_re, fn_kind, type_kind = {
        "php": (_PHP_FN, _PHP_TYPE, "php-function", "php-class"),
        "python": (_PY_FN, _PY_TYPE, "function", "class"),
        "ts": (_JS_FN, _JS_TYPE, "function", "class"),
        "js": (_JS_FN, _JS_TYPE, "function", "class"),
    }.get(language, (None, None, "symbol", "symbol"))
    if fn_re is not None:
        for j in range(idx, -1, -1):
            m = fn_re.search(lines[j])
            if m:
                name = next((g for g in m.groups() if g), None)
                if name:
                    return name, fn_kind
        for j in range(idx, -1, -1):
            m = type_re.search(lines[j]) if type_re else None
            if m:
                return m.group(1), type_kind
    return "", "config" if language == "yaml" else "file"


# ───────────────────────── seed rows ─────────────────────────


@dataclass
class CMSeed:
    element_id: str
    element_kind: str
    category: str
    detector_id: str
    cm_seed: str
    language: str
    evidence: str
    file: str
    line: int

    def cm_id(self) -> str:
        h = blake3.blake3()
        for part in (
            self.element_id,
            self.detector_id,
            self.category,
            self.evidence,
            self.file,
            str(self.line),
        ):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest(length=12)

    def row(self, *, source: str = "pattern") -> dict:
        return {
            "cm_id": self.cm_id(),
            "element_id": self.element_id,
            "element_kind": self.element_kind,
            "category": self.category,
            "detector_id": self.detector_id,
            "cm_seed": self.cm_seed,
            "language": self.language,
            "evidence": self.evidence,
            "file": self.file,
            "line_range": str(self.line),
            "schema_version": SCHEMA_VERSION,
            "source": source,
        }


@dataclass
class ScanStats:
    n_files_scanned: int = 0
    n_seeds: int = 0
    n_elements: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_seed: dict[str, int] = field(default_factory=dict)
    by_language: dict[str, int] = field(default_factory=dict)
    by_detector: dict[str, int] = field(default_factory=dict)
    total_seconds: float = 0.0


def _clip(s: str, n: int = 200) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _lang_of(path: Path) -> str | None:
    suf = path.suffix.lower()
    name = path.name.lower()
    for lang, sufs in _LANG_SUFFIXES.items():
        if suf in sufs or name.endswith(sufs):
            return lang
    return None


def _skip(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    return any(p in _SKIP_DIR_PARTS for p in rel_parts)


def scan_cm(
    source_root: str | Path,
    *,
    detectors: Sequence[Detector] | None = None,
    id_prefix: str = "",
) -> tuple[pl.DataFrame, ScanStats]:
    """Mechanically seed intent-CM rows over a source tree (LM-free, deterministic).

    Walks every file whose suffix maps to a language some detector declares, applies
    that language's detectors line-by-line, and anchors each hit to its enclosing
    symbol. Returns ``(intent_cm_df, stats)`` with rows deterministically sorted so
    re-runs over the same tree are byte-identical.

    ``id_prefix`` is prepended to ``element_id`` (e.g. a repo name) so seeds from
    different corpora never collide.
    """
    start = time.perf_counter()
    root = Path(source_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"source-root {root} does not exist")
    dets = list(detectors) if detectors is not None else load_cm_detectors()
    by_lang: dict[str, list[Detector]] = defaultdict(list)
    for d in dets:
        for lang in d.languages:
            by_lang[lang].append(d)

    seeds: list[CMSeed] = []
    stats = ScanStats()

    for path in sorted(root.rglob("*")):
        if not path.is_file() or _skip(path, root):
            continue
        lang = _lang_of(path)
        if lang is None or lang not in by_lang:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Cheap pre-filter: skip a file none of the language's detectors can match.
        applicable = [d for d in by_lang[lang]]
        lines = text.splitlines()
        rel = _rel(path, root)
        matched_any = False
        for i, ln in enumerate(lines):
            for d in applicable:
                if not d.file_ok(rel):
                    continue
                if d.pattern.search(ln):
                    name, kind = (
                        _enclosing_symbol(lines, i, lang)
                        if lang != "yaml"
                        else (path.stem, "config")
                    )
                    anchor = name or path.stem
                    element_id = f"{id_prefix}{d.category}:{anchor}:{rel}"
                    seeds.append(
                        CMSeed(
                            element_id=element_id,
                            element_kind=d.element_kind_hint if name or lang == "yaml" else "file",
                            category=d.category,
                            detector_id=d.id,
                            cm_seed=d.cm_seed,
                            language=lang,
                            evidence=_clip(ln.strip()),
                            file=rel,
                            line=i + 1,
                        )
                    )
                    matched_any = True
        if matched_any or applicable:
            stats.n_files_scanned += 1

    rows = [s.row() for s in seeds]
    rows.sort(
        key=lambda r: (
            r["category"],
            r["element_id"],
            r["detector_id"],
            r["file"],
            int(r["line_range"]) if r["line_range"].isdigit() else 0,
            r["evidence"],
        )
    )
    df = pl.DataFrame(rows, schema=_cm_schema()).select(INTENT_CM_COLUMNS)

    stats.n_seeds = df.height
    stats.n_elements = df["element_id"].n_unique() if df.height else 0
    stats.by_category = dict(Counter(r["category"] for r in rows))
    stats.by_seed = dict(Counter(r["cm_seed"] for r in rows))
    stats.by_language = dict(Counter(r["language"] for r in rows))
    stats.by_detector = dict(Counter(r["detector_id"] for r in rows))
    stats.total_seconds = round(time.perf_counter() - start, 3)
    return df, stats


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _cm_schema() -> dict:
    return {
        "cm_id": pl.Utf8,
        "element_id": pl.Utf8,
        "element_kind": pl.Utf8,
        "category": pl.Utf8,
        "detector_id": pl.Utf8,
        "cm_seed": pl.Utf8,
        "language": pl.Utf8,
        "evidence": pl.Utf8,
        "file": pl.Utf8,
        "line_range": pl.Utf8,
        "schema_version": pl.Int64,
        "source": pl.Utf8,  # "pattern" | "framework-implied"
    }


# ───────────────────────── framework-implied CM ─────────────────────────────────────────


@dataclass(frozen=True)
class FrameworkImpliedFact:
    """One CM implication that a detected framework carries for the entire source tree."""

    id: str
    category: str
    cm_seed: str  # "CM-hard" | "CM-soft"
    severity_default: str  # "hard" | "soft"
    rationale: str


@dataclass(frozen=True)
class FrameworkSpec:
    id: str
    name: str
    implied_facts: tuple[FrameworkImpliedFact, ...]


def load_framework_implied(path: str | Path | None = None) -> list[FrameworkSpec]:
    """Load the ``framework_implied`` section from ``cm_detectors.json``.

    Returns a list of :class:`FrameworkSpec` objects (one per framework). Returns
    ``[]`` gracefully when the section is absent (forward-compat with older table
    versions shipped before this feature).
    """
    p = Path(path) if path else _DATA_DIR / "cm_detectors.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    fw_section = raw.get("framework_implied", {})
    specs: list[FrameworkSpec] = []
    for fw in fw_section.get("frameworks", []):
        facts = tuple(
            FrameworkImpliedFact(
                id=f["id"],
                category=f["category"],
                cm_seed=f["cm_seed"],
                severity_default=f["severity_default"],
                rationale=f["rationale"],
            )
            for f in fw.get("implied_facts", [])
        )
        specs.append(FrameworkSpec(id=fw["id"], name=fw["name"], implied_facts=facts))
    return specs


def detect_frameworks(source_root: str | Path) -> list[str]:
    """Return sorted list of framework IDs detected in *source_root* (filesystem only, LM-free).

    Implements the detection predicates declared in the ``framework_implied`` section of
    ``cm_detectors.json`` — file_glob, file_exists, file_content. Logic='any' means
    OR over predicates (any match → framework detected). Conservative: a miss is safe
    (falls back to zero implied rows); a false-positive would emit CM noise.

    Detected IDs: ``"drupal"``, ``"django"``, ``"rails"`` (others if added to the table).
    """
    root = Path(source_root).expanduser().resolve()
    detected: set[str] = set()

    # Drupal: presence of *.info.yml (module descriptor) is sufficient.
    # Content check for Drupal namespace done as tiebreaker for ambiguous repos.
    if any(True for p in root.rglob("*.info.yml") if not _skip(p, root)):
        detected.add("drupal")

    # Django: manage.py at root OR requirements*.txt / pyproject.toml mentioning Django.
    if (root / "manage.py").exists():
        detected.add("django")
    if "django" not in detected:
        for req in list(root.glob("requirements*.txt")) + [root / "pyproject.toml"]:
            if req.exists():
                try:
                    if re.search(r"(?i)\bdjango\b", req.read_text(encoding="utf-8", errors="replace")):
                        detected.add("django")
                        break
                except OSError:
                    pass

    # Rails: Gemfile containing 'rails' or 'activerecord', OR application_record.rb present.
    gemfile = root / "Gemfile"
    if gemfile.exists():
        try:
            if re.search(r"(?i)\brails\b|\bactiverecord\b", gemfile.read_text(encoding="utf-8", errors="replace")):
                detected.add("rails")
        except OSError:
            pass
    if "rails" not in detected and any(True for _ in root.rglob("application_record.rb") if not _skip(_, root)):
        detected.add("rails")

    return sorted(detected)


def scan_framework_implied(
    source_root: str | Path,
    *,
    id_prefix: str = "",
    detectors_path: str | Path | None = None,
) -> tuple[pl.DataFrame, list[str]]:
    """Emit framework-implied CM rows for any framework detected in *source_root*.

    Returns ``(df, detected_framework_ids)``. The DataFrame has the **same schema** as
    :func:`scan_cm` output (``source='framework-implied'``). These rows are NOT sent to
    the LM adjudicator — the implication IS the classification.

    **element_id design** — framework-scope sentinel, one row per (framework, category):
    ``{id_prefix}framework-implied:{framework_id}:{category}``.
    Rationale: the implication applies uniformly to every module in the codebase; a
    per-module breakdown would cause N×M row explosion without adding discriminating
    information (every Drupal module inherits the same ACID assumption). A single sentinel
    row per category is the minimal representation and matches how adjudication collapses
    per-element verdicts. Downstream callers may filter by category to surface the fact
    in module-specific briefs.
    """
    root = Path(source_root).expanduser().resolve()
    specs_by_id = {fw.id: fw for fw in load_framework_implied(detectors_path)}
    detected = detect_frameworks(root)

    rows: list[dict] = []
    for fw_id in detected:
        spec = specs_by_id.get(fw_id)
        if spec is None:
            logger.debug("detected framework %r has no implied-facts entry in table; skipping", fw_id)
            continue
        for fact in spec.implied_facts:
            element_id = f"{id_prefix}framework-implied:{fw_id}:{fact.category}"
            evidence = f"framework-implied:{fact.id}"
            seed = CMSeed(
                element_id=element_id,
                element_kind="framework",
                category=fact.category,
                detector_id=fact.id,
                cm_seed=fact.cm_seed,
                language="",
                evidence=evidence,
                file="framework",
                line=0,
            )
            r = seed.row(source="framework-implied")
            rows.append(r)

    rows.sort(key=lambda r: (r["category"], r["element_id"], r["detector_id"]))
    schema = _cm_schema()
    if rows:
        df = pl.DataFrame(rows, schema=schema).select(INTENT_CM_COLUMNS)
    else:
        df = pl.DataFrame(schema={k: schema[k] for k in INTENT_CM_COLUMNS})
    return df, detected


# ───────────────────────── heuristic pre-screen (cheap none filter) ─────────────────────────

# Detectors empirically found to be high-recall / low-precision for single-seed elements:
# a hit from one of these detectors alone is very likely to be adjudicated 'none' by the
# strong model. Calibrated against the i57 farmOS run (125 adjudicated, 43 none; 12 of those
# were single-seed config-route-permission elements consistently called 'none').
_DEFAULT_SHALLOW_DETECTORS: frozenset[str] = frozenset({"config-route-permission"})


def heuristic_prescreen_cm(
    cm_df: pl.DataFrame,
    *,
    enabled: bool = True,
    shallow_detectors: frozenset[str] = _DEFAULT_SHALLOW_DETECTORS,
    max_seeds_per_element: int = 1,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fast heuristic pre-screen for obvious 'none' cases before LM adjudication.

    Returns ``(send_to_llm, presuppose_none)``. Elements in *presuppose_none* are
    predicted 'none' and should be emitted with
    ``adjudication_source='heuristic-prescreen'`` — no model call performed.

    **Heuristic**: an element is pre-screened as 'none' when ALL of:

    1. ``enabled`` is True (the dial — set ``enabled=False`` to send everything to LM).
    2. Seed count for the element ≤ ``max_seeds_per_element``.
    3. Every seed has ``cm_seed == 'CM-soft'`` (no hard mechanical prior).
    4. Every seed's ``detector_id`` is in ``shallow_detectors``.

    Conservative by design: only elements where every signal is weak (soft prior, single
    seed) AND from a known low-precision detector are screened. The false-negative rate on
    the i57 farmOS run is zero for the default ``shallow_detectors`` set.
    """
    if not enabled or cm_df.height == 0:
        return cm_df, cm_df.filter(pl.lit(False))

    grouped = (
        cm_df.group_by("element_id")
        .agg(
            pl.len().alias("n_seeds"),
            pl.col("cm_seed").alias("cm_seeds"),
            pl.col("detector_id").alias("detector_ids"),
        )
    )

    screen_eids: set[str] = set()
    for r in grouped.iter_rows(named=True):
        if r["n_seeds"] > max_seeds_per_element:
            continue
        if any(s != "CM-soft" for s in r["cm_seeds"]):
            continue
        if not all(d in shallow_detectors for d in r["detector_ids"]):
            continue
        screen_eids.add(r["element_id"])

    if not screen_eids:
        return cm_df, cm_df.filter(pl.lit(False))

    eid_list = list(screen_eids)
    presuppose_none = cm_df.filter(pl.col("element_id").is_in(eid_list))
    send_to_llm = cm_df.filter(~pl.col("element_id").is_in(eid_list))
    return send_to_llm, presuppose_none


# ───────────────────────── LM adjudication (strong model, cached) ─────────────────────────


class _CMVerdictOut(BaseModel):
    """One per-category adjudication verdict (strong model)."""

    category: str = Field(description="The CM category being classified.")
    sensitivity: Literal["hard", "soft", "none"] = Field(
        description="hard = the invariant CANNOT hold under eventual consistency "
        "without a chosen resolution strategy (unique/monotonic ids, single-writer "
        "locks, atomic multi-write); soft = holds EVENTUALLY, transient violation "
        "tolerable (access snapshots, revision history, conservation sums); none = "
        "independent of the consistency model, or a mechanical false positive."
    )
    rationale: str = Field(
        description="One sentence: WHY this grade, naming the specific assumption "
        "and its distributed consequence. Cite the evidence line."
    )
    citation: str = Field(
        default="", description="The file:line of the evidence this verdict rests on."
    )


class CMAdjudicationOut(BaseModel):
    """The strong model's verdicts for one element's seeded CM candidates."""

    verdicts: list[_CMVerdictOut] = Field(default_factory=list)

    @field_validator("verdicts", mode="before")
    @classmethod
    def _lists(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return []
            return parsed if isinstance(parsed, list) else [parsed]
        return v if isinstance(v, list) else []


class AdjudicatedCM(BaseModel):
    """One adjudicated intent-CM element (``intent_cm_adjudicated.jsonl``).

    Groups an element's seeds and attaches the strong model's per-category
    sensitivity verdict. ``adjudication_id`` is content-addressed over the evidence
    digest + provenance and is independent of the LLM output text (the T5 re-run
    identity contract). Deterministic given the seeds + prompt_version + model.
    """

    adjudication_id: str
    element_id: str
    element_kind: str
    categories: list[str]
    cm_seed: str  # strongest mechanical prior over the element's seeds
    sensitivity: str  # strongest adjudicated grade: hard | soft | none
    per_category: dict[str, str] = Field(default_factory=dict)  # category → hard|soft|none
    rationale: str = ""
    evidence_refs: list[str] = Field(default_factory=list)  # cm_ids
    citations: list[str] = Field(default_factory=list)  # file:line
    evidence_digest: str = ""
    llm_model: str
    prompt_version: str
    schema_version: int = SCHEMA_VERSION
    generated_at: str
    adjudication_source: str = "llm"  # "llm" | "framework-implied" | "heuristic-prescreen"


_SYS_ADJUDICATE = (
    "You grade CONSISTENCY-MODEL SENSITIVITY for a source built on a central "
    "authority (ACID transactions, unique constraints, autoincrement ids, "
    "server-side access checks, revision/locks) that is being re-implemented for a "
    "LOCAL-FIRST, eventually-consistent target (event log + materialized views, "
    "sync with selective disclosure). A mechanical detector flagged the sites below "
    "as candidates. For each CM category, decide whether the invariant is:\n"
    "- hard: it CANNOT hold under eventual consistency without a chosen resolution "
    "strategy (a convergence rule, a coordination layer, or a conscious weakening);\n"
    "- soft: it holds EVENTUALLY and a transient violation is tolerable;\n"
    "- none: it is independent of the consistency model, OR the mechanical flag is a "
    "false positive.\n"
    "Be conservative and specific: name the assumption and its distributed "
    "consequence, cite the evidence line. Do NOT propose the port's design — only "
    "grade the source's assumption."
)


def _fmt_seeds(seeds: Sequence[dict]) -> list[str]:
    lines: list[str] = []
    for s in seeds:
        lines.append(
            f"- [{s['category']} / seed {s['cm_seed']} / {s['detector_id']}] "
            f"{s['evidence']}  ({s['file']}:{s['line_range']})"
        )
    return lines


def render_adjudication_prompt(element_id: str, element_kind: str, seeds: Sequence[dict]) -> str:
    cats = sorted({s["category"] for s in seeds})
    return "\n".join(
        [
            f"# Element `{element_id}` ({element_kind})",
            "",
            f"CM categories flagged here: {', '.join(cats)}",
            "",
            "## Flagged sites (evidence)",
            *_fmt_seeds(seeds),
            "",
            "Emit a CMAdjudicationOut: one verdict per DISTINCT category above "
            "(hard | soft | none) with a cited one-sentence rationale.",
        ]
    )


def _cm_evidence_digest(element_id: str, element_kind: str, seeds: Sequence[dict]) -> str:
    payload = {
        "element_id": element_id,
        "element_kind": element_kind,
        "seeds": sorted(
            [
                s["category"],
                s["detector_id"],
                s["cm_seed"],
                s["evidence"],
                s["file"],
                s["line_range"],
            ]
            for s in seeds
        ),
    }
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return blake3.blake3(canon.encode("utf-8")).hexdigest()


def _adjudication_id(element_id: str, digest: str, *, prompt_version: str, model: str) -> str:
    canon = json.dumps(
        [element_id, digest, prompt_version, model], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "cm:" + blake3.blake3(canon).hexdigest()[:24]


def _strongest(grades: Sequence[str]) -> str:
    return min(grades, key=lambda g: _CM_RANK.get(g, 9)) if grades else ""


@dataclass
class AdjudicateStats:
    n_elements: int = 0
    n_calls: int = 0
    n_failed_calls: int = 0
    cache_hits: int = 0
    by_sensitivity: dict[str, int] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    total_seconds: float = 0.0


def adjudicate_cm(
    cm_df: pl.DataFrame,
    client: LLMClient,
    *,
    model: str = DEFAULT_MODEL,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    temperature: float = DEFAULT_TEMPERATURE,
    max_elements: int | None = None,
    only_seeds: Sequence[str] = ("CM-hard", "CM-soft"),
    max_tokens: int = 900,
    use_heuristic_filter: bool = False,
    shallow_detectors: frozenset[str] | None = None,
) -> tuple[list[AdjudicatedCM], AdjudicateStats]:
    """Adjudicate the seeded CM candidates with the strong model (§8 pattern).

    Routes only the flagged subset (``only_seeds`` — CM-hard/CM-soft by default;
    CM-none seeds are false-positive-prone and skipped to keep spend on the subset
    that earns it). One structured call per element, cached by the evidence digest,
    so unchanged seeds re-run free + byte-identical. Degrades one element on a
    provider/validation failure rather than aborting the batch.

    **Framework-implied rows** (``source='framework-implied'``): bypassed entirely —
    the implication IS the classification; ``adjudication_source='framework-implied'``
    is set in the output record.

    **Heuristic pre-screen** (``use_heuristic_filter=True``): single-seed soft
    elements from shallow detectors are predicted 'none' before the LM call;
    ``adjudication_source='heuristic-prescreen'`` is set. Off by default since
    2026-07-19: the first human calibration confirmed both of its farmOS false
    negatives were real CM signal (MetaCoding-9h5.14), and Luna-priced
    adjudication (~$0.001/element) no longer justifies any FN rate. Re-enable
    with ``use_heuristic_filter=True`` only for token-starved bulk scans.
    """
    start = time.perf_counter()
    stats = AdjudicateStats()
    want = set(only_seeds)
    generated_at_ts = datetime.now(tz=UTC).isoformat()

    # ── Step 1: separate framework-implied rows (no LM needed) ──────────────────
    out: list[AdjudicatedCM] = []
    has_source_col = "source" in cm_df.columns
    if has_source_col:
        fw_mask = pl.col("source") == "framework-implied"
        fw_df = cm_df.filter(fw_mask)
        cm_df = cm_df.filter(~fw_mask)
        if fw_df.height > 0:
            fw_by_el: dict[str, list[dict]] = defaultdict(list)
            fw_kind_by: dict[str, str] = {}
            for r in fw_df.iter_rows(named=True):
                fw_by_el[r["element_id"]].append(r)
                fw_kind_by[r["element_id"]] = r["element_kind"]
            for fw_eid in sorted(fw_by_el):
                seeds = fw_by_el[fw_eid]
                kind = fw_kind_by[fw_eid]
                digest = _cm_evidence_digest(fw_eid, kind, seeds)
                aid = _adjudication_id(fw_eid, digest, prompt_version=prompt_version, model="framework-implied")
                per_cat = {s["category"]: s["cm_seed"].replace("CM-", "").lower() for s in seeds}
                sensitivity = _strongest(list(per_cat.values()))
                stats.by_sensitivity[sensitivity] = stats.by_sensitivity.get(sensitivity, 0) + 1
                out.append(AdjudicatedCM(
                    adjudication_id=aid,
                    element_id=fw_eid,
                    element_kind=kind,
                    categories=sorted(per_cat),
                    cm_seed=_strongest([s["cm_seed"] for s in seeds]),
                    sensitivity=sensitivity,
                    per_category=per_cat,
                    rationale="; ".join(_clip(s["evidence"], 150) for s in seeds),
                    evidence_refs=sorted(s["cm_id"] for s in seeds),
                    citations=[],
                    evidence_digest=digest,
                    llm_model="framework-implied",
                    prompt_version=prompt_version,
                    generated_at=generated_at_ts,
                    adjudication_source="framework-implied",
                ))

    # ── Step 2: heuristic pre-screen (predict obvious 'none' without LM) ─────────
    eff_shallow = frozenset(shallow_detectors) if shallow_detectors is not None else _DEFAULT_SHALLOW_DETECTORS
    if use_heuristic_filter and cm_df.height > 0:
        cm_df, presuppose_none_df = heuristic_prescreen_cm(
            cm_df, enabled=True, shallow_detectors=eff_shallow
        )
        if presuppose_none_df.height > 0:
            hn_by_el: dict[str, list[dict]] = defaultdict(list)
            hn_kind_by: dict[str, str] = {}
            for r in presuppose_none_df.iter_rows(named=True):
                hn_by_el[r["element_id"]].append(r)
                hn_kind_by[r["element_id"]] = r["element_kind"]
            for hn_eid in sorted(hn_by_el):
                seeds = hn_by_el[hn_eid]
                kind = hn_kind_by[hn_eid]
                digest = _cm_evidence_digest(hn_eid, kind, seeds)
                aid = _adjudication_id(hn_eid, digest, prompt_version=prompt_version, model=model)
                sensitivity = "none"
                per_cat = {s["category"]: "none" for s in seeds}
                stats.by_sensitivity[sensitivity] = stats.by_sensitivity.get(sensitivity, 0) + 1
                out.append(AdjudicatedCM(
                    adjudication_id=aid,
                    element_id=hn_eid,
                    element_kind=kind,
                    categories=sorted(per_cat),
                    cm_seed=_strongest([s["cm_seed"] for s in seeds]),
                    sensitivity=sensitivity,
                    per_category=per_cat,
                    rationale="heuristic-prescreen: single-seed shallow-detector element, "
                               "predicted none without LM call.",
                    evidence_refs=sorted(s["cm_id"] for s in seeds),
                    citations=sorted({f"{s['file']}:{s['line_range']}" for s in seeds})[:4],
                    evidence_digest=digest,
                    llm_model=model,
                    prompt_version=prompt_version,
                    generated_at=generated_at_ts,
                    adjudication_source="heuristic-prescreen",
                ))

    # ── Step 3: normal LM adjudication for the remaining elements ────────────────
    by_el: dict[str, list[dict]] = defaultdict(list)
    kind_by: dict[str, str] = {}
    for r in cm_df.iter_rows(named=True):
        if r["cm_seed"] not in want:
            continue
        by_el[r["element_id"]].append(r)
        kind_by[r["element_id"]] = r["element_kind"]

    element_ids = sorted(by_el)
    if max_elements is not None:
        element_ids = element_ids[:max_elements]
    stats.n_elements = len(element_ids) + len(out)

    for eid in element_ids:
        seeds = by_el[eid]
        kind = kind_by[eid]
        digest = _cm_evidence_digest(eid, kind, seeds)
        aid = _adjudication_id(eid, digest, prompt_version=prompt_version, model=model)
        prompt = render_adjudication_prompt(eid, kind, seeds)
        parsed: CMAdjudicationOut | None = None
        try:
            res = client.complete_structured(
                prompt,
                schema=CMAdjudicationOut,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system=_SYS_ADJUDICATE,
            )
            parsed = res.parsed
            stats.total_cost_usd += res.cost_estimate_usd
            stats.cache_hits += 1 if res.cache_hit else 0
            stats.n_calls += 1
        except Exception as e:  # noqa: BLE001 — provider/validation errors vary
            logger.warning("cm adjudication failed for %s: %s", eid, e)
            stats.n_failed_calls += 1

        per_cat: dict[str, str] = {}
        rationales: list[str] = []
        citations: list[str] = []
        if parsed is not None:
            valid_cats = {s["category"] for s in seeds}
            for v in parsed.verdicts:
                if v.category in valid_cats:
                    per_cat[v.category] = v.sensitivity
                    if v.rationale:
                        rationales.append(f"[{v.category}] {v.rationale}")
                    if v.citation:
                        citations.append(v.citation)
        # Any flagged category the model didn't return keeps its mechanical prior,
        # downcased ("CM-hard" → "hard"), so the record is never silently empty.
        for s in seeds:
            per_cat.setdefault(s["category"], s["cm_seed"].replace("CM-", ""))
        sensitivity = _strongest(list(per_cat.values()))
        stats.by_sensitivity[sensitivity] = stats.by_sensitivity.get(sensitivity, 0) + 1

        out.append(
            AdjudicatedCM(
                adjudication_id=aid,
                element_id=eid,
                element_kind=kind,
                categories=sorted(per_cat),
                cm_seed=_strongest([s["cm_seed"] for s in seeds]),
                sensitivity=sensitivity,
                per_category=per_cat,
                rationale=" ".join(rationales),
                evidence_refs=sorted({s["cm_id"] for s in seeds}),
                citations=sorted(set(citations))
                or sorted({f"{s['file']}:{s['line_range']}" for s in seeds})[:4],
                evidence_digest=digest,
                llm_model=model,
                prompt_version=prompt_version,
                generated_at=datetime.now(tz=UTC).isoformat(),
            )
        )

    out.sort(key=lambda a: a.adjudication_id)
    stats.total_cost_usd = round(stats.total_cost_usd, 6)
    stats.total_seconds = round(time.perf_counter() - start, 3)
    return out, stats


# ───────────────────────── target profile (OPTIONAL everywhere) ─────────────────────────


@dataclass(frozen=True)
class TargetProfile:
    """A re-implementation target's consistency profile (docs/design/target-profile.md).

    OPTIONAL input: every scanner/adjudicator works without one. A profile only
    conditions the brief's target-adaptation section — it decides how the brief
    *responds* to the source's CM grades, never the grades themselves.
    """

    id: str
    name: str
    consistency_model: str
    architecture: list[str]
    sync: str
    summary: str
    # sensitivity class → ordered decision menu (the options the port must choose from)
    decision_menu: dict[str, list[str]]
    capabilities: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def _default_menu() -> dict[str, list[str]]:
        return {
            "hard": [
                "preserve-via-convergence-rule",
                "move-to-coordination-layer",
                "weaken-to-eventual",
            ],
            "soft": ["preserve-as-eventual-invariant", "move-to-disclosure-layer"],
            "none": ["port-verbatim"],
        }

    @classmethod
    def load(cls, path: str | Path) -> TargetProfile:
        import yaml

        raw = yaml.safe_load(Path(path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"target profile {path} is not a mapping")
        tp = raw.get("target_profile", raw)
        menu = tp.get("decision_menu") or {}
        merged = cls._default_menu()
        for k, v in menu.items():
            if isinstance(v, list):
                merged[k] = [str(x) for x in v]
        return cls(
            id=str(tp.get("id", "unnamed-target")),
            name=str(tp.get("name", tp.get("id", "unnamed target"))),
            consistency_model=str(tp.get("consistency_model", "eventual")),
            architecture=[str(x) for x in (tp.get("architecture") or [])],
            sync=str(tp.get("sync", "")),
            summary=str(tp.get("summary", "")),
            decision_menu=merged,
            capabilities=dict(tp.get("capabilities") or {}),
        )


# ───────────────────────── target adaptation notes (deterministic render) ─────────────────────────


_CATEGORY_ASSUMPTION = {
    "transaction": "the source groups writes in an ACID transaction "
    "(atomic + isolated by a central store)",
    "unique-constraint": "the source relies on the store enforcing uniqueness at write time",
    "autoincrement-id": "the source relies on a server-assigned sequential/monotonic id",
    "access-check": "the source answers 'who may see/do what' with a synchronous "
    "server-side check against central state",
    "revision-lock": "the source assumes a single serialized write history "
    "(revisions / locks) managed centrally",
}


def build_target_adaptation_notes(
    adjudicated: Sequence[AdjudicatedCM],
    profile: TargetProfile,
    *,
    element_filter: set[str] | None = None,
    include_none: bool = False,
) -> list[str]:
    """Render the 'Target adaptation notes' markdown lines (Phase 3, brief §8).

    TARGET-CONDITIONED JUDGMENT — clearly labeled, NEVER mixed into source-derived
    INTENT. Per intent-CM-tagged element: the source assumption, the adjudicated
    sensitivity class, and the profile's decision menu for that class. Deterministic
    (no LLM at render). Returns ``[]`` when there is nothing to adapt.

    ``element_filter`` restricts to a subset of ``element_id``s (e.g. one subsystem);
    ``None`` renders all. CM-none elements are excluded unless ``include_none``.
    """
    rows = [
        a
        for a in adjudicated
        if (element_filter is None or a.element_id in element_filter)
        and (include_none or a.sensitivity in ("hard", "soft"))
    ]
    if not rows:
        return []
    rows = sorted(rows, key=lambda a: (_CM_RANK.get(a.sensitivity, 9), a.element_id))

    L: list[str] = []
    L.append("## Target adaptation notes")
    L.append("")
    L.append(
        f"> **Target-conditioned judgment for `{profile.id}` — {profile.name}.** These notes "
        f"are NOT source-derived INTENT: they say how *this* {profile.consistency_model}-"
        f"consistency target ({', '.join(profile.architecture) or 'local-first'}"
        f"{'; sync: ' + profile.sync if profile.sync else ''}) must re-answer the source's "
        f"central-authority assumptions. A port to a different target would re-answer "
        f"differently; a port that keeps the central authority ignores this section entirely. "
        f"The intent-CM grades below describe the SOURCE and stand without any profile."
    )
    L.append("")
    n_hard = sum(1 for a in rows if a.sensitivity == "hard")
    n_soft = sum(1 for a in rows if a.sensitivity == "soft")
    L.append(
        f"_{len(rows)} consistency-model-sensitive element(s): "
        f"**{n_hard} hard** (must choose a resolution strategy), {n_soft} soft "
        f"(preserve as eventual)._"
    )
    L.append("")
    icon = {"hard": "⛔ **CM-hard**", "soft": "◐ CM-soft", "none": "· CM-none"}
    for a in rows:
        assumptions = "; ".join(
            _CATEGORY_ASSUMPTION.get(c, c) for c in a.categories
        )
        menu = profile.decision_menu.get(a.sensitivity, [])
        cite = f" ({'; '.join(a.citations[:3])})" if a.citations else ""
        L.append(f"### {icon.get(a.sensitivity, a.sensitivity)} `{a.element_id}`")
        L.append(f"- **Source assumption** — {assumptions}.{cite}")
        L.append(f"- **Sensitivity** — {a.sensitivity} ({', '.join(a.categories)}).")
        if a.rationale:
            L.append(f"  - _{_clip(a.rationale, 300)}_")
        if menu:
            L.append(f"- **Decision menu** — {' / '.join(menu)}.")
            L.append(
                "  - _Choose one and record it as a Port Decision; the port-verifier "
                "treats the choice as an expected delta, not a failure._"
            )
        L.append("")
    return L


# ───────────────────────── IO + manifest ─────────────────────────


def write_intent_cm(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(INTENT_CM_COLUMNS).write_parquet(p)


def write_adjudicated_jsonl(rows: Sequence[AdjudicatedCM], out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: r.adjudication_id)
    with p.open("w", encoding="utf-8") as f:
        for r in ordered:
            f.write(r.model_dump_json() + "\n")


def read_adjudicated_jsonl(path: str | Path) -> list[AdjudicatedCM]:
    p = Path(path).expanduser().resolve()
    out: list[AdjudicatedCM] = []
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(AdjudicatedCM.model_validate_json(line))
    return out


def write_manifest(
    data_dir: str | Path,
    *,
    n_seeds: int,
    n_adjudicated: int,
    generated_at: str | None = None,
) -> Path:
    """Merge intent-CM presence + counts into ``<data_dir>/ctkr/manifest.json`` (additive)."""
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
        "intent_cm": True,
        "intent_cm_adjudicated": n_adjudicated > 0,
        "n_intent_cm_seeds": int(n_seeds),
        "n_intent_cm_adjudicated": int(n_adjudicated),
    }
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "SCHEMA_VERSION",
    "INTENT_CM_FILE",
    "INTENT_CM_ADJUDICATED_FILE",
    "INTENT_CM_COLUMNS",
    "Detector",
    "load_cm_detectors",
    "CMSeed",
    "ScanStats",
    "scan_cm",
    # framework-implied
    "FrameworkImpliedFact",
    "FrameworkSpec",
    "load_framework_implied",
    "detect_frameworks",
    "scan_framework_implied",
    # heuristic pre-screen
    "_DEFAULT_SHALLOW_DETECTORS",
    "heuristic_prescreen_cm",
    # adjudication
    "CMAdjudicationOut",
    "AdjudicatedCM",
    "AdjudicateStats",
    "adjudicate_cm",
    "render_adjudication_prompt",
    "TargetProfile",
    "build_target_adaptation_notes",
    "write_intent_cm",
    "write_adjudicated_jsonl",
    "read_adjudicated_jsonl",
    "write_manifest",
]
