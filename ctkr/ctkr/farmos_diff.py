"""farmOS 1.x ↔ 2.x differential intention harvest — portability calibration.

The port-loop thesis (``docs/design/port-loop-plan.md`` "Why farmOS"): farmOS
1.x (Drupal 7) → 2.x (Drupal 9) was a ground-up rewrite of the *same product*.
A signal that **survived** the rewrite is intent-I (universal) by construction;
a signal that **changed** is idiom. ``farm_migrate`` writes the old→new mapping
down explicitly, so we do not have to guess the correspondence. Diffing the two
harvests empirically calibrates the portability tiers of
``docs/design/ct-intention-extraction.md`` §7.2 and the D/R dials (§5.3, §10
"N=1 problem").

This module is the **reusable, deterministic, LLM-free** diff engine:

* :func:`harvest_d7` — a small **Drupal 7 adapter**. ``ctkr drupal-harvest``
  (``ctkr.drupal``) is D8+ YAML-centric; farmOS 1.x is Drupal 7 — ``.info`` INI
  manifests, ``.module``/``.install`` PHP with ``hook_permission()`` arrays and
  ``entity_import('<type>', '{json}')`` feature exports. This adapter recovers the
  intention-bearing *declarative* surfaces at **honest, regex-level fidelity**
  (see :data:`D7_COVERAGE`) — it is NOT a PHP parser.
* :func:`harvest_d9` — projects the shipped ``ctkr.drupal`` harvest into the same
  comparable :class:`Sig` shape (so the two versions diff apples-to-apples).
* :func:`parse_migrations` — parses ``farm_migrate``'s migration YAMLs into the
  **ground-truth old→new mapping** (source bundle → destination bundle; process
  field maps; ``static_map`` value renames).
* :func:`diff_signals` — the survival classifier: per signal kind, every 1.x
  identifier is labelled ``survived_verbatim`` / ``survived_renamed`` (via the
  migrate map or token-similarity after affix folding) / ``dropped``; every 2.x
  identifier with no 1.x pre-image is ``new``. Renames are sub-classified
  ``convention`` (affix/namespace/plural only — intent-N confirmed) vs
  ``semantic`` (the domain root itself changed).

Everything is a pure function of its inputs and deterministically ordered, so a
re-run over the same trees is byte-identical (the T5a acceptance standard).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ctkr.intention import NormTables, fold_affixes, load_norm_tables, tokenize_identifier

# ─────────────────────────── honesty notes ───────────────────────────

D7_COVERAGE: dict[str, str] = {
    "module": ".info files are INI (`key = value`, `dependencies[] = x`); parsed "
    "line-wise, not by a Drupal .info parser — good fidelity for name/description/"
    "dependencies, ignores rarely-used directives.",
    "asset_type|log_type": "recovered from `entity_import('farm_asset_type'|'log_type', "
    "'{json}')` feature exports in *.features.inc via regex over the JSON blob's "
    "`type`/`label` keys — this is how D7 farmOS ships its default bundles. Bundles "
    "created only at runtime (none in core) are missed.",
    "permission": "recovered from `hook_permission()` returning an array literal; the "
    "permission machine-name keys + `title`/`description` are read by a brace-balanced "
    "regex over the function body. Dynamically-built permission names are missed.",
    "taxonomy_vocab": "D7 does not export vocabularies via entity_import in farmOS core; "
    "the 1.x vocabulary machine-names are taken from the ground-truth migrate source "
    "bundles (d7_taxonomy_term) rather than a direct D7 parse — flagged as oracle-derived.",
}


# ─────────────────────────── comparable signal ───────────────────────────

# Signal kinds compared across versions, with their §7.2 default portability tier
# (the *hypothesis* this study tests) and the §1 catalog indicator they map to.
#   I = universal (survive as-is)  N = convention-encoded (restate)  A = idiom (drop)
KIND_TIER: dict[str, tuple[str, str, str]] = {
    # kind          indicator  §7.2-predicted-tier   what it encodes
    "module": ("B1", "A", "module machine name — authors' decomposition"),
    "asset_type": ("A4", "I", "asset bundle — domain vocabulary (noun)"),
    "log_type": ("A4", "I", "log bundle — domain vocabulary (event noun)"),
    "taxonomy_vocab": ("A4", "I", "vocabulary — domain vocabulary (noun)"),
    "permission": ("A3", "N", "access-policy controlled vocab"),
    "field": ("A4", "N", "field machine name — data-shape vocab"),
}


@dataclass(frozen=True)
class Sig:
    """One comparable declarative identifier from one farmOS version."""

    kind: str  # key into KIND_TIER
    name: str  # machine name (the identifier compared)
    label: str  # human label, if any (context only, not compared)
    version: str  # "1.x" | "2.x"
    source: str  # provenance: relative file or "migrate-oracle"


# ─────────────────────────── D7 adapter ───────────────────────────

_INFO_KV = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$")
_INFO_DEP = re.compile(r"^\s*dependencies\[\]\s*=\s*(.+?)\s*$")
# entity_import('<entity_type>', '{ ... json ... }')
_ENTITY_IMPORT = re.compile(
    r"""entity_import\(\s*['"](?P<etype>[a-z_]+)['"]\s*,\s*'(?P<json>\{.*?\})'""",
    re.DOTALL,
)
_PERM_FN = re.compile(r"function\s+([a-z0-9_]+)_permission\s*\(\s*\)")


def _unquote_ini(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    return v


def _parse_info(path: Path) -> dict:
    """Parse a Drupal 7 ``.info`` (INI-ish) manifest. Best-effort, line-wise."""
    out: dict = {"dependencies": []}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for ln in text.splitlines():
        if ln.lstrip().startswith(";") or not ln.strip():
            continue
        dep = _INFO_DEP.match(ln)
        if dep:
            out["dependencies"].append(_unquote_ini(dep.group(1)))
            continue
        kv = _INFO_KV.match(ln)
        if kv and "[]" not in kv.group(1):
            out[kv.group(1)] = _unquote_ini(kv.group(2))
    return out


def _harvest_permissions(text: str) -> list[tuple[str, str, str]]:
    """(machine_name, title, description) from a D7 ``hook_permission()`` body."""
    out: list[tuple[str, str, str]] = []
    m = _PERM_FN.search(text)
    if not m:
        return out
    # bound the function body from the { after the () signature
    brace = text.find("{", m.end())
    if brace < 0:
        return out
    depth = 0
    body_end = len(text)
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body_end = i
                break
    body = text[brace : body_end + 1]
    # each top-level "'perm name' => array( 'title' => t('..'), 'description' => t('..') )"
    for pm in re.finditer(r"""['"]([a-zA-Z0-9 _\-]+?)['"]\s*=>\s*array\(""", body):
        name = pm.group(1)
        window = _balanced_paren(body, pm.end() - 1)
        title = _first_group(re.search(r"""['"]title['"]\s*=>\s*t\(\s*['"](.+?)['"]""", window))
        out.append((name, title, ""))
    return out


def _balanced_paren(text: str, open_idx: int) -> str:
    """Substring from the ``(`` at/after ``open_idx`` to its matching ``)``."""
    depth = 0
    start = text.find("(", open_idx)
    if start < 0:
        return ""
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def _first_group(m: re.Match | None) -> str:
    return m.group(1) if m else ""


def harvest_d7(root: str | Path) -> list[Sig]:
    """Harvest the declarative intention-bearing surfaces of a farmOS 1.x
    (Drupal 7) tree. Honest, regex-level fidelity — see :data:`D7_COVERAGE`."""
    root = Path(root).expanduser().resolve()
    sigs: list[Sig] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, name: str, label: str, source: str) -> None:
        name = name.strip()
        if not name or (kind, name) in seen:
            return
        seen.add((kind, name))
        sigs.append(Sig(kind, name, label.strip(), "1.x", source))

    # modules: every *.info manifest (module ≈ feature)
    for info in sorted(root.rglob("*.info")):
        if "/tests" in str(info) or "_test" in info.name:
            continue
        data = _parse_info(info)
        machine = info.name[: -len(".info")]
        add("module", machine, str(data.get("name") or machine), _rel(info, root))

    # asset/log types: entity_import('farm_asset_type'|'log_type', '{json}')
    for inc in sorted(root.rglob("*.features.inc")):
        if "/tests" in str(inc):
            continue
        try:
            text = inc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel(inc, root)
        for em in _ENTITY_IMPORT.finditer(text):
            etype = em.group("etype")
            kind = {"farm_asset_type": "asset_type", "log_type": "log_type"}.get(etype)
            if not kind:
                continue
            blob = em.group("json")
            tmatch = re.search(r'"type"\s*:\s*"([^"]+)"', blob)
            lmatch = re.search(r'"label"\s*:\s*"([^"]+)"', blob)
            if tmatch:
                add(kind, tmatch.group(1), _first_group(lmatch), rel)

    # permissions: hook_permission() in *.module / *.install
    for src in sorted([*root.rglob("*.module"), *root.rglob("*.install")]):
        if "/tests" in str(src) or "_test" in src.name:
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "_permission(" not in text:
            continue
        rel = _rel(src, root)
        for name, title, _desc in _harvest_permissions(text):
            add("permission", name, title, rel)

    return sigs


# ─────────────────────────── D9 (2.x) projection ───────────────────────────


def harvest_d9(root: str | Path) -> list[Sig]:
    """Harvest the farmOS 2.x tree via the shipped ``ctkr.drupal`` declarative
    lane, projected into comparable :class:`Sig` rows. Test-fixture modules
    (``**/tests/**``) are excluded so the diff compares shipped surfaces only."""
    from ctkr.drupal import harvest_site

    signals_df, _shapes, features_df, _stats = harvest_site(root)

    sigs: list[Sig] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, name: str, label: str, source: str) -> None:
        name = (name or "").strip()
        if not name or (kind, name) in seen:
            return
        seen.add((kind, name))
        sigs.append(Sig(kind, name, (label or "").strip(), "2.x", source))

    def is_test(path: str) -> bool:
        return "/tests/" in f"/{path}"

    # modules from the feature inventory (drop test-support modules — those under
    # tests/ and those whose machine name ends in _test, matching the D7 side)
    for row in features_df.iter_rows(named=True):
        if is_test(row["declarative_ref"] or "") or row["name"].endswith("_test"):
            continue
        add("module", row["name"], row["label"] or "", row["declarative_ref"] or "")

    # config-entity bundles + permissions from the signals frame
    file_of: dict[str, str] = {}
    for row in signals_df.iter_rows(named=True):
        if is_test(row["file"] or ""):
            continue
        file_of.setdefault(row["element_id"], row["file"])
        if row["element_kind"] == "permission" and row["indicator_kind"] == "A3":
            add("permission", row["content"], "", row["file"])

    # derive bundles from config element ids:
    #   element_id = "config:<provider>.<type>.<id>"  (e.g. config:asset.type.animal)
    _cfg = re.compile(r"^config:(?P<type>[a-z0-9_]+\.[a-z0-9_]+)\.(?P<bundle>[a-z0-9_]+)$")
    kind_for = {
        "asset.type": "asset_type",
        "log.type": "log_type",
        "taxonomy.vocabulary": "taxonomy_vocab",
    }
    for eid in sorted(file_of):
        if not eid.startswith("config:"):
            continue
        m = _cfg.match(eid)
        if not m:
            continue
        kind = kind_for.get(m.group("type"))
        if kind:
            add(kind, m.group("bundle"), "", file_of[eid])

    return sigs


