// JUDGE shim: exposes makeAdapter() = the composed store's LOCATION adapter.
import { createComposedStore } from "../build/src/index";
export function makeAdapter() {
  return createComposedStore().location;
}
