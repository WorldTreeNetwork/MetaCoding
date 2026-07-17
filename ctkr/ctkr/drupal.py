"""Drupal declarative-config intention lane — port-loop Phase 0.

A YAML/annotation walker over a Drupal codebase's **declarative** artifacts. It
is deliberately independent of the structural scip-php lane: it covers exactly
where static PHP analysis is weakest — plugins, hooks, config entities, routing,
permissions, and update hooks — all of which Drupal encodes declaratively (YAML
config + PHP 8 attributes) rather than in call graphs.

Three artifacts, all deterministic + byte-identical on re-run (no timestamps in
rows; content-addressed ids; provenance conventions from
``ctkr-l3-artifacts.md`` / ``decomposition-schema.md`` §2):

* **Drupal intention signals** (:data:`DRUPAL_SIGNALS_FILE`) — ``IntentionSignalRow``
  rows (the same schema as the T5a mechanical harvest, so the two concat) from
  config-entity YAML, config schema, ``*.routing.yml``, ``*.permissions.yml``,
  ``*.links.*.yml``, ``.info.yml``, PHP 8 attribute plugins, and
  ``hook_update_N`` docblocks. Tiers S/A per the design's §1 catalog.
* **Config data shapes** (:data:`DRUPAL_CONFIG_SHAPES_FILE`) — ``ConfigShapeRow``
  rows for config-entity types + their fields, derived from ``config/schema``
  mappings (data_shapes-style, but keyed to the owning module rather than a
  structural subsystem — this lane runs *without* the Louvain partition).
* **Feature inventory** (``features.parquet``, D1) — ``FeatureRow``, one row per
  module (module ≈ feature): label + description from ``.info.yml``, the
  feature-level dependency graph (free from the manifest), routes / permissions
  counts, owned config entity types, and member file globs.

**Coverage honesty** (:data:`HARVEST_COVERAGE`). PHP attribute + docblock signals
are recovered by regex over source slices, not a PHP parser; the harvest records
a coverage note rather than claiming parser fidelity. Field-storage defined
imperatively in ``baseFieldDefinitions()`` is *not* harvested here (only
declarative config + attributes) — surfaced as a deferred note, not a silent gap.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import yaml
from blake3 import blake3

from ctkr.schema import (
    CONFIG_SHAPES_COLUMNS,
    FEATURES_COLUMNS,
    INTENTION_SIGNALS_COLUMNS,
    SCHEMA_VERSION,
)

logger = logging.getLogger("ctkr.drupal")

# Output artifact filenames under ``<data_dir>/ctkr/``. The signals file is
# deliberately NOT ``intention_signals.parquet`` — that name belongs to the T5a
# structural harvest; this lane writes a sibling with the identical schema so a
# consumer concats the two rather than one clobbering the other.
DRUPAL_SIGNALS_FILE = "drupal_signals.parquet"
DRUPAL_CONFIG_SHAPES_FILE = "drupal_config_shapes.parquet"
FEATURES_FILE = "features.parquet"

# Signals we DO emit but via regex over PHP source rather than a real PHP parser.
HARVEST_COVERAGE: dict[str, str] = {
    "A1": "PHP 8 attribute plugins (#[AssetType], #[LogType], #[Hook], "
    "#[ConfigEntityType], …) recovered by regex over the attribute head + its "
    "id:/label: args, not a PHP AST — nested/computed attribute args are missed.",
    "A6": "hook_update_N rationale recovered from the immediately-preceding "
    "/** … */ docblock by regex; multi-hook docblocks attach to the first hook.",
}

# Indicators intentionally NOT emitted by this lane, with the honest reason.
DEFERRED_INDICATORS: dict[str, str] = {
    "baseFieldDefinitions": "imperative field storage declared in PHP "
    "baseFieldDefinitions()/bundleFieldDefinitions() is not harvested — this "
    "lane is declarative-only (config YAML + attributes); the scip-php lane "
    "covers imperative PHP.",
    "B2": "README/module-doc prose — deferred to the doc-file lane; .info.yml "
    "description carries the module's one-line purpose (S4).",
}


# ───────────────────────── portability + tier tables ─────────────────────────
# §7.2 intent tags: I=universal (into the brief as-is), N=convention-encoded
# (restate), A=idiom-specific (drop, retained in provenance). §1 tiers S/A rank
# the indicator. Kept as a single table so the mapping is auditable in one place.

# (indicator_kind, tier, portability_tier) per Drupal signal role.
_SIGNAL_SPEC: dict[str, tuple[str, str, str]] = {
    # .info.yml — the module manifest
    "module_label": ("A3", "A", "I"),  # human name — domain vocab
    "module_description": ("S4", "S", "I"),  # one-line purpose statement
    "module_package": ("B1", "B", "A"),  # grouping/topic — Drupal idiom
    "module_dependency": ("B3", "B", "N"),  # declared dependency — idiom context
    # config/install — config-entity instances
    "config_label": ("A4", "A", "I"),  # domain vocab (Animal, Harvest)
    "config_description": ("S4", "S", "I"),
    "config_id": ("A4", "A", "I"),  # bundle machine name — domain
    "config_type": ("A3", "A", "N"),  # config entity type (asset.type) — Drupal idiom
    # config/schema — field definitions
    "config_field": ("A4", "A", "N"),  # schema field name+type — convention
    # *.routing.yml
    "route_path": ("A2", "A", "N"),  # URL route string — framework contract
    "route_title": ("A2", "A", "I"),  # user-facing page title
    "route_permission": ("A3", "A", "N"),  # access-policy key
    # *.permissions.yml
    "permission_id": ("A3", "A", "N"),  # access-policy controlled vocab
    "permission_title": ("A2", "A", "I"),  # user-facing
    "permission_description": ("S4", "S", "I"),
    # *.links.*.yml
    "menu_link_title": ("A2", "A", "I"),  # user-facing nav text
    # PHP 8 attribute plugins
    "attribute_name": ("A1", "A", "N"),  # #[AssetType], #[Hook] — annotation name
    "attribute_id": ("A3", "A", "N"),  # plugin id — controlled vocab
    "attribute_label": ("A4", "A", "I"),  # plugin label — domain vocab
    # hook_update_N
    "update_hook": ("A6", "A", "I"),  # migration/compat rationale (WHY)
}


# ───────────────────────── id + row helpers ─────────────────────────


def _digest(*parts: str) -> str:
    h = blake3()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest(length=12)


def _clip(s: str, n: int = 240) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _lr(line: int | None) -> str:
    return str(line) if line else ""


@dataclass
class DSig:
    """A pending Drupal intention signal (rendered to an IntentionSignalRow)."""

    element_id: str
    element_kind: str
    role: str  # key into _SIGNAL_SPEC
    content: str
    file: str
    line: int | None

    def row(self) -> dict:
        indicator, tier, port = _SIGNAL_SPEC[self.role]
        lr = _lr(self.line)
        content = _clip(self.content)
        return {
            "signal_id": _digest(self.element_id, indicator, content, self.file, lr),
            "element_id": self.element_id,
            "element_kind": self.element_kind,
            "indicator_kind": indicator,
            "tier": tier,
            "content": content,
            "file": self.file,
            "line_range": lr,
            "portability_tier": port,
            "schema_version": SCHEMA_VERSION,
        }


@dataclass
class HarvestStats:
    n_modules: int = 0
    n_signals: int = 0
    n_config_shapes: int = 0
    n_features: int = 0
    by_indicator: dict[str, int] = field(default_factory=dict)
    by_tier: dict[str, int] = field(default_factory=dict)
    by_portability: dict[str, int] = field(default_factory=dict)
    by_element_kind: dict[str, int] = field(default_factory=dict)
    n_routes: int = 0
    n_permissions: int = 0
    n_php_plugins: int = 0
    n_update_hooks: int = 0
    coverage: dict[str, str] = field(default_factory=lambda: dict(HARVEST_COVERAGE))
    deferred: dict[str, str] = field(default_factory=lambda: dict(DEFERRED_INDICATORS))
    total_seconds: float = 0.0


# ───────────────────────── YAML + text helpers ─────────────────────────


def _safe_yaml(path: Path) -> object | None:
    """Parse a YAML file, returning None on any error (a malformed config file
    must not abort a whole-corpus harvest — it is dropped with a debug log)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        logger.debug("skipping unparseable YAML %s: %s", path, exc)
        return None


