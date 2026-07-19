// JUDGE shim: exposes makeAdapter() = the composed store's LOGS adapter.
// A fresh composed store per fixture (the runner calls makeAdapter() per scenario);
// only the logs view is exercised, but it is a thin view over the SAME unified store.
import { createComposedStore } from "../build/src/index";
export function makeAdapter() {
  return createComposedStore().logs;
}
