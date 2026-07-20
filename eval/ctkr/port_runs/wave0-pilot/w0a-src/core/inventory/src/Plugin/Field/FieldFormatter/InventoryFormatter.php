<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Plugin\Field\FieldFormatter;

use Drupal\Core\Field\Attribute\FieldFormatter;
use Drupal\Core\Field\FieldItemListInterface;
use Drupal\Core\Field\FormatterBase;
use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\quantity\QuantityHelper;

/**
 * Plugin implementation of the 'inventory' formatter.
 */
#[FieldFormatter(
  id: 'inventory',
  label: new TranslatableMarkup('Inventory'),
  field_types: ['inventory'],
)]
class InventoryFormatter extends FormatterBase {

  /**
   * {@inheritdoc}
   */
  public function viewElements(FieldItemListInterface $items, $langcode) {
    /** @var \Drupal\Core\Field\FieldItemList $items */
    $elements = [];

    /** @var \Drupal\farm_inventory\Plugin\Field\FieldType\InventoryItem $item */
    foreach ($items->getIterator() as $delta => $item) {
      $summary = $item->value;
      if (!empty($item->units)) {
        $summary .= ' ' . $item->units;
      }
      if (!empty($item->measure)) {
        $measures = QuantityHelper::quantityMeasures();
        if (!empty($measures[$item->measure]['label'])) {
          $summary .= ' (' . $measures[$item->measure]['label'] . ')';
        }
      }
      $elements[$delta]['value'] = ['#markup' => $summary];
    }

    return $elements;
  }

}