# ─────────────────────────── migrate map (ground truth) ───────────────────────────


@dataclass
class MigrateMap:
    """The ground-truth old→new correspondence parsed from ``farm_migrate``."""

    # D7 source bundle  →  D9 destination bundle/type (hard-coded in process.type)
    bundle_map: dict[str, str] = field(default_factory=dict)
    # D9 destination field  →  set of D7 source fields feeding it
    field_map: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # static_map value renames: old value → new value (across all migrations)
    value_map: dict[str, str] = field(default_factory=dict)
    n_migrations: int = 0

    def to_json(self) -> dict:
        return {
            "bundle_map": dict(sorted(self.bundle_map.items())),
            "field_map": {k: sorted(v) for k, v in sorted(self.field_map.items())},
            "value_map": dict(sorted(self.value_map.items())),
            "n_migrations": self.n_migrations,
        }


def _walk_process(node: object, dest_field: str, mm: MigrateMap) -> None:
    """Recursively pull ``source:`` scalars and ``static_map`` blocks out of a
    migration ``process`` value, attributing sources to ``dest_field``."""
    if isinstance(node, dict):
        src = node.get("source")
        if isinstance(src, str) and not src.startswith("@") and not src.startswith("constants"):
            mm.field_map[dest_field].add(src.lstrip("'\""))
        if node.get("plugin") == "static_map":
            m = node.get("map")
            if isinstance(m, dict):
                for old, new in m.items():
                    if isinstance(old, str) and isinstance(new, str):
                        mm.value_map[old] = new
        for v in node.values():
            if isinstance(v, (dict, list)):
                _walk_process(v, dest_field, mm)
    elif isinstance(node, list):
        for v in node:
            _walk_process(v, dest_field, mm)


