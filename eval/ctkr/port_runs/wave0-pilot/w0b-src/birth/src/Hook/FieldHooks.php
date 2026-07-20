<?php

declare(strict_types=1);

namespace Drupal\farm_birth\Hook;

use Drupal\Core\Entity\EntityTypeInterface;
use Drupal\Core\Field\Entity\BaseFieldOverride;
use Drupal\Core\Hook\Attribute\Hook;

/**
 * Field hook implementations for farm_birth.
 */
class FieldHooks {

  /**
   * Implements hook_entity_bundle_field_info().
   */
  #[Hook('entity_bundle_field_info')]
  public function entityBundleFieldInfo(EntityTypeInterface $entity_type, $bundle, array $base_field_definitions) {
    $fields = [];

    // Add the UniqueBirthLog validation constraint to the asset field of birth
    // logs. We need to do this via hook_entity_bundle_field_info() instead of
    // hook_entity_field_info_alter() because this module also provides a
    // BaseFieldOverride for the asset field, and there is a Drupal core issue
    // that prevents these from working together normally.
    // @see https://www.drupal.org/project/drupal/issues/3193351
    if ($entity_type->id() == 'log' && $bundle == 'birth') {
      $fields['asset'] = BaseFieldOverride::loadByName($entity_type->id(), $bundle, 'asset') ?: clone $base_field_definitions['asset'];
      $fields['asset']->addConstraint('UniqueBirthLog');
    }
    return $fields;
  }

}
