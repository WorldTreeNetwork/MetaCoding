"""A minimal port bridge. RECURSIVE=1 matches farmOS; RECURSIVE=0 is the
non-transitive last-write-wins register the kernel bound before C1.

The two ports differ in exactly one line. That is the point: the judge must rank
them by which one matches the SOURCE, and before the fix it ranked them the other
way round (the farmOS-matching port scored 95.2% NOT-CLEAN; the diverging one
scored 100% clean).
"""
import json, os, sys

RECURSIVE = os.environ.get("RECURSIVE") == "1"
CAPS = {"operations": ["assign_to_group"], "probes": ["group_member"]}

assets, group_of = [], {}

def handle(req):
    op = req["op"]
    if op == "describe":
        return CAPS
    if op == "reset":
        assets.clear(); group_of.clear(); return True
    if op == "create_asset":
        h = f"h{len(assets)+1}"; assets.append(h); return h
    if op == "assign_to_group":
        group_of[req["asset"]] = req["group"]; return True
    if op == "group_member":
        cur, seen = group_of.get(req["asset"]), set()
        while cur is not None and cur not in seen:
            if cur == req["group"]:
                return True
            if not RECURSIVE:
                return False
            seen.add(cur); cur = group_of.get(cur)
        return False
    if op == "close":
        sys.exit(0)
    raise KeyError(op)

for line in sys.stdin:
    if not line.strip():
        continue
    r = json.loads(line)
    try:
        out = {"id": r.get("id"), "ok": True, "value": handle(r)}
    except Exception as exc:
        out = {"id": r.get("id"), "ok": False, "error": str(exc), "unsupported": True}
    sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
