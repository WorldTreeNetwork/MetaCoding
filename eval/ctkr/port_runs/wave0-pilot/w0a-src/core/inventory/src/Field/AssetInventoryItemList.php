<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Field;

use Drupal\Core\Field\FieldItemList;
use Drupal\Core\TypedData\ComputedItemListTrait;
use Drupal\asset\Entity\AssetInterface;

/**
 * Computes the current inventory value for assets.
 */
class AssetInventoryItemList extends FieldItemList {

  use ComputedItemListTrait;

  /**
   * Computes the current inventory value for the asset.
   */
  protected function computeValue() {

    // Get the asset entity.
    $entity = $this->getEntity();

    // Get the asset's current inventories.
    assert($entity instanceof AssetInterface);
    $inventories = \Drupal::service('asset.inventory')->getInventory($entity);

    // Update the assets current inventory values to match.
    // @todo Cache this field computation.
    foreach ($inventories as $delta => $inventory) {
      $this->list[$delta] = $this->createItem($delta, $inventory);
    }
  }

}