def parse_migrations(migrate_root: str | Path) -> MigrateMap:
    """Parse every ``migrate_plus.migration.*.yml`` under ``migrate_root`` into a
    :class:`MigrateMap`. The ``source.bundle`` → ``process.type.default_value``
    pair is the bundle correspondence; ``process.<field>.source`` is the field
    correspondence; ``static_map`` blocks are value renames."""
    import yaml

    root = Path(migrate_root).expanduser().resolve()
    mm = MigrateMap()
    files = sorted(root.rglob("migrate_plus.migration.*.yml"))
    for f in files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        proc = data.get("process")
        if not isinstance(proc, dict):
            continue
        mm.n_migrations += 1

        # bundle correspondence: source.bundle → hard-coded destination bundle.
        # The bundle-determining process key is `type` (asset/log), `vid`
        # (taxonomy vocabulary), or `bundle` — whichever carries a default_value.
        src = data.get("source") or {}
        src_bundle = src.get("bundle") if isinstance(src, dict) else None
        dest_bundle = None
        for key in ("type", "vid", "bundle"):
            kp = proc.get(key)
            if isinstance(kp, dict) and kp.get("plugin") == "default_value":
                dest_bundle = kp.get("default_value")
                break
            if isinstance(kp, str):
                dest_bundle = kp
                break
        if isinstance(src_bundle, str) and isinstance(dest_bundle, str):
            mm.bundle_map[src_bundle] = dest_bundle

        # field correspondences (skip the bundle/id plumbing keys)
        for dest_field, spec in proc.items():
            if dest_field in ("type", "vid", "bundle", "id", "tid", "uid", "langcode"):
                continue
            _walk_process(spec, dest_field, mm)

    return mm


