// MetaCoding-87t: drive the LIVE port bridge over its line protocol — the
// exact surface port-verify exercises — so the wire-level pieces the store
// tests cannot see are covered: the top-level `lot_number` wire field landing
// in extras, the `bundle` -> quantityType normalization feeding
// material_quantity, and the unanswerable channel for ghost subjects on all
// three new probes.

import { test, expect } from "bun:test";

interface Reply {
  id?: number;
  ok: boolean;
  value?: unknown;
  unanswerable?: boolean;
  unsupported?: boolean;
  error?: string;
}

// One live bridge session: fixture-shaped record flows, then the probes, all
// on handles the bridge itself echoed back (handles are per-session mints).
async function driveSession() {
  const proc = Bun.spawn({
    cmd: ["bun", "run", new URL("../port_bridge.ts", import.meta.url).pathname],
    stdin: "pipe",
    stdout: "pipe",
    stderr: "inherit",
  });
  const decoder = new TextDecoder();
  const reader = proc.stdout.getReader();
  let buf = "";
  let next = 0;
  async function call(r: Record<string, unknown>): Promise<Reply> {
    const id = next++;
    proc.stdin.write(JSON.stringify({ id, ...r }) + "\n");
    await proc.stdin.flush();
    for (;;) {
      const nl = buf.indexOf("\n");
      if (nl >= 0) {
        const line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        const reply = JSON.parse(line) as Reply;
        if (reply.id === id) return reply;
        continue;
      }
      const { value, done } = await reader.read();
      if (done) throw new Error("bridge closed early");
      buf += decoder.decode(value);
    }
  }

  await call({ op: "create_asset", entity: "land", name: "Plot" });
  const lottedLog = (await call({
    op: "record_log", kind: "harvest", name: "Lotted", status: "done",
    assets: [], quantities: [{ measure: "weight", value: 5, unit: "kilogram", bundle: "" }],
    lot_number: "w2x-LOT-A1",
  })).value;
  const unlottedLog = (await call({
    op: "record_log", kind: "harvest", name: "Unlotted", status: "done",
    assets: [], quantities: [{ measure: "weight", value: 5, unit: "kilogram", bundle: "" }],
    lot_number: "",
  })).value;
  const twoQtyLog = (await call({
    op: "record_log", kind: "input", name: "Two quantities", status: "done",
    assets: [], quantities: [
      { measure: "weight", value: 2, unit: "kilogram", bundle: "" },
      { measure: "weight", value: 3, unit: "kilogram", bundle: "" },
    ],
  })).value;
  const materialLog = (await call({
    op: "record_log", kind: "input", name: "Material qty", status: "done",
    assets: [], quantities: [{ measure: "weight", value: 5, unit: "kilogram", bundle: "material" }],
  })).value;
  const emptyLog = (await call({
    op: "record_log", kind: "input", name: "No qty", status: "done",
    assets: [], quantities: [],
  })).value;

  const result = {
    describe: await call({ op: "describe" }),
    lotted: (await call({ op: "lot_number", log: lottedLog })).value,
    unlotted: (await call({ op: "lot_number", log: unlottedLog })).value,
    ghostLot: await call({ op: "lot_number", log: "log:GHOST-1" }),
    materialQuantityStd: (await call({ op: "material_quantity", log: twoQtyLog })).value,
    materialQuantityMat: (await call({ op: "material_quantity", log: materialLog })).value,
    materialQuantityEmpty: (await call({ op: "material_quantity", log: emptyLog })).value,
    ghostMaterial: await call({ op: "material_quantity", log: "log:GHOST-2" }),
    quantitySum: (await call({ op: "quantity_recorded", log: twoQtyLog, measure: "weight", unit: "kilogram" })).value,
    ghostQuantity: await call({ op: "quantity_recorded", log: "log:GHOST-3", measure: "weight", unit: "kilogram" }),
  };
  await call({ op: "close" }).catch(() => undefined);
  reader.releaseLock();
  await proc.exited;
  return result;
}

test("bridge round-trip: the three new probes answer the pack's contrasts and refuse ghosts", async () => {
  const s = await driveSession();

  // manifest and bridge agree on the declared surface
  const probes = (s.describe.value as { probes: string[] }).probes;
  expect(probes).toContain("lot_number");
  expect(probes).toContain("material_quantity");
  expect(probes).toContain("quantity_recorded");

  // lot_number: stated reads back; unstated is the '' VALUE; ghost refuses
  expect(s.lotted).toBe("w2x-LOT-A1");
  expect(s.unlotted).toBe("");
  expect(s.ghostLot.ok).toBe(false);
  expect(s.ghostLot.unanswerable).toBe(true);

  // material_quantity: wire bundle "" is recorded standard; "material" rides;
  // a quantity-less log answers ''; ghost refuses
  expect(s.materialQuantityStd).toBe("standard");
  expect(s.materialQuantityMat).toBe("material");
  expect(s.materialQuantityEmpty).toBe("");
  expect(s.ghostMaterial.ok).toBe(false);
  expect(s.ghostMaterial.unanswerable).toBe(true);

  // quantity_recorded: the two-quantity fixture's 2+3 -> 5; ghost refuses
  expect(s.quantitySum).toBe(5);
  expect(s.ghostQuantity.ok).toBe(false);
  expect(s.ghostQuantity.unanswerable).toBe(true);
});
