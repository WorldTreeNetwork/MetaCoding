"""Lexicon gap scan — the deterministic vocabulary diff (glossary-as-topology, ch. 1).

Walks a scoped set of farmOS/Drupal module directories and diffs their
**declarative** vocabulary — workflow FSM states, config-entity type lists,
allowed-values maps, bundle-field names declared in attribute plugins — against
the oracle glossary's closed sets (:mod:`ctkr.oracle.glossary`). Every value the
source declares that the glossary does not know is a *gap*: a place where the
discovered ontology is smaller than the system it describes.

Zero LLM, zero network, zero writes into the scanned tree. The scan reads YAML
(``*.workflows.yml``, ``config/install`` + ``config/optional`` config entities,
field storage/instance definitions) plus the declarative field arrays inside
PHP 8 attribute plugins (``#[LogType(...)]`` etc. — the same artifact class the
drupal-harvest lane treats as declarative). Output rows are sorted and carry no
timestamps, so a re-run over the same tree is byte-identical.

Each gap carries a partial **TERM-SPEC v1** candidate — the shared contract
between ``propose-terms`` output and the binding gate::

    {"term": str, "kind": "entity"|"action"|"assertion", "description": str,
     "probe_semantics": str, "discriminating_flow": {<flow-DSL sketch>},
     "provenance": {"role_class_id": str|null, "config_source": str|null,
                    "punts": [str], "first_pack_seal": null}}

A term is PROVISIONAL until ``first_pack_seal`` is filled by a real sealed
recording. This module never binds anything: it only *surfaces* vocabulary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ctkr.drupal import _CONFIG_NAME, _rel, _safe_yaml
from ctkr.oracle.glossary import (
    ENTITY_TERMS,
    LOG_KINDS,
    LOG_STATUSES,
    MEASURES,
    all_terms,
)

# ---------------------------------------------------------------------------
# Gap row
# ---------------------------------------------------------------------------

GAP_KINDS: tuple[str, ...] = (
    "workflow_state",
    "log_type",
    "asset_type",
    "quantity_type",
    "bundle_field",
    "allowed_values",
)


@dataclass(frozen=True)
class Gap:
    """One vocabulary item the source declares and the glossary lacks."""

    gap_kind: str
    source_ref: str  # "<relative file path>:<key path>"
    value: Any  # str for single terms; sorted list for allowed-values lists
    glossary_set: str  # which closed set it is absent from
    candidate: dict = field(compare=False, default_factory=dict)

    def to_row(self) -> dict:
        return {
            "gap_kind": self.gap_kind,
            "source_ref": self.source_ref,
            "value": self.value,
            "glossary_set": self.glossary_set,
            "candidate": self.candidate,
        }


# ---------------------------------------------------------------------------
# TERM-SPEC v1 candidate construction (deterministic templates)
# ---------------------------------------------------------------------------

_KIND_BY_GAP: dict[str, str] = {
    "workflow_state": "assertion",  # extends the log_status value vocabulary
    "log_type": "action",  # a recordable event kind (record_log's sub-type)
    "asset_type": "entity",  # a domain noun a `given` could instantiate
    "quantity_type": "assertion",  # a delivered measured-value classification
    "bundle_field": "assertion",  # a delivered per-record value
    "allowed_values": "entity",  # a closed descriptor vocabulary
}

_PROBE_BY_GAP: dict[str, str] = {
    "workflow_state": (
        "read the lifecycle status delivered for the recorded log and compare "
        "it to the expected state"
    ),
    "log_type": "count/read logs of this kind referencing the subject asset",
    "asset_type": "instantiate the asset kind and read it back from the active set",
    "quantity_type": (
        "read the quantity classification delivered for a measured value on a "
        "recorded log"
    ),
    "bundle_field": "read the field's delivered value back for the recorded subject",
    "allowed_values": (
        "read the descriptor delivered for the subject and check membership in "
        "the closed list"
    ),
}


def _flow_sketch(gap_kind: str, term: str) -> dict:
    """A minimal, deterministic flow-DSL sketch for a discriminating fixture."""
    if gap_kind == "workflow_state":
        return {
            "given": ["a land asset", "a recorded activity log against it"],
            "when": [f"set_log_status -> {term}"],
            "then": [f"log_status == {term}"],
        }
    if gap_kind == "log_type":
        return {
            "given": ["a land asset"],
            "when": [f"record_log kind={term}"],
            "then": [f"log_count kind={term} == 1"],
        }
    if gap_kind in ("asset_type", "allowed_values"):
        return {
            "given": [f"a {term}"],
            "when": [],
            "then": ["asset_active == true"],
        }
    if gap_kind == "quantity_type":
        return {
            "given": ["a land asset"],
            "when": [f"record_log with a {term} quantity"],
            "then": ["quantity_recorded"],
        }
    # bundle_field
    return {
        "given": ["a land asset"],
        "when": [f"record_log with {term} set"],
        "then": [f"{term} delivered == the recorded value"],
    }


def _candidate(gap_kind: str, term: str, source_ref: str, description: str,
               punts: list[str]) -> dict:
    kind = _KIND_BY_GAP[gap_kind]
    return {
        "term": term,
        "kind": kind,
        "description": description,
        "probe_semantics": _PROBE_BY_GAP[gap_kind],
        "discriminating_flow": _flow_sketch(gap_kind, term),
        "provenance": {
            "role_class_id": None,
            "config_source": source_ref,
            "punts": [f"kind={kind!r} guessed deterministically from "
                      f"gap_kind={gap_kind!r}"] + punts,
            "first_pack_seal": None,
        },
    }


# ---------------------------------------------------------------------------
# Channel 1: workflow FSMs (*.workflows.yml)
# ---------------------------------------------------------------------------

def _scan_workflows(path: Path, root: Path) -> list[Gap]:
    doc = _safe_yaml(path)
    if not isinstance(doc, dict):
        return []
    gaps: list[Gap] = []
    rel = _rel(path, root)
    for wf_id, wf in sorted(doc.items()):
        if not isinstance(wf, dict):
            continue
        group = wf.get("group")
        states = wf.get("states")
        if not isinstance(states, dict):
            continue
        if group == "log":
            known, gset = LOG_STATUSES, "LOG_STATUSES"
        else:
            known = all_terms()
            gset = f"(no closed set for group {group!r})"
        for state in sorted(states):
            if state in known:
                continue
            ref = f"{rel}:{wf_id}.states.{state}"
            label = ""
            if isinstance(states[state], dict):
                label = str(states[state].get("label", ""))
            desc = (f"workflow state {state!r} of {wf_id!r} (group {group!r}"
                    f"{', label ' + label if label else ''}) — a lifecycle "
                    f"value the source FSM can deliver")
            gaps.append(Gap(
                gap_kind="workflow_state", source_ref=ref, value=state,
                glossary_set=gset,
                candidate=_candidate(
                    "workflow_state", state, ref, desc,
                    punts=["transition preconditions not captured in sketch"]),
            ))
    return gaps


# ---------------------------------------------------------------------------
# Channel 2: config entities (config/install + config/optional *.yml)
# ---------------------------------------------------------------------------

_TYPE_LIST_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+_type$")


def _scan_config_entity(path: Path, root: Path,
                        type_lists: dict[str, list[tuple[str, str, str]]],
                        ) -> list[Gap]:
    # field.storage.<entity>.<name> / field.field.<entity>.<bundle>.<name>
    # carry dotted ids, so they never match _CONFIG_NAME — route them first.
    if path.stem.startswith(("field.storage.", "field.field.")):
        doc = _safe_yaml(path)
        if not isinstance(doc, dict):
            return []
        return _scan_field_definition(path, _rel(path, root), doc)
    m = _CONFIG_NAME.match(path.stem)
    if m is None:
        return []
    config_type, entity_id = m.group("type"), m.group("id")
    rel = _rel(path, root)
    doc = _safe_yaml(path)
    doc = doc if isinstance(doc, dict) else {}
    label = str(doc.get("label", ""))
    gaps: list[Gap] = []

    if config_type == "log.type":
        if entity_id not in LOG_KINDS:
            ref = f"{rel}:id"
            desc = (f"log type {entity_id!r}"
                    f"{' (' + label + ')' if label else ''} — a recordable "
                    f"event kind the source declares")
            gaps.append(Gap(
                gap_kind="log_type", source_ref=ref, value=entity_id,
                glossary_set="LOG_KINDS",
                candidate=_candidate("log_type", entity_id, ref, desc, []),
            ))
        # default quantity type — the measured-value classification this log
        # kind records by default (e.g. input -> material).
        tps = doc.get("third_party_settings")
        if isinstance(tps, dict):
            qty = tps.get("farm_log_quantity")
            if isinstance(qty, dict):
                dqt = qty.get("default_quantity_type")
                if isinstance(dqt, str) and dqt and dqt not in MEASURES \
                        and dqt not in all_terms():
                    ref = (f"{rel}:third_party_settings.farm_log_quantity."
                           f"default_quantity_type")
                    desc = (f"quantity type {dqt!r} — the default measured-"
                            f"value classification for {entity_id!r} logs")
                    gaps.append(Gap(
                        gap_kind="quantity_type", source_ref=ref, value=dqt,
                        glossary_set="MEASURES",
                        candidate=_candidate(
                            "quantity_type", dqt, ref, desc,
                            punts=["quantity bundle fields (e.g. its *_type "
                                   "reference) live in the quantity module, "
                                   "outside this file"]),
                    ))
    elif config_type == "asset.type":
        if entity_id not in ENTITY_TERMS:
            ref = f"{rel}:id"
            desc = (f"asset type {entity_id!r}"
                    f"{' (' + label + ')' if label else ''} — a domain noun "
                    f"the source tracks")
            gaps.append(Gap(
                gap_kind="asset_type", source_ref=ref, value=entity_id,
                glossary_set="ENTITY_TERMS",
                candidate=_candidate("asset_type", entity_id, ref, desc, []),
            ))
    elif _TYPE_LIST_RE.match(config_type):
        # A `<module>.<noun>_type.<id>` config entity: one member of a closed
        # descriptor vocabulary (e.g. farm_land.land_type.bed). Collected per
        # config_type and emitted as ONE allowed-values-list gap by the caller.
        type_lists.setdefault(config_type, []).append((entity_id, rel, label))
    return gaps


def _scan_field_definition(path: Path, rel: str, doc: dict) -> list[Gap]:
    """field.storage.* / field.field.* — bundle fields + allowed_values maps."""
    gaps: list[Gap] = []
    field_name = doc.get("field_name")
    if isinstance(field_name, str) and field_name \
            and field_name not in all_terms():
        ref = f"{rel}:field_name"
        desc = (f"field {field_name!r} (type {doc.get('type', '?')!r}) — a "
                f"declared per-record value")
        gaps.append(Gap(
            gap_kind="bundle_field", source_ref=ref, value=field_name,
            glossary_set="ASSERTION_TERMS",
            candidate=_candidate("bundle_field", field_name, ref, desc, []),
        ))
    settings = doc.get("settings")
    if isinstance(settings, dict):
        allowed = settings.get("allowed_values")
        values: list[str] = []
        if isinstance(allowed, dict):
            values = [str(v) for v in allowed]
        elif isinstance(allowed, list):
            for item in allowed:
                if isinstance(item, dict) and "value" in item:
                    values.append(str(item["value"]))
        missing = sorted(v for v in values if v not in all_terms())
        if missing:
            ref = f"{rel}:settings.allowed_values"
            name = field_name or path.stem
            desc = (f"allowed-values list of field {name!r} — a closed "
                    f"vocabulary the source enforces")
            gaps.append(Gap(
                gap_kind="allowed_values", source_ref=ref, value=missing,
                glossary_set="ENTITY_TERMS",
                candidate=_candidate(
                    "allowed_values", str(name), ref, desc,
                    punts=[f"list members absent from glossary: {missing}"]),
            ))
    return gaps


def _emit_type_lists(
        type_lists: dict[str, list[tuple[str, str, str]]]) -> list[Gap]:
    """One allowed_values gap per `<module>.<noun>_type` config-entity family."""
    gaps: list[Gap] = []
    for config_type in sorted(type_lists):
        members = sorted(type_lists[config_type])
        ids = [m[0] for m in members]
        missing = sorted(i for i in ids if i not in all_terms())
        if not missing:
            continue
        # Anchor the row at the family's first file (sorted → deterministic).
        ref = f"{members[0][1]}:{config_type}.*"
        noun = config_type.split(".", 1)[1]  # e.g. "land_type"
        desc = (f"{noun} allowed-values list {sorted(ids)} — a closed "
                f"descriptor vocabulary declared as config entities")
        gaps.append(Gap(
            gap_kind="allowed_values", source_ref=ref, value=sorted(ids),
            glossary_set="ENTITY_TERMS",
            candidate=_candidate(
                "allowed_values", noun, ref, desc,
                punts=[f"list members absent from glossary: {missing}"]),
        ))
    return gaps


# ---------------------------------------------------------------------------
# Channel 3: bundle fields declared in PHP attribute plugins
# ---------------------------------------------------------------------------

_PLUGIN_ATTR = re.compile(
    r"#\[\s*(LogType|AssetType|QuantityType|PlanType)\s*\(")
_PLUGIN_ID = re.compile(r"""\bid:\s*['"]([^'"]+)['"]""")
_FIELD_ASSIGN = re.compile(r"\$fields\[['\"]([a-z0-9_]+)['\"]\]\s*=")
_OPT_LABEL = re.compile(r"""'label'\s*=>\s*\$this->t\('([^']*)'\)""")
_OPT_TYPE = re.compile(r"""'type'\s*=>\s*'([^']*)'""")
_OPT_DESC = re.compile(r"""'description'\s*=>\s*\$this->t\('([^']*)'\)""")