# ─────────────────────────── the diff / survival classifier ───────────────────────────

_NAMESPACE_PREFIXES = ("farm", "field")  # farmOS project namespace + D7 field prefix


def _fold(tokens: list[str], tables: NormTables, drop_namespace: bool) -> list[str]:
    """Fold shipped convention affixes; optionally drop the project-namespace
    tokens (``farm``/``field``) wherever they occur — not just as a leading prefix,
    because farmOS embeds the namespace mid-identifier too (``administer farm_asset
    types``, ``field_farm_animal_sex``). Returns domain tokens, plural-normalised."""
    toks, _ = fold_affixes(tokens, tables, "php")
    if drop_namespace:
        toks = [t for t in toks if t not in _NAMESPACE_PREFIXES]
    return [_singular(t) for t in toks]


def _singular(tok: str) -> str:
    if len(tok) > 3 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def classify_rename(v1: str, v2: str, tables: NormTables) -> str:
    """``convention`` if v1→v2 differ only by convention affix / namespace prefix /
    pluralisation (intent-N confirmed); else ``semantic`` (the domain root moved)."""
    d1 = _fold(tokenize_identifier(v1), tables, drop_namespace=True)
    d2 = _fold(tokenize_identifier(v2), tables, drop_namespace=True)
    return "convention" if d1 == d2 and d1 else "semantic"


