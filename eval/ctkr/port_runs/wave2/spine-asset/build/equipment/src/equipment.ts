// spine-asset · equipment — asset bundle with four optional typed fields and no
// farm_location flags (asset.type.equipment.yml declares neither).
//
//   equipment_type  entity_reference → taxonomy_term(equipment_type), MULTIPLE,
//                   auto_create (term creation NOT modeled — punt spine-asset-autocreate)
//   manufacturer    string
//   model           string
//   serial_number   string
//
// Source: modules/asset/equipment/src/Plugin/Asset/AssetType/Equipment.php.
//
// PUNTED UP (out of this asset-spine surface): farm_equipment also adds an
// `equipment` entity_reference BASE FIELD to the LOG entity ("Equipment used")
// plus CSV-import / Views / field-group wiring (src/Hook/FieldHooks.php,
// ThemeHooks.php). That is a cross-family field on logs, not the asset bundle —
// see punts.jsonl spine-asset-equipment-log-field.

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export interface EquipmentFields {
  equipmentType?: readonly string[];
  manufacturer?: string;
  model?: string;
  serialNumber?: string;
}

export function makeEquipmentAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    createEquipment(name: string, fields: EquipmentFields = {}): Handle {
      return store.createAsset({
        bundle: "equipment",
        name,
        fields: {
          equipment_type: fields.equipmentType,
          manufacturer: fields.manufacturer,
          model: fields.model,
          serial_number: fields.serialNumber,
        },
      });
    },
    archive(asset: Handle): void {
      store.archiveAsset(asset);
    },
    isActive(asset: Handle): boolean {
      return store.assetActive(asset);
    },
    manufacturerOf(asset: Handle): string | undefined {
      return store.fieldOf(asset, "manufacturer") as string | undefined;
    },
    modelOf(asset: Handle): string | undefined {
      return store.fieldOf(asset, "model") as string | undefined;
    },
    serialNumberOf(asset: Handle): string | undefined {
      return store.fieldOf(asset, "serial_number") as string | undefined;
    },
    equipmentTypesOf(asset: Handle): readonly string[] {
      return (store.fieldOf(asset, "equipment_type") as readonly string[] | undefined) ?? [];
    },
    listEquipment(): Handle[] {
      return store.listByBundle("equipment");
    },
  };
}