def _scan_plugin_php(path: Path, root: Path) -> list[Gap]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    attr = _PLUGIN_ATTR.search(text)
    if attr is None:
        return []
    plugin_kind = attr.group(1)
    id_m = _PLUGIN_ID.search(text, attr.end())
    plugin_id = id_m.group(1) if id_m else path.stem.lower()
    rel = _rel(path, root)

    gaps: list[Gap] = []
    matches = list(_FIELD_ASSIGN.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1)
        if name in all_terms():
            continue
        # The declarative $options block for this field sits between the
        # previous $fields[...] assignment (or the attribute) and this one.
        chunk_start = matches[i - 1].end() if i > 0 else attr.end()
        chunk = text[chunk_start:m.start()]
        label_m = _OPT_LABEL.search(chunk)
        type_m = _OPT_TYPE.search(chunk)
        desc_m = _OPT_DESC.search(chunk)
        ref = f"{rel}:fields.{name}"
        bits = [f"bundle field {name!r} on {plugin_kind} {plugin_id!r}"]
        if type_m:
            bits.append(f"type {type_m.group(1)!r}")
        if label_m:
            bits.append(f"label {label_m.group(1)!r}")
        if desc_m:
            bits.append(desc_m.group(1))
        gaps.append(Gap(
            gap_kind="bundle_field", source_ref=ref, value=name,
            glossary_set="ASSERTION_TERMS",
            candidate=_candidate(
                "bundle_field", name, ref, " — ".join(bits),
                punts=["field declared in a PHP attribute plugin's "
                       "buildFieldDefinitions, not a YAML file"]),
        ))
    return gaps


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def scan_sources(src_roots: list[Path], *, rel_root: Path | None = None,
                 ) -> list[Gap]:
    """Walk the given module directories and return all gaps, sorted.

    ``rel_root`` anchors the relative paths in ``source_ref`` (defaults to the
    common parent behaviour of :func:`ctkr.drupal._rel` per root). Read-only:
    nothing is written anywhere.
    """
    gaps: list[Gap] = []
    type_lists: dict[str, list[tuple[str, str, str]]] = {}
    for src in sorted(Path(p).resolve() for p in src_roots):
        root = (rel_root or src).resolve()
        for path in sorted(src.rglob("*.yml")):
            if "tests" in path.parts:
                continue
            if path.name.endswith(".workflows.yml"):
                gaps.extend(_scan_workflows(path, root))
            elif path.parent.name in ("install", "optional") \
                    and path.parent.parent.name == "config":
                gaps.extend(_scan_config_entity(path, root, type_lists))
        for path in sorted(src.rglob("*.php")):
            if "tests" in path.parts:
                continue
            if "Plugin" in path.parts:
                gaps.extend(_scan_plugin_php(path, root))
    gaps.extend(_emit_type_lists(type_lists))
    gaps.sort(key=lambda g: (g.gap_kind, str(g.value), g.source_ref))
    return gaps


def write_gaps_jsonl(gaps: list[Gap], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for gap in gaps:
            fh.write(json.dumps(gap.to_row(), sort_keys=True) + "\n")


def summary_table(gaps: list[Gap]) -> str:
    """A human summary table (stdout)."""
    lines = [
        f"{'gap_kind':<16} {'value':<40} {'absent from':<28} source_ref",
        "-" * 110,
    ]
    for g in gaps:
        val = ",".join(g.value) if isinstance(g.value, list) else str(g.value)
        if len(val) > 38:
            val = val[:35] + "..."
        lines.append(
            f"{g.gap_kind:<16} {val:<40} {g.glossary_set:<28} {g.source_ref}")
    by_kind: dict[str, int] = {}
    for g in gaps:
        by_kind[g.gap_kind] = by_kind.get(g.gap_kind, 0) + 1
    counts = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
    lines += ["-" * 110, f"{len(gaps)} gaps ({counts})"]
    return "\n".join(lines)