def _toplevel_key_lines(path: Path) -> dict[str, int]:
    """Map each top-level YAML mapping key to its 1-indexed line (best-effort).

    PyYAML's safe_load discards positions; for route/permission/link files whose
    top-level keys ARE the elements (route names, permission names) a cheap regex
    over the raw text recovers provenance without a position-tracking loader.
    """
    out: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for i, ln in enumerate(lines, start=1):
        m = re.match(r"^([A-Za-z_][\w.\-: ]*?):(?:\s|$)", ln)
        if m and m.group(1) not in out:
            out[m.group(1)] = i
    return out


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ───────────────────────── module discovery + ownership ─────────────────────────


@dataclass
class Module:
    machine_name: str  # e.g. farm_harvest (basename of the .info.yml)
    info_path: Path
    root: Path  # directory containing the .info.yml (owns its subtree)
    label: str
    description: str
    package: str
    dependencies: list[str]  # module machine names (colon-stripped)
    core_requirement: str


def _discover_modules(site_root: Path) -> list[Module]:
    """Every ``*.info.yml`` is a module (module ≈ feature). Deterministic order."""
    mods: list[Module] = []
    for info in sorted(site_root.rglob("*.info.yml")):
        machine = info.name[: -len(".info.yml")]
        data = _safe_yaml(info)
        if not isinstance(data, dict):
            data = {}
        raw_deps = data.get("dependencies") or []
        deps: list[str] = []
        if isinstance(raw_deps, list):
            for d in raw_deps:
                # dependency spec is "project:module" or "module"; keep the module part
                deps.append(str(d).split(":")[-1].strip())
        mods.append(
            Module(
                machine_name=machine,
                info_path=info,
                root=info.parent,
                label=str(data.get("name") or machine),
                description=str(data.get("description") or ""),
                package=str(data.get("package") or ""),
                dependencies=sorted(set(deps)),
                core_requirement=str(data.get("core_version_requirement") or ""),
            )
        )
    return mods


