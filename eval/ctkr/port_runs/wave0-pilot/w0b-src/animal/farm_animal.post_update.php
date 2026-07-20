<?php

/**
 * @file
 * Post update hooks for the farm_animal module.
 */

declare(strict_types=1);

/**
 * Rename is_castrated to is_sterile on Animal assets.
 */
function farm_animal_post_update_rename_is_castrated_is_sterile(&$sandbox) {

  // Get the Drupal entity definition update manager.
  $update_manager = \Drupal::entityDefinitionUpdateManager();

  // Install the new is_sterile field.
  $options = [
    'type' => 'boolean',
    'label' => t('Sterile'),
    'description' => t('Is this animal sterile?'),
    'weight' => [
      'form' => 26,
    ],
    'view_display_options' => [
      'label' => 'inline',
      'type' => 'hideable_boolean',
      'settings' => [
        'format' => 'default',
        'format_custom_false' => '',
        'format_custom_true' => '',
        'hide_if_false' => TRUE,
      ],
      'weight' => -25,
    ],
  ];
  $field_definition = \Drupal::service('farm_field.factory')->bundleFieldDefinition($options);
  $update_manager->installFieldStorageDefinition('is_sterile', 'asset', 'farm_animal', $field_definition);

  // Copy values from the is_castrated field.
  \Drupal::database()->query('INSERT INTO {asset__is_sterile} (bundle, deleted, entity_id, revision_id, langcode, delta, is_sterile_value) SELECT bundle, deleted, entity_id, revision_id, langcode, delta, is_castrated_value as is_sterile_value FROM {asset__is_castrated}');

  // Delete the old is_castrated field.
  $storage_definition = $update_manager->getFieldStorageDefinition('is_castrated', 'asset');
  $update_manager->uninstallFieldStorageDefinition($storage_definition);

  // Update core.entity_view_display.asset.animal.map_popup config.
  $config = \Drupal::configFactory()->getEditable('core.entity_view_display.asset.animal.map_popup');
  if (!$config->isNew()) {
    $hidden = $config->get('hidden');
    if (isset($hidden['is_castrated'])) {
      unset($hidden['is_castrated']);
      $hidden['is_sterile'] = TRUE;
      $config->set('hidden', $hidden);
      $config->save();
    }
  }
}