def _token_key(name: str, tables: NormTables) -> tuple[str, ...]:
    return tuple(_fold(tokenize_identifier(name), tables, drop_namespace=True))


@dataclass
class DiffRecord:
    kind: str
    v1_name: str
    v2_name: str  # "" when dropped
    status: str  # survived_verbatim | survived_renamed | dropped | new
    rename_class: str  # "" | convention | semantic
    via: str  # verbatim | migrate | token | ""
    predicted_tier: str  # §7.2 default portability tier for the kind

    def to_json(self) -> dict:
        return asdict(self)


def build_oracle(migmap: MigrateMap) -> dict[str, str]:
    """A flat v1→v2 correspondence oracle from the migrate map: bundle renames
    plus inverted field maps (each D7 source field → its D9 destination field).
    A source field feeding several destinations maps to the first by sort order
    (deterministic)."""
    oracle: dict[str, str] = dict(migmap.bundle_map)
    for dest_field, srcs in migmap.field_map.items():
        for src in sorted(srcs):
            oracle.setdefault(src, dest_field)
    return oracle


def fields_from_migrate(migmap: MigrateMap) -> tuple[list[Sig], list[Sig]]:
    """Synthesize comparable ``field`` Sigs from the migrate map: every D7 source
    field is a 1.x field, every D9 destination field is a 2.x field. This is the
    ground-truth field correspondence (denominator caveat: *migrated* fields only —
    D7 fields dropped entirely by the rewrite are not in any migration YAML)."""
    v1: list[Sig] = []
    v2: list[Sig] = []
    seen1: set[str] = set()
    seen2: set[str] = set()
    for dest_field, srcs in migmap.field_map.items():
        if dest_field not in seen2:
            seen2.add(dest_field)
            v2.append(Sig("field", dest_field, "", "2.x", "migrate-oracle"))
        for src in srcs:
            if src not in seen1:
                seen1.add(src)
                v1.append(Sig("field", src, "", "1.x", "migrate-oracle"))
    return v1, v2