def _owning_module(path: Path, module_roots: list[tuple[Path, Module]]) -> Module | None:
    """The nearest ancestor module (longest matching root path) that owns a file."""
    best: Module | None = None
    best_len = -1
    for root, mod in module_roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        depth = len(root.parts)
        if depth > best_len:
            best_len = depth
            best = mod
    return best


# ───────────────────────── config-entity type parsing ─────────────────────────

# config/install filenames: {provider}.{config_prefix}.{id}.yml
# e.g. asset.type.animal → type "asset.type", bundle "animal"
#      farm_id_tag.tag_type.ear_tag → type "farm_id_tag.tag_type", bundle "ear_tag"
_CONFIG_NAME = re.compile(r"^(?P<type>[a-z0-9_]+\.[a-z0-9_]+)\.(?P<id>[a-z0-9_]+)$")


def _config_type_of(filename_stem: str) -> tuple[str, str] | None:
    """(config_entity_type, bundle_id) from a config/install filename stem, or None
    for a simple config *object* (e.g. ``system.site``) that is not a bundle."""
    m = _CONFIG_NAME.match(filename_stem)
    if not m:
        return None
    return m.group("type"), m.group("id")


# ───────────────────────── PHP attribute parsing ─────────────────────────

# Attribute head: #[AttrName( ... — captures the name. farmOS 3.x is 100% PHP 8
# attributes (Drupal 11); legacy @AnnotationType doc-comments do not appear.
_ATTR_HEAD = re.compile(r"#\[\s*([A-Z][A-Za-z0-9_]+)\s*\(")
# id: 'x' / label: new TranslatableMarkup('x') / label: 'x' inside an attribute.
_ATTR_ID = re.compile(r"""\bid:\s*['"]([^'"]+)['"]""")
_ATTR_LABEL = re.compile(
    r"""\blabel:\s*(?:new\s+\w+\(\s*)?['"]([^'"]{1,160})['"]"""
)
# Plugin attributes worth harvesting as intention (entity types, farmOS plugin
# kinds, hooks, actions). Test-only / DI / render attributes are skipped.
_PLUGIN_ATTRS = frozenset(
    {
        "ContentEntityType", "ConfigEntityType", "AssetType", "LogType",
        "QuantityType", "PlanType", "FieldType", "FieldWidget", "FieldFormatter",
        "Action", "QuickForm", "Block", "Constraint", "Hook", "NotificationDelivery",
    }
)


