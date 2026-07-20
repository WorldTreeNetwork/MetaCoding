<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Hook;

use Drupal\Component\Datetime\TimeInterface;
use Drupal\Core\Cache\CacheTagsInvalidatorInterface;
use Drupal\Core\Hook\Attribute\Hook;
use Drupal\asset\Entity\AssetInterface;
use Drupal\log\Entity\LogInterface;
use Drupal\quantity\Entity\QuantityInterface;

/**
 * Entity hook implementations for farm_inventory.
 */
class EntityHooks {

  public function __construct(
    protected CacheTagsInvalidatorInterface $cacheTagsInvalidator,
    protected TimeInterface $time,
  ) {}

  /**
   * Implements hook_ENTITY_TYPE_presave().
   */
  #[Hook('log_presave')]
  public function logPresave(LogInterface $log) {
    $this->invalidateAssetCacheOnInventoryChange($log);
  }

  /**
   * Implements hook_ENTITY_TYPE_delete().
   */
  #[Hook('log_delete')]
  public function logDelete(LogInterface $log) {
    $this->invalidateAssetCacheOnInventoryChange($log);
  }

  /**
   * Invalidate asset caches when assets inventory changes.
   *
   * @param \Drupal\log\Entity\LogInterface $log
   *   The Log entity.
   */
  protected function invalidateAssetCacheOnInventoryChange(LogInterface $log): void {

    // Keep track if we need to invalidate the cache of referenced assets so
    // the computed 'inventory' field is updated.
    $update_asset_cache = FALSE;

    // If the log is an active quantity measurement, invalidate the cache.
    if ($this->isActiveQuantityLog($log)) {
      $update_asset_cache = TRUE;
    }

    // If updating an existing inventory log, invalidate the cache.
    // This catches inventory logs changing from done to another status.
    if (!empty($log->getOriginal()) && $this->isActiveQuantityLog($log->getOriginal())) {
      $update_asset_cache = TRUE;
    }

    // If an update is not necessary, bail.
    if (!$update_asset_cache) {
      return;
    }

    // Build a list of cache tags.
    // @todo Only invalidate cache if the log changes the asset's inventory. This might be different for each asset.
    $tags = [];

    // Include assets that were previously referenced by inventory adjustments.
    if (!empty($log->getOriginal())) {
      array_push($tags, ...$this->getInventoryAssetCacheTags($log->getOriginal()));
    }

    // Include assets currently referenced by the log.
    array_push($tags, ...$this->getInventoryAssetCacheTags($log));

    // Invalidate the cache tags.
    $this->cacheTagsInvalidator->invalidateTags($tags);
  }

  /**
   * Helper function to determine if a log is active and has quantities.
   *
   * @param \Drupal\log\Entity\LogInterface $log
   *   The log to check.
   *
   * @return bool
   *   Boolean indicating if the log is active.
   */
  protected function isActiveQuantityLog(LogInterface $log): bool {
    return $log->get('status')->value == 'done' && $log->get('timestamp')->value <= $this->time->getCurrentTime() && !$log->get('quantity')->isEmpty();
  }

  /**
   * Helper function to load asset cache tags from the inventory_asset field.
   *
   * @param \Drupal\log\Entity\LogInterface $log
   *   The log to check.
   *
   * @return string[]
   *   An array of cache tags.
   */
  protected function getInventoryAssetCacheTags(LogInterface $log): array {

    // Filter to only log quantities with an inventory adjustment.
    $quantities = array_filter($log->get('quantity')->referencedEntities(), function (QuantityInterface $quantity) {
      return in_array($quantity->get('inventory_adjustment')->value, ['reset', 'increment', 'decrement']) && !$quantity->get('inventory_asset')->isEmpty();
    });

    // Collect cache tags from assets referenced by the inventory_asset field.
    $cache_tags = array_map(function (QuantityInterface $quantity) {
      $asset_tags = array_map(function (AssetInterface $asset) {
        return $asset->getCacheTags();
      }, $quantity->get('inventory_asset')->referencedEntities());
      return array_merge(...$asset_tags);
    }, $quantities);

    // Return all cache tags.
    return array_merge(...$cache_tags);
  }

}
