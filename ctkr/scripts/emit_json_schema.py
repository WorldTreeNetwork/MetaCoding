"""Emit JSON Schema files for all pydantic models in schema.py and schema_l3.py.

Design choice: one JSON Schema file per model (not a combined bundle). This
lets quicktype-core load each schema independently and gives cleaner per-type
naming. The combined TS output is assembled by the TS codegen step.

Output directory: .metacoding/ctkr/schemas/<ModelName>.json
(relative to the repo root — this script resolves it from its own location)

Usage:
    uv run python ctkr/scripts/emit_json_schema.py [--out-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo root is two levels up from this script (ctkr/scripts/emit_json_schema.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / ".metacoding" / "ctkr" / "schemas"

# Add the ctkr package to sys.path so we can import without installing
sys.path.insert(0, str(REPO_ROOT / "ctkr"))

from ctkr import schema, schema_l3  # noqa: E402


def _models_from_module(mod: object) -> list[tuple[str, type]]:
    """Return (name, cls) pairs for every pydantic BaseModel in *mod*."""
    from pydantic import BaseModel

    models: list[tuple[str, type]] = []
    for name in getattr(mod, "__all__", []):
        cls = getattr(mod, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            models.append((name, cls))
    return models


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory to write *.json files into (default: {DEFAULT_OUT_DIR})",
    )
    args = parser.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    models = _models_from_module(schema) + _models_from_module(schema_l3)

    for name, cls in models:
        raw = cls.model_json_schema()
        # Inject a top-level annotation so consumers know which schema
        # version produced this file.
        raw["$schema_version"] = schema.SCHEMA_VERSION
        raw["$source_module"] = cls.__module__

        out_path = out_dir / f"{name}.json"
        out_path.write_text(json.dumps(raw, indent=2) + "\n")
        print(f"  wrote {out_path.relative_to(REPO_ROOT)}", flush=True)

    print(f"\n{len(models)} schemas written to {out_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