def _harvest_php_attributes(text: str) -> list[tuple[int, str, str | None, str | None]]:
    """Return (line, attr_name, id_arg, label_arg) for each plugin attribute.

    Regex-level (coverage note A1): reads the attribute head + a bounded window
    for its ``id:`` / ``label:`` args. Deterministic; sorted by position.
    """
    out: list[tuple[int, str, str | None, str | None]] = []
    for m in _ATTR_HEAD.finditer(text):
        name = m.group(1)
        if name not in _PLUGIN_ATTRS:
            continue
        line = text.count("\n", 0, m.start()) + 1
        # window from the attribute head to a bounded length — big enough for the
        # id:/label: args, small enough to not drag in an unrelated later attribute.
        window = text[m.start() : m.start() + 1200]
        id_m = _ATTR_ID.search(window)
        label_m = _ATTR_LABEL.search(window)
        out.append(
            (line, name, id_m.group(1) if id_m else None, label_m.group(1) if label_m else None)
        )
    return out


# hook_update_N: function <module>_update_<N>() preceded by a /** docblock */.
_UPDATE_FN = re.compile(r"^\s*function\s+([a-z0-9_]+_update_(\d+))\s*\(", re.MULTILINE)


def _harvest_update_hooks(text: str) -> list[tuple[int, str, str]]:
    """Return (line, function_name, docblock_summary) for each hook_update_N."""
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    for m in _UPDATE_FN.finditer(text):
        fn = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        # walk backwards over blank lines to a preceding /** … */ docblock
        i = line - 2  # 0-indexed line just above the function
        while i >= 0 and not lines[i].strip():
            i -= 1
        doc_lines: list[str] = []
        if i >= 0 and lines[i].strip().endswith("*/"):
            j = i
            while j >= 0:
                stripped = lines[j].strip()
                cleaned = stripped.lstrip("/*").rstrip("*/").strip(" *")
                if cleaned:
                    doc_lines.append(cleaned)
                if stripped.startswith("/**"):
                    break
                j -= 1
            doc_lines.reverse()
        summary = " ".join(doc_lines).strip()
        out.append((line, fn, summary))
    return out


# ───────────────────────── the harvest ─────────────────────────


