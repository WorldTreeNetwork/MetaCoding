<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Hook;

use Drupal\Core\Hook\Attribute\Hook;
use Drupal\Core\StringTranslation\StringTranslationTrait;

/**
 * Theme hook implementations for farm_inventory.
 */
class ThemeHooks {

  use StringTranslationTrait;

  /**
   * Implements hook_preprocess_HOOK().
   */
  #[Hook('preprocess_quantity')]
  public function preprocessQuantity(array &$variables) {

    /** @var \Drupal\quantity\Entity\QuantityInterface $quantity */
    $quantity = $variables['elements']['#quantity'];
    if (!empty($variables['content']['inventory_adjustment']) && !empty($variables['content']['inventory_asset'])) {

      // Do not render the inventory fields themselves.
      unset($variables['content']['inventory_adjustment']);
      unset($variables['content']['inventory_asset']);

      // Get the adjustment label.
      $adjustment_field = $quantity->get('inventory_adjustment');
      $adjustment_values = $adjustment_field->getFieldDefinition()->getSetting('allowed_values');
      $adjustment = $adjustment_values[$adjustment_field->value];

      // Get the inventory asset.
      $assets = $quantity->get('inventory_asset')->referencedEntities();
      $asset = reset($assets);

      // Render array of inventory info to display after the quantity.
      $inventory = [
        '#prefix' => '<span class="inventory">',
        '#suffix' => '</span>',
        '#markup' => '(' . $this->t('@adjustment <a href=":url">@asset</a> inventory', ['@adjustment' => $adjustment, ':url' => $asset->toUrl()->toString(), '@asset' => $asset->label()]) . ')',
        '#weight' => 5,
      ];
      $variables['content']['inventory'] = $inventory;
    }
  }

}
