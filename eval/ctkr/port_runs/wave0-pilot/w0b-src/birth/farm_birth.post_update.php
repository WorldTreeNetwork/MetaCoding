<?php

/**
 * @file
 * Post update hooks for the farm_birth module.
 */

declare(strict_types=1);

/**
 * Implements hook_removed_post_updates().
 */
function farm_birth_removed_post_updates() {
  return [
    'farm_birth_post_update_override_birth_asset_label_description' => '4.x',
  ];
}