def harvest_site(
    site_root: str | Path,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, HarvestStats]:
    """Walk a Drupal codebase's declarative artifacts.

    Returns ``(signals_df, config_shapes_df, features_df, stats)`` — all rows
    deterministically sorted so re-runs over the same tree are byte-identical.
    """
    start = time.perf_counter()
    root = Path(site_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"--site-root {root} does not exist")

    modules = _discover_modules(root)
    module_roots = [(m.root, m) for m in modules]
    by_machine = {m.machine_name: m for m in modules}

    sigs: list[DSig] = []
    shape_rows: list[dict] = []
    # per-module tallies for the feature inventory
    routes_count: dict[str, int] = defaultdict(int)
    perms_count: dict[str, int] = defaultdict(int)
    config_types: dict[str, set[str]] = defaultdict(set)
    stats = HarvestStats(n_modules=len(modules))

    def owner(path: Path) -> Module | None:
        return _owning_module(path, module_roots)

    # ── .info.yml (module manifest) ──
    for m in modules:
        rel = _rel(m.info_path, root)
        eid = f"module:{m.machine_name}"
        if m.label:
            sigs.append(DSig(eid, "module", "module_label", m.label, rel, None))
        if m.description:
            sigs.append(DSig(eid, "module", "module_description", m.description, rel, None))
        if m.package:
            sigs.append(DSig(eid, "module", "module_package", m.package, rel, None))
        for dep in m.dependencies:
            sigs.append(DSig(eid, "module", "module_dependency", dep, rel, None))

    # ── config/install (config-entity instances) ──
    for cfg in sorted(root.rglob("*.yml")):
        parts = cfg.parts
        if "config" not in parts:
            continue
        idx = parts.index("config")
        sub = parts[idx + 1] if idx + 1 < len(parts) else ""
        if sub != "install":
            continue
        data = _safe_yaml(cfg)
        if not isinstance(data, dict):
            continue
        rel = _rel(cfg, root)
        mod = owner(cfg)
        mname = mod.machine_name if mod else ""
        typed = _config_type_of(cfg.stem)
        if typed:
            ctype, _bundle = typed
            if mod:
                config_types[mname].add(ctype)
        else:
            ctype = ""
        eid = f"config:{cfg.stem}"
        klines = _toplevel_key_lines(cfg)
        if ctype:
            sigs.append(DSig(eid, "config-entity", "config_type", ctype, rel, None))
        cid = data.get("id")
        if isinstance(cid, str) and cid:
            sigs.append(DSig(eid, "config-entity", "config_id", cid, rel, klines.get("id")))
        label = data.get("label")
        if isinstance(label, str) and label:
            sigs.append(DSig(eid, "config-entity", "config_label", label, rel, klines.get("label")))
        desc = data.get("description")
        if isinstance(desc, str) and desc.strip():
            sigs.append(
                DSig(eid, "config-entity", "config_description", desc, rel,
                     klines.get("description"))
            )

    # ── config/schema (field definitions → data shapes) ──
    for sch in sorted(root.rglob("*.yml")):
        parts = sch.parts
        if "config" not in parts:
            continue
        idx = parts.index("config")
        sub = parts[idx + 1] if idx + 1 < len(parts) else ""
        if sub != "schema":
            continue
        data = _safe_yaml(sch)
        if not isinstance(data, dict):
            continue
        rel = _rel(sch, root)
        mod = owner(sch)
        mname = mod.machine_name if mod else ""
        for type_key, spec in data.items():
            if not isinstance(spec, dict):
                continue
            entity_kind = str(spec.get("type") or "")
            mapping = spec.get("mapping")
            eid = f"schema:{type_key}"
            # type-summary shape row (field null)
            shape_rows.append(
                _shape_row(root_repo=root.name, module=mname, config_type=type_key,
                           entity_kind=entity_kind, field_name=None, field_type=None,
                           field_label=str(spec.get("label") or "") or None, source_file=rel)
            )
            if isinstance(mapping, dict):
                for fname, fspec in mapping.items():
                    if not isinstance(fspec, dict):
                        continue
                    ftype = str(fspec.get("type") or "") or None
                    flabel = str(fspec.get("label") or "") or None
                    shape_rows.append(
                        _shape_row(root_repo=root.name, module=mname, config_type=type_key,
                                   entity_kind=entity_kind, field_name=str(fname),
                                   field_type=ftype, field_label=flabel, source_file=rel)
                    )
                    sigs.append(
                        DSig(eid, "config-field", "config_field",
                             f"{fname}:{ftype}" if ftype else str(fname), rel, None)
                    )

    # ── *.routing.yml ──
    for rt in sorted(root.rglob("*.routing.yml")):
        data = _safe_yaml(rt)
        if not isinstance(data, dict):
            continue
        rel = _rel(rt, root)
        mod = owner(rt)
        if not mod:
            continue
        klines = _toplevel_key_lines(rt)
        for route_name, spec in data.items():
            if not isinstance(spec, dict):
                continue
            routes_count[mod.machine_name] += 1
            stats.n_routes += 1
            eid = f"route:{route_name}"
            line = klines.get(route_name)
            path = spec.get("path")
            if isinstance(path, str) and path:
                sigs.append(DSig(eid, "route", "route_path", path, rel, line))
            defaults = spec.get("defaults") or {}
            title = defaults.get("_title") if isinstance(defaults, dict) else None
            if isinstance(title, str) and title:
                sigs.append(DSig(eid, "route", "route_title", title, rel, line))
            reqs = spec.get("requirements") or {}
            perm = reqs.get("_permission") if isinstance(reqs, dict) else None
            if isinstance(perm, str) and perm:
                sigs.append(DSig(eid, "route", "route_permission", perm, rel, line))

    # ── *.permissions.yml ──
    for pm in sorted(root.rglob("*.permissions.yml")):
        data = _safe_yaml(pm)
        if not isinstance(data, dict):
            continue
        rel = _rel(pm, root)
        mod = owner(pm)
        if not mod:
            continue
        klines = _toplevel_key_lines(pm)
        for perm_name, spec in data.items():
            perms_count[mod.machine_name] += 1
            stats.n_permissions += 1
            eid = f"permission:{perm_name}"
            line = klines.get(perm_name)
            sigs.append(DSig(eid, "permission", "permission_id", perm_name, rel, line))
            if isinstance(spec, dict):
                title = spec.get("title")
                if isinstance(title, str) and title:
                    sigs.append(DSig(eid, "permission", "permission_title", title, rel, line))
                desc = spec.get("description")
                if isinstance(desc, str) and desc.strip():
                    sigs.append(DSig(eid, "permission", "permission_description", desc, rel, line))

    # ── *.links.*.yml (menu/task/action link titles) ──
    for lk in sorted(root.glob("**/*.links.*.yml")):
        data = _safe_yaml(lk)
        if not isinstance(data, dict):
            continue
        rel = _rel(lk, root)
        klines = _toplevel_key_lines(lk)
        for link_name, spec in data.items():
            if not isinstance(spec, dict):
                continue
            title = spec.get("title")
            if isinstance(title, str) and title:
                sigs.append(
                    DSig(f"link:{link_name}", "menu-link", "menu_link_title", title, rel,
                         klines.get(link_name))
                )

    # ── PHP 8 attribute plugins (src/**.php) ──
    for php in sorted(root.rglob("*.php")):
        # skip test scaffolding — a plugin attribute in a test isn't a feature
        if "/tests/" in str(php) or php.name.endswith("Test.php"):
            continue
        try:
            text = php.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "#[" not in text:
            continue
        rel = _rel(php, root)
        for line, name, id_arg, label_arg in _harvest_php_attributes(text):
            stats.n_php_plugins += 1
            eid = f"plugin:{id_arg or name}:{rel}"
            sigs.append(DSig(eid, "php-plugin", "attribute_name", f"#[{name}]", rel, line))
            if id_arg:
                sigs.append(DSig(eid, "php-plugin", "attribute_id", id_arg, rel, line))
            if label_arg:
                sigs.append(DSig(eid, "php-plugin", "attribute_label", label_arg, rel, line))

    # ── hook_update_N docblocks (*.install) ──
    for inst in sorted(root.rglob("*.install")):
        try:
            text = inst.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel(inst, root)
        for line, fn, summary in _harvest_update_hooks(text):
            stats.n_update_hooks += 1
            content = f"{fn}: {summary}" if summary else fn
            sigs.append(DSig(f"update-hook:{fn}", "update-hook", "update_hook", content, rel, line))

    # ── feature inventory (one row per module) ──
    feat_rows: list[dict] = []
    feature_id_of = {m.machine_name: _digest(root.name, m.machine_name) for m in modules}
    for m in modules:
        deps = [feature_id_of[d] for d in m.dependencies if d in by_machine]
        rel_root = _rel(m.root, root)
        glob = f"{rel_root}/**" if rel_root != "." else "**"
        feat_rows.append(
            {
                "feature_id": feature_id_of[m.machine_name],
                "repo": root.name,
                "name": m.machine_name,
                "label": m.label,
                "description": m.description,
                "source_basis": "declarative",
                "declarative_ref": _rel(m.info_path, root),
                "package": m.package or None,
                "core_requirement": m.core_requirement or None,
                "depends_on": sorted(deps),
                "config_entity_types": sorted(config_types.get(m.machine_name, set())),
                "routes_count": routes_count.get(m.machine_name, 0),
                "permissions_count": perms_count.get(m.machine_name, 0),
                "member_globs": [glob],
                "schema_version": SCHEMA_VERSION,
            }
        )
    stats.n_features = len(feat_rows)

    # ── deterministic sort + frames ──
    sig_dicts = [s.row() for s in sigs]
    sig_dicts.sort(
        key=lambda d: (
            d["element_kind"], d["element_id"], d["indicator_kind"],
            d["content"], d["file"], d["line_range"],
        )
    )
    shape_rows.sort(
        key=lambda d: (d["module"], d["config_type"], d["field_name"] or "", d["shape_id"])
    )
    feat_rows.sort(key=lambda d: d["name"])

    signals_df = pl.DataFrame(sig_dicts, schema=_signals_schema()).select(
        INTENTION_SIGNALS_COLUMNS
    )
    config_shapes_df = pl.DataFrame(shape_rows, schema=_config_shapes_schema()).select(
        CONFIG_SHAPES_COLUMNS
    )
    features_df = pl.DataFrame(feat_rows, schema=_features_schema()).select(FEATURES_COLUMNS)

    stats.n_signals = signals_df.height
    stats.n_config_shapes = config_shapes_df.height
    stats.by_indicator = dict(Counter(s["indicator_kind"] for s in sig_dicts))
    stats.by_tier = dict(Counter(s["tier"] for s in sig_dicts))
    stats.by_portability = dict(Counter(s["portability_tier"] for s in sig_dicts))
    stats.by_element_kind = dict(Counter(s["element_kind"] for s in sig_dicts))
    stats.total_seconds = round(time.perf_counter() - start, 3)
    return signals_df, config_shapes_df, features_df, stats


