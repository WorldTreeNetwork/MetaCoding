"""Throwaway spike prep: join hom_profiles.parquet + export/nodes.jsonl into
profiles.jsonl {symbol_id, qualified_name, kind, profile_vec} for one data dir.
Run: uv run python prep.py <data-dir>"""
import json, sys
import polars as pl

data_dir = sys.argv[1]
prof = pl.read_parquet(f"{data_dir}/ctkr/hom_profiles.parquet")
kind_by_id = {}
qn_by_id = {}
for line in open(f"{data_dir}/ctkr/export/nodes.jsonl"):
    n = json.loads(line)
    kind_by_id[n["id"]] = n["kind"]
    qn_by_id[n["id"]] = n["qualified_name"]

out = f"{data_dir}/ctkr/profiles.jsonl"
n = 0
with open(out, "w") as f:
    for r in prof.iter_rows(named=True):
        sid = r["symbol_id"]
        f.write(json.dumps({
            "symbol_id": sid,
            "qualified_name": r["qualified_name"],
            "kind": kind_by_id.get(sid, "unknown"),
            "profile_vec": list(r["profile_vec"]),
        }) + "\n")
        n += 1
print(f"wrote {n} profiles -> {out}")
