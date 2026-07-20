<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Hook;

use Drupal\Core\Hook\Attribute\Hook;
use Drupal\Core\StringTranslation\StringTranslationTrait;

/**
 * Views hook implementations for farm_inventory.
 */
class ViewsHooks {

  use StringTranslationTrait;

  /**
   * Implements hook_views_data_alter().
   */
  #[Hook('views_data_alter')]
  public function viewsDataAlter(array &$data) {

    // Add computed inventory field to assets.
    if (isset($data['asset'])) {
      $data['asset']['inventory'] = [
        'title' => $this->t('Current inventory'),
        'field' => [
          'id' => 'asset_inventory',
          'field_name' => 'inventory',
        ],
      ];
    }
  }

}