def _shape_row(*, root_repo: str, module: str, config_type: str, entity_kind: str,
               field_name: str | None, field_type: str | None, field_label: str | None,
               source_file: str) -> dict:
    return {
        "shape_id": _digest(root_repo, config_type, field_name or ""),
        "repo": root_repo,
        "module": module,
        "config_type": config_type,
        "entity_kind": entity_kind,
        "field_name": field_name,
        "field_type": field_type,
        "field_label": field_label,
        "source_file": source_file,
        "schema_version": SCHEMA_VERSION,
    }


# ───────────────────────── schemas + writers ─────────────────────────


def _signals_schema() -> dict:
    return {
        "signal_id": pl.Utf8, "element_id": pl.Utf8, "element_kind": pl.Utf8,
        "indicator_kind": pl.Utf8, "tier": pl.Utf8, "content": pl.Utf8,
        "file": pl.Utf8, "line_range": pl.Utf8, "portability_tier": pl.Utf8,
        "schema_version": pl.Int64,
    }


def _config_shapes_schema() -> dict:
    return {
        "shape_id": pl.Utf8, "repo": pl.Utf8, "module": pl.Utf8,
        "config_type": pl.Utf8, "entity_kind": pl.Utf8, "field_name": pl.Utf8,
        "field_type": pl.Utf8, "field_label": pl.Utf8, "source_file": pl.Utf8,
        "schema_version": pl.Int64,
    }


