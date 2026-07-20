<?php

declare(strict_types=1);

namespace Drupal\farm_birth\Hook;

use Drupal\Core\Entity\Display\EntityViewDisplayInterface;
use Drupal\Core\Entity\EntityTypeManagerInterface;
use Drupal\Core\Hook\Attribute\Hook;
use Drupal\Core\Url;
use Drupal\asset\Entity\AssetInterface;

/**
 * Theme hook implementations for farm_birth.
 */
class ThemeHooks {

  public function __construct(
    protected EntityTypeManagerInterface $entityTypeManager,
  ) {}

  /**
   * Implements hook_ENTITY_TYPE_view_alter().
   */
  #[Hook('asset_view_alter')]
  public function assetViewAlter(array &$build, AssetInterface $asset, EntityViewDisplayInterface $display) {

    // Only alter animal assets.
    if ($asset->bundle() != 'animal') {
      return;
    }

    // Add a link to the asset's birth log.
    if (!empty($build['birthdate'][0])) {
      $log_storage = $this->entityTypeManager->getStorage('log');
      $log_ids = $log_storage->getQuery()
        ->accessCheck(TRUE)
        ->condition('type', 'birth')
        ->condition('asset', $asset->id())
        ->execute();

      // Render a link to the log with a title of the timestamp field value.
      if (!empty($log_ids)) {
        $title = $build['birthdate'][0];
        $build['birthdate'][0] = [
          '#type' => 'link',
          '#title' => $title,
          '#url' => Url::fromRoute('entity.log.canonical', ['log' => reset($log_ids)]),
        ];
      }
    }
  }

}
