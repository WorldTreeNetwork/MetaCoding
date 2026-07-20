<?php

declare(strict_types=1);

namespace Drupal\quantity;

use Drupal\Core\Entity\ContentEntityInterface;
use Drupal\Core\Field\FieldStorageDefinitionInterface;

/**
 * Helper methods for quantity.
 */
class QuantityHelper {

  /**
   * Define information about available quantity measures.
   *
   * @return array
   *   Returns an array of measure information.
   */
  public static function quantityMeasures(): array {
    return [
      'count' => [
        'label' => t('Count'),
      ],
      'length' => [
        'label' => t('Length/depth'),
      ],
      'weight' => [
        'label' => t('Weight'),
      ],
      'area' => [
        'label' => t('Area'),
      ],
      'volume' => [
        'label' => t('Volume'),
      ],
      'time' => [
        'label' => t('Time'),
      ],
      'temperature' => [
        'label' => t('Temperature'),
      ],
      'pressure' => [
        'label' => t('Pressure'),
      ],
      'water_content' => [
        'label' => t('Water content'),
      ],
      'value' => [
        'label' => t('Value'),
      ],
      'rate' => [
        'label' => t('Rate'),
      ],
      'rating' => [
        'label' => t('Rating'),
      ],
      'ratio' => [
        'label' => t('Ratio'),
      ],
      'probability' => [
        'label' => t('Probability'),
      ],
      'speed' => [
        'label' => t('Speed'),
      ],
    ];
  }

  /**
   * Quantity measure options helper.
   *
   * @return array
   *   Returns an array of quantity measures for use in form select options.
   */
  public static function quantityMeasureOptions(): array {

    // Start an empty options array.
    $options = [];

    // Load information about measures.
    $measures = QuantityHelper::quantityMeasures();

    // Iterate through the measures and build a list of options.
    foreach ($measures as $measure => $data) {
      $options[$measure] = $data['label'];
    }

    // Return the array of options.
    return $options;
  }

  /**
   * Allowed values callback function for the quantity measure field.
   *
   * @param \Drupal\Core\Field\FieldStorageDefinitionInterface $definition
   *   The field definition.
   * @param \Drupal\Core\Entity\ContentEntityInterface|null $entity
   *   The entity being created if applicable.
   * @param bool $cacheable
   *   Boolean indicating if the allowed values can be cached. Defaults to TRUE.
   *
   * @return array
   *   Returns an array of allowed values for use in form select options.
   */
  public static function quantityMeasureAllowedValues(FieldStorageDefinitionInterface $definition, ?ContentEntityInterface $entity = NULL, bool &$cacheable = TRUE): array {
    return QuantityHelper::quantityMeasureOptions();
  }

}
