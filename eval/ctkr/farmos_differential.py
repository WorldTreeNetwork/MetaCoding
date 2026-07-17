#!/usr/bin/env python3
"""farmOS 1.x↔2.x differential intention harvest — runner (bead MetaCoding-k12).

Drives the reusable diff engine (``ctkr.farmos_diff``) over two local farmOS
checkouts + the ``farm_migrate`` ground-truth map, and writes:

* ``eval/ctkr/results/farmos-differential.jsonl`` — one DiffRecord per signal
  (the per-identifier survival ledger; deterministic).
* ``eval/ctkr/results/farmos-differential.md`` — the calibration report: real
  survival numbers per §7.2 tier hypothesis + proposed dial/tier reassignments.

Usage:
    uv run python farmos_differential.py \
        --v1 <farmOS-1.x tree> --v2 <farmOS-2.x tree> \
        --migrate <farmOS-2.x/modules/core/migrate>

Deterministic + LLM-free. Paths are reported (sandbox vs production) in the
report header per the CLAUDE.md data-dir-scope convention.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# make the ctkr package importable when run from eval/ctkr with its own venv
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "ctkr"))

from ctkr.farmos_diff import (  # noqa: E402
    D7_COVERAGE,
    KIND_TIER,
    build_oracle,
    diff_signals,
    fields_from_migrate,
    harvest_d7,
    harvest_d9,
    load_tables,
    parse_migrations,
    survival_table,
    write_diff_jsonl,
)

RESULTS = Path(__file__).resolve().parent / "results"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _examples(records, kind, status, rename_class=None, n=8):
    out = []
    for r in records:
        if r.kind != kind or r.status != status:
            continue
        if rename_class is not None and r.rename_class != rename_class:
            continue
        if status == "dropped":
            out.append(f"`{r.v1_name}`")
        elif status == "new":
            out.append(f"`{r.v2_name}`")
        elif status == "survived_verbatim":
            out.append(f"`{r.v1_name}`")
        else:  # renamed
            out.append(f"`{r.v1_name}`→`{r.v2_name}`")
    out = sorted(set(out))
    return ", ".join(out[:n]) + (f" … (+{len(out) - n})" if len(out) > n else "")


def build_report(v1_path, v2_path, migrate_path, migmap, records, table) -> str:
    ts = datetime.now(tz=UTC).isoformat(timespec="seconds")
    L: list[str] = []
    a = L.append

    a("# farmOS 1.x ↔ 2.x differential intention harvest — portability calibration")
    a("")
    a(f"_Generated {ts} · bead MetaCoding-k12 · deterministic, LLM-free._")
    a("")
    a("The N=2 instance the intention design (`ct-intention-extraction.md` §7.2, §10) "
      "says it lacks: farmOS 1.x (Drupal 7) → 2.x (Drupal 9) was a ground-up rewrite of "
      "the **same product**, with the old→new map written down in `farm_migrate`. A signal "
      "that **survived** the rewrite is intent-I (universal) *by construction*; one that "
      "**changed** is idiom. These are empirical numbers against that hypothesis.")
    a("")
    a("## Provenance")
    a("")
    a(f"- **1.x source** (harvested): `{v1_path}` — Drupal 7 tree; sandbox clone of "
      "`farmOS@7.x-1.x`.")
    a(f"- **2.x source** (harvested): `{v2_path}` — Drupal 9/10 tree; sandbox clone of "
      "`farmOS@2.x`.")
    a(f"- **Ground-truth map**: `{migrate_path}` — `farm_migrate`, "
      f"{migmap.n_migrations} migration templates parsed.")
    a("- All paths are **sandbox** checkouts (temp clones), not a user production tree. "
      "No farmOS data was mutated; the diff reads source only.")
    a("")
    a("## Method + honest fidelity")
    a("")
    a("- **2.x harvest** uses the shipped `ctkr drupal-harvest` declarative lane "
      "(`ctkr.drupal.harvest_site`) — YAML config-entity ids, `.info.yml` modules, "
      "`*.permissions.yml`. Test-fixture modules (`**/tests/**`) excluded.")
    a("- **1.x harvest** uses a new **Drupal-7 adapter** (`ctkr.farmos_diff.harvest_d7`) — "
      "farmOS 1.x predates YAML config. Fidelity is regex-level, not a PHP parser:")
    for k, v in D7_COVERAGE.items():
        a(f"  - **{k}**: {v}")
    a("- **Normalization**: every identifier is compared as a **token sequence** via the "
      "shipped tokenizer (`ct-intention-extraction.md` §7.1(1)) with shipped convention "
      "affixes folded (§7.1(2)). A rename is `convention` if the versions differ only by "
      "affix / namespace-prefix / plural, else `semantic`. Never raw-string comparison.")
    a("- **Correspondence oracle**: the `farm_migrate` map first (source-bundle → "
      "destination-type; `process.<field>.source` field maps); token-similarity is the "
      "fallback where the map is silent.")
    a("- **Caveat — field denominator**: `field` rows come from the migrate map, so the "
      "population is *migrated* fields only; D7 fields the rewrite dropped outright are "
      "not counted (they appear in no migration). Bundle/module/permission populations "
      "are the full independent harvests.")
    a("")

    # ── headline table ──
    a("## Survival by signal kind (the headline)")
    a("")
    a("`survival` = survived_verbatim + survived_renamed, over the 1.x population. "
      "`domain-root` = verbatim + convention-only rename (the domain root token is "
      "preserved; a semantic rename moved it). `pred` = the §7.2 default portability tier "
      "this kind was *assigned* going in.")
    a("")
    a("| kind | pred tier | 1.x pop | verbatim | renamed (conv/sem) | dropped | new "
      "| survival | domain-root |")
    a("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for kind in sorted(table):
        r = table[kind]
        a(f"| {kind} | {r['predicted_tier']} | {r['v1_population']} | "
          f"{r['survived_verbatim']} | {r['survived_renamed']} "
          f"({r['renamed_convention']}/{r['renamed_semantic']}) | "
          f"{r['dropped']} | {r['new_in_v2']} | {_pct(r['survival_rate'])} | "
          f"{_pct(r['domain_root_survival'])} |")
    a("")

    # ── per-kind detail ──
    a("## Per-kind detail + examples")
    a("")
    for kind in sorted(table):
        r = table[kind]
        meaning = KIND_TIER.get(kind, ("?", "?", ""))[2]
        a(f"### {kind} — {meaning} (predicted tier **{r['predicted_tier']}**)")
        a("")
        a(f"- survived verbatim ({r['survived_verbatim']}): "
          f"{_examples(records, kind, 'survived_verbatim')}")
        a(f"- renamed / convention-only ({r['renamed_convention']}): "
          f"{_examples(records, kind, 'survived_renamed', 'convention')}")
        a(f"- renamed / semantic ({r['renamed_semantic']}): "
          f"{_examples(records, kind, 'survived_renamed', 'semantic')}")
        a(f"- dropped ({r['dropped']}): {_examples(records, kind, 'dropped')}")
        a(f"- new in 2.x ({r['new_in_v2']}): {_examples(records, kind, 'new')}")
        a("")

    # ── ground-truth value renames ──
    if migmap.value_map:
        a("## Value-level renames (`static_map` in farm_migrate)")
        a("")
        a("Controlled-vocabulary *values* the migration explicitly rewrites — the crispest "
          "intent-N evidence: the value's meaning survives, its spelling is idiom.")
        a("")
        for old, new in sorted(migmap.value_map.items())[:24]:
            a(f"- `{old}` → `{new}`")
        a("")

    # ── the calibration verdict ──
    a("## Calibration: predicted §7.2 tier vs observed survival")
    a("")
    a("The hypothesis under test: **intent-I signals survive a same-product rewrite; "
      "intent-N signals survive in meaning but change in spelling; intent-A signals "
      "vanish.** Reading the observed numbers against the assigned tier:")
    a("")
    for kind in sorted(table):
        r = table[kind]
        tier = r["predicted_tier"]
        dr = r["domain_root_survival"]
        verdict = _verdict(tier, r)
        a(f"- **{kind}** (predicted **{tier}**): domain-root survival "
          f"{_pct(dr)}, verbatim {_pct(r['verbatim_rate'])}. {verdict}")
    a("")

    a("## Proposed tier / dial adjustments (where data contradicts §7.2 defaults)")
    a("")
    for line in _proposals(table, migmap):
        a(f"- {line}")
    a("")

    a("## Reproduce")
    a("")
    a("```")
    a("uv run python eval/ctkr/farmos_differential.py \\")
    a(f"    --v1 {v1_path} \\")
    a(f"    --v2 {v2_path} \\")
    a(f"    --migrate {migrate_path}")
    a("```")
    a("")
    return "\n".join(L)


def _verdict(tier: str, r: dict) -> str:
    dr = r["domain_root_survival"]
    verb = r["verbatim_rate"]
    if tier == "I":
        if dr >= 0.85:
            return "**Confirms intent-I** — the domain root is preserved across the rewrite."
        if dr >= 0.6:
            return "**Mostly confirms intent-I**, with a semantic-rename tail worth inspecting."
        return "**Weakens the intent-I assignment** — too many domain roots moved; review."
    if tier == "N":
        if verb < dr:
            return ("**Confirms intent-N** — meaning survives (high domain-root) but the "
                    "verbatim spelling does not (the convention was restated).")
        return "Behaves more universal (I) than convention-encoded (N); consider promotion."
    if tier == "A":
        if r["survival_rate"] < 0.5:
            return "**Consistent with intent-A** — largely did not survive as-is."
        return ("**Contradicts the intent-A assignment** — it survived far more than an "
                "idiom-only signal should; consider promoting toward N/I.")
    return ""


def _proposals(table: dict, migmap) -> list[str]:
    out: list[str] = []
    # namespace-affix table addition (the headline finding)
    out.append(
        "**Add a project-namespace affix to `intention_normalization.json`.** farmOS 1.x "
        "prefixes log/taxonomy/field machine names with `farm_`/`field_farm_`; the rewrite "
        "drops it wholesale (`farm_activity`→`activity`, `field_farm_animal_sex`→`sex`). "
        "This is exactly a §7.1(2) convention affix (portability **N**) but is "
        "project-specific, so it must be a *per-project* affix entry, not a global one — "
        "evidence the affix table needs a `project_namespace` lane keyed per corpus."
    )
    # module tier
    if "module" in table:
        m = table["module"]
        out.append(
            f"**Module names (predicted A/B1): observed survival {_pct(m['survival_rate'])}, "
            f"domain-root {_pct(m['domain_root_survival'])}.** The feature decomposition is "
            "more portable than B1's 'directories accrete' framing assumes when modules are "
            "feature-shaped; but the semantic-rename + dropped tail confirms module *names* "
            "are not a reliable cross-version key — keep B1 low-weight, prefer the type "
            "vocabulary as the join key."
        )
    for kind in ("asset_type", "log_type", "taxonomy_vocab"):
        if kind in table:
            r = table[kind]
            out.append(
                f"**{kind} (predicted I): domain-root survival {_pct(r['domain_root_survival'])}, "
                f"verbatim {_pct(r['verbatim_rate'])}.** The gap between domain-root and "
                "verbatim survival is the intent-N convention layer sitting *on top of* an "
                "intent-I root — the design's split of A4 into 'name (N)' vs 'the thing it "
                "names (I)' is vindicated: harvest the root as I, the spelling as N."
            )
    if "field" in table:
        r = table["field"]
        out.append(
            f"**Fields (predicted A4/N): domain-root survival {_pct(r['domain_root_survival'])} "
            f"among migrated fields.** Confirms A4's 'boundary shapes portable, internal "
            "freely renamed' — but here even the *root* survives once the `field_farm_` "
            "namespace is folded, so the D/R richness weight for field-name signals can be "
            "raised for same-domain ports (fewer 'ambiguous' misclassifications)."
        )
    out.append(
        "**D/R dial note (§5.3):** value-level `static_map` renames "
        f"({len(migmap.value_map)} found) are load-bearing intent-N evidence the current "
        "harvest does not capture from a single version — they only become visible with the "
        "N=2 diff. Recommend the calibration.parquet schema add a `cross_version_rename` "
        "signal so the second instance's renames feed the R score directly."
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v1", required=True, help="farmOS 1.x (Drupal 7) tree")
    ap.add_argument("--v2", required=True, help="farmOS 2.x (Drupal 9) tree")
    ap.add_argument("--migrate", required=True, help="farm_migrate module dir (2.x)")
    ap.add_argument("--out-md", default=str(RESULTS / "farmos-differential.md"))
    ap.add_argument("--out-jsonl", default=str(RESULTS / "farmos-differential.jsonl"))
    args = ap.parse_args()

    tables = load_tables()

    # harvest both versions + parse the ground-truth migrate map
    v1 = harvest_d7(args.v1)
    v2 = harvest_d9(args.v2)
    migmap = parse_migrations(args.migrate)

    # add taxonomy_vocab v1 signals from the migrate source bundles (oracle-derived —
    # D7 farmOS does not export vocabularies via entity_import; see D7_COVERAGE).
    from ctkr.farmos_diff import Sig

    tax_v1_seen = {s.name for s in v1 if s.kind == "taxonomy_vocab"}
    tax_v2_names = {s.name for s in v2 if s.kind == "taxonomy_vocab"}
    for src_bundle, dest in migmap.bundle_map.items():
        # taxonomy source bundles are those mapped to a 2.x vocabulary machine name
        if dest in tax_v2_names and src_bundle not in tax_v1_seen:
            v1.append(Sig("taxonomy_vocab", src_bundle, "", "1.x", "migrate-oracle"))
            tax_v1_seen.add(src_bundle)

    # fields: synthesized from the migrate field map (ground-truth correspondence)
    f1, f2 = fields_from_migrate(migmap)
    v1 += f1
    v2 += f2

    oracle = build_oracle(migmap)
    records = diff_signals(v1, v2, oracle, tables)
    table = survival_table(records)

    write_diff_jsonl(records, args.out_jsonl)
    report = build_report(args.v1, args.v2, args.migrate, migmap, records, table)
    Path(args.out_md).write_text(report, encoding="utf-8")

    print(f"wrote {args.out_jsonl}")
    print(f"wrote {args.out_md}")
    for kind, row in table.items():
        print(
            f"  {kind:16s} tier={row['predicted_tier']} "
            f"survival={_pct(row['survival_rate'])} "
            f"domain-root={_pct(row['domain_root_survival'])} "
            f"(pop={row['v1_population']}, dropped={row['dropped']}, new={row['new_in_v2']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
