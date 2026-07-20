<?php

declare(strict_types=1);

namespace Drupal\farm_inventory;

use Drupal\asset\Entity\AssetInterface;

/**
 * Asset inventory logic.
 */
interface AssetInventoryInterface {

  /**
   * Get inventory summaries for an asset.
   *
   * @param \Drupal\asset\Entity\AssetInterface $asset
   *   The Asset entity.
   * @param string $measure
   *   The quantity measure of the inventory.
   *   See QuantityHelper::quantityMeasures().
   * @param string|int|null $units
   *   The quantity units of the inventory (term ID).
   * @param int|null $timestamp
   *   Include logs with a timestamp less than or equal to this.
   *   If this is NULL (default), the current time will be used.
   *
   * @return array
   *   Returns an array of asset inventory information.
   */
  public function getInventory(AssetInterface $asset, string $measure = '', string|int|null $units = NULL, int|null $timestamp = NULL): array;

}
