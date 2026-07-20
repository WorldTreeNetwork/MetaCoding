<?php

declare(strict_types=1);

namespace Drupal\farm_inventory\Hook;

use Drupal\Core\Entity\EntityTypeInterface;
use Drupal\Core\Hook\Attribute\Hook;
use Drupal\Core\StringTranslation\StringTranslationTrait;
use Drupal\farm_field\FarmFieldFactoryInterface;
use Drupal\farm_inventory\Field\AssetInventoryItemList;

/**
 * Field hook implementations for farm_inventory.
 */
class FieldHooks {

  use StringTranslationTrait;

  public function __construct(
    protected FarmFieldFactoryInterface $farmFieldFactory,
  ) {}

  /**
   * Implements hook_entity_base_field_info().
   */
  #[Hook('entity_base_field_info')]
  public function entityBaseFieldInfo(EntityTypeInterface $entity_type) {

    // Add inventory base fields to entity types.
    if ($entity_type->id() == 'asset') {
      return $this->assetFields();
    }
    elseif ($entity_type->id() == 'quantity') {
      return $this->quantityFields();
    }
    return [];
  }

  /**
   * Define quantity inventory base fields.
   *
   * @return array
   *   Returns an array of field information for use with farm_field.factory.
   */
  private function assetFields(): array {
    $field_info = [
      'inventory' => [
        'type' => 'inventory',
        'label' => $this->t('Current inventory'),
        'multiple' => TRUE,
        'computed' => AssetInventoryItemList::class,
        'hidden' => 'form',
        'weight' => [
          'view' => 94,
        ],
      ],
    ];
    $fields = [];
    foreach ($field_info as $name => $info) {
      $fields[$name] = $this->farmFieldFactory->baseFieldDefinition($info);
    }
    return $fields;
  }

  /**
   * Define quantity inventory base fields.
   *
   * @return array
   *   Returns an array of field information for use with farm_field.factory.
   */
  private function quantityFields(): array {
    $field_info = [
      'inventory_adjustment' => [
        'type' => 'list_string',
        'label' => $this->t('Inventory adjustment'),
        'description' => $this->t('What type of inventory adjustment is this?'),
        'allowed_values' => [
          'increment' => $this->t('Increment'),
          'decrement' => $this->t('Decrement'),
          'reset' => $this->t('Reset'),
        ],
        'multiple' => FALSE,
        'weight' => [
          'form' => 50,
          'view' => 50,
        ],
      ],
      'inventory_asset' => [
        'type' => 'entity_reference',
        'label' => $this->t('Inventory asset'),
        'description' => $this->t('Which asset will this adjust the inventory of?'),
        'target_type' => 'asset',
        'multiple' => FALSE,
        'weight' => [
          'form' => 51,
          'view' => 51,
        ],
      ],
    ];
    $fields = [];
    foreach ($field_info as $name => $info) {
      $fields[$name] = $this->farmFieldFactory->baseFieldDefinition($info);
    }
    return $fields;
  }

}
