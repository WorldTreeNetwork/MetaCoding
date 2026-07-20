<?php

/**
 * @file
 * Post update hooks for the quantity module.
 */

declare(strict_types=1);

/**
 * Implements hook_removed_post_updates().
 */
function quantity_removed_post_updates() {
  return [
    'quantity_post_update_plain_text_view_mode' => '4.x',
    'quantity_post_update_delete_action' => '4.x',
  ];
}
