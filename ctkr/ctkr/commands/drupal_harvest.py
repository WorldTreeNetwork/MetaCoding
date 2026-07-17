"""``ctkr drupal-harvest`` — Drupal declarative-config intention lane (Phase 0).

Walks a Drupal codebase's declarative artifacts (config-entity + config-schema
YAML, ``*.routing.yml``, ``*.permissions.yml``, ``*.links.*.yml``, ``.info.yml``,
PHP 8 attribute plugins, ``hook_update_N`` docblocks) and writes three artifacts
under ``<data_dir>/ctkr/``:

* ``drupal_signals.parquet`` — intention signals (IntentionSignalRow schema;
  sibling of ``intention_signals.parquet`` so the two concat rather than clobber);
* ``drupal_config_shapes.parquet`` — config-entity types + fields (ConfigShapeRow);
* ``features.parquet`` — the D1 Feature Inventory (FeatureRow, module ≈ feature).

Independent of scip-php + the structural graph: covers exactly where static PHP
analysis is weakest (hooks, plugins, magic). Deterministic — no LLM, no timestamps
in rows. See :mod:`ctkr.drupal` for the walker and
``docs/design/decomposition-schema.md`` §2 + ``port-loop-plan.md`` Phase 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import resolve_data_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "drupal-harvest",
        help="Drupal declarative-config intention lane (port-loop Phase 0) — "
        "signals + config shapes + feature inventory.",
        description=(
            "Harvest a Drupal codebase's DECLARATIVE artifacts (config/install + "
            "config/schema YAML, routing/permissions/links YAML, .info.yml, PHP 8 "
            "attribute plugins, hook_update_N docblocks) into drupal_signals.parquet "
            "(IntentionSignalRow), drupal_config_shapes.parquet (ConfigShapeRow), and "
            "features.parquet (D1 Feature Inventory, module ≈ feature). Deterministic; "
            "no LLM; independent of scip-php + the structural graph."
        ),
    )
    p.add_argument(
        "--site-root",
        required=True,
        help="Path to the Drupal codebase root (the tree containing the module "
        "*.info.yml files, config/, and src/).",
    )
    p.add_argument(
        "--data-dir",
        default=None,
        help="Path to .metacoding/ where artifacts are written under ctkr/ "
        "(auto-detected by walking up from cwd if omitted).",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the run summary as JSON on stdout.",
    )
    p.add_argument(
        "--generated-at",
        default=None,
        help="Fixed ISO-8601 timestamp for the manifest (byte-identical re-runs). "
        "Does not affect row content (rows carry no timestamp).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.drupal import (
        DRUPAL_CONFIG_SHAPES_FILE,
        DRUPAL_SIGNALS_FILE,
        FEATURES_FILE,
        harvest_site,
        write_config_shapes,
        write_drupal_signals,
        write_features,
        write_manifest,
    )

    site_root = Path(args.site_root).expanduser().resolve()
    if not site_root.exists():
        sys.stderr.write(f"ERROR: --site-root {site_root} does not exist.\n")
        return 2

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    ctkr_dir.mkdir(parents=True, exist_ok=True)

    sys.stderr.write(f"harvesting Drupal declarative artifacts from {site_root}...\n")
    signals_df, config_shapes_df, features_df, stats = harvest_site(site_root)

    if stats.n_modules == 0:
        sys.stderr.write(
            "WARNING: no *.info.yml modules found under --site-root — is this a "
            "Drupal codebase?\n"
        )

    write_drupal_signals(signals_df, ctkr_dir / DRUPAL_SIGNALS_FILE)
    write_config_shapes(config_shapes_df, ctkr_dir / DRUPAL_CONFIG_SHAPES_FILE)
    write_features(features_df, ctkr_dir / FEATURES_FILE)
    manifest_path = write_manifest(
        data_dir,
        n_signals=signals_df.height,
        n_config_shapes=config_shapes_df.height,
        n_features=features_df.height,
        generated_at=args.generated_at,
    )

    sys.stderr.write(
        "\n"
        f"  modules (features)  : {stats.n_modules:,}\n"
        f"  intention signals   : {stats.n_signals:,} "
        f"(by indicator {stats.by_indicator})\n"
        f"  signal tiers        : {stats.by_tier}\n"
        f"  portability tiers   : {stats.by_portability}\n"
        f"  by element kind     : {stats.by_element_kind}\n"
        f"  config shapes       : {stats.n_config_shapes:,}\n"
        f"  routes / perms      : {stats.n_routes} / {stats.n_permissions}\n"
        f"  php attr plugins    : {stats.n_php_plugins}\n"
        f"  update hooks        : {stats.n_update_hooks}\n"
        f"  deferred            : {', '.join(sorted(stats.deferred))}\n"
        f"  artifacts           : {ctkr_dir / DRUPAL_SIGNALS_FILE}\n"
        f"                        {ctkr_dir / DRUPAL_CONFIG_SHAPES_FILE}\n"
        f"                        {ctkr_dir / FEATURES_FILE}\n"
        f"  manifest            : {manifest_path}\n"
        f"  elapsed             : {stats.total_seconds}s\n"
    )

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_modules": stats.n_modules,
                    "n_signals": stats.n_signals,
                    "n_config_shapes": stats.n_config_shapes,
                    "n_features": stats.n_features,
                    "by_indicator": stats.by_indicator,
                    "by_tier": stats.by_tier,
                    "by_portability": stats.by_portability,
                    "by_element_kind": stats.by_element_kind,
                    "n_routes": stats.n_routes,
                    "n_permissions": stats.n_permissions,
                    "n_php_plugins": stats.n_php_plugins,
                    "n_update_hooks": stats.n_update_hooks,
                    "coverage": stats.coverage,
                    "deferred": stats.deferred,
                    "elapsed_seconds": stats.total_seconds,
                    "data_dir": str(Path(data_dir).resolve()),
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    return 0