def _features_schema() -> dict:
    return {
        "feature_id": pl.Utf8, "repo": pl.Utf8, "name": pl.Utf8, "label": pl.Utf8,
        "description": pl.Utf8, "source_basis": pl.Utf8, "declarative_ref": pl.Utf8,
        "package": pl.Utf8, "core_requirement": pl.Utf8,
        "depends_on": pl.List(pl.Utf8), "config_entity_types": pl.List(pl.Utf8),
        "routes_count": pl.Int64, "permissions_count": pl.Int64,
        "member_globs": pl.List(pl.Utf8), "schema_version": pl.Int64,
    }


def write_drupal_signals(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(INTENTION_SIGNALS_COLUMNS).write_parquet(p)


def write_config_shapes(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(CONFIG_SHAPES_COLUMNS).write_parquet(p)


def write_features(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(FEATURES_COLUMNS).write_parquet(p)


def write_manifest(
    data_dir: str | Path,
    *,
    n_signals: int,
    n_config_shapes: int,
    n_features: int,
    generated_at: str | None = None,
) -> Path:
    """Merge Drupal-lane presence + counts into ``<data_dir>/ctkr/manifest.json``.

    Additive: existing manifest keys (from the structural / T5a lanes) are
    preserved; only the drupal_* / features keys are set. ``ArtifactManifest``
    carries ``extra="allow"`` so these round-trip through the pydantic model.
    """
    import json
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
        "drupal_signals": True,
        "drupal_config_shapes": True,
        "features": True,
        "n_drupal_signals": int(n_signals),
        "n_drupal_config_shapes": int(n_config_shapes),
        "n_features": int(n_features),
    }
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "Module",
    "HarvestStats",
    "harvest_site",
    "write_drupal_signals",
    "write_config_shapes",
    "write_features",
    "write_manifest",
    "DRUPAL_SIGNALS_FILE",
    "DRUPAL_CONFIG_SHAPES_FILE",
    "FEATURES_FILE",
    "HARVEST_COVERAGE",
    "DEFERRED_INDICATORS",
]