def diff_signals(
    v1: list[Sig],
    v2: list[Sig],
    oracle: dict[str, str],
    tables: NormTables,
) -> list[DiffRecord]:
    """Per-kind survival classification of every 1.x identifier against 2.x,
    using the correspondence ``oracle`` (v1→v2, from :func:`build_oracle`) first
    and token-similarity (post affix-fold) as the fallback. Deterministic order."""
    records: list[DiffRecord] = []
    v1_by_kind: dict[str, list[Sig]] = defaultdict(list)
    v2_by_kind: dict[str, list[Sig]] = defaultdict(list)
    for s in v1:
        v1_by_kind[s.kind].append(s)
    for s in v2:
        v2_by_kind[s.kind].append(s)

    all_kinds = sorted(set(v1_by_kind) | set(v2_by_kind))
    for kind in all_kinds:
        tier = KIND_TIER.get(kind, ("?", "?", ""))[1]
        v2names = {s.name for s in v2_by_kind[kind]}
        v2_token_index: dict[tuple[str, ...], str] = {}
        for s in sorted(v2_by_kind[kind], key=lambda x: x.name):
            v2_token_index.setdefault(_token_key(s.name, tables), s.name)

        matched_v2: set[str] = set()
        for s in sorted(v1_by_kind[kind], key=lambda x: x.name):
            name = s.name
            # 1) verbatim
            if name in v2names:
                records.append(
                    DiffRecord(kind, name, name, "survived_verbatim", "", "verbatim", tier)
                )
                matched_v2.add(name)
                continue
            # 2) oracle correspondence (ground truth: migrate map)
            mapped = oracle.get(name)
            if mapped and mapped in v2names:
                records.append(
                    DiffRecord(
                        kind, name, mapped, "survived_renamed",
                        classify_rename(name, mapped, tables), "migrate", tier,
                    )
                )
                matched_v2.add(mapped)
                continue
            # 3) token-similarity fallback (affix-folded key equality)
            key = _token_key(name, tables)
            tok_match = v2_token_index.get(key) if key else None
            if tok_match and tok_match not in matched_v2:
                records.append(
                    DiffRecord(
                        kind, name, tok_match, "survived_renamed",
                        classify_rename(name, tok_match, tables), "token", tier,
                    )
                )
                matched_v2.add(tok_match)
                continue
            # 4) dropped
            records.append(DiffRecord(kind, name, "", "dropped", "", "", tier))

        # 2.x identifiers with no 1.x pre-image → new
        for s in sorted(v2_by_kind[kind], key=lambda x: x.name):
            if s.name not in matched_v2:
                records.append(DiffRecord(kind, "", s.name, "new", "", "", tier))

    return records


# ─────────────────────────── survival table ───────────────────────────


def survival_table(records: list[DiffRecord]) -> dict:
    """Aggregate survival numbers per signal kind (and rename sub-class). The
    denominator for a survival rate is the 1.x population (verbatim + renamed +
    dropped); ``new`` rows are counted separately (they have no 1.x pre-image)."""
    out: dict[str, dict] = {}
    by_kind: dict[str, list[DiffRecord]] = defaultdict(list)
    for r in records:
        by_kind[r.kind].append(r)

    for kind in sorted(by_kind):
        rs = by_kind[kind]
        verbatim = [r for r in rs if r.status == "survived_verbatim"]
        renamed = [r for r in rs if r.status == "survived_renamed"]
        dropped = [r for r in rs if r.status == "dropped"]
        new = [r for r in rs if r.status == "new"]
        conv = [r for r in renamed if r.rename_class == "convention"]
        sem = [r for r in renamed if r.rename_class == "semantic"]
        v1_pop = len(verbatim) + len(renamed) + len(dropped)
        survived = len(verbatim) + len(renamed)
        out[kind] = {
            "predicted_tier": KIND_TIER.get(kind, ("?", "?", ""))[1],
            "meaning": KIND_TIER.get(kind, ("?", "?", ""))[2],
            "v1_population": v1_pop,
            "survived_verbatim": len(verbatim),
            "survived_renamed": len(renamed),
            "renamed_convention": len(conv),
            "renamed_semantic": len(sem),
            "dropped": len(dropped),
            "new_in_v2": len(new),
            "survival_rate": round(survived / v1_pop, 3) if v1_pop else 0.0,
            "verbatim_rate": round(len(verbatim) / v1_pop, 3) if v1_pop else 0.0,
            # domain-root survival = survived where the root token is preserved
            # (verbatim + convention-only rename); semantic renames moved the root.
            "domain_root_survival": (
                round((len(verbatim) + len(conv)) / v1_pop, 3) if v1_pop else 0.0
            ),
        }
    return out


def write_diff_jsonl(records: list[DiffRecord], out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r.to_json(), sort_keys=True) + "\n")


def load_tables() -> NormTables:
    return load_norm_tables()


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


__all__ = [
    "Sig",
    "MigrateMap",
    "DiffRecord",
    "KIND_TIER",
    "D7_COVERAGE",
    "harvest_d7",
    "harvest_d9",
    "parse_migrations",
    "build_oracle",
    "fields_from_migrate",
    "classify_rename",
    "diff_signals",
    "survival_table",
    "write_diff_jsonl",
    "load_tables",
]
