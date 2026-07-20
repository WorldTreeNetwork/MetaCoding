<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Plugin\views\field;

use Drupal\views\Attribute\ViewsField;
use Drupal\views\Plugin\views\field\EntityField;

/**
 * A field that displays asset inventory.
 *
 * @ingroup views_field_handlers
 */
#[ViewsField("asset_inventory")]
class AssetInventory extends EntityField {

}
