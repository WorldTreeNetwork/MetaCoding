<?php

declare(strict_types=1);

namespace Drupal\quantity\Hook;

use Drupal\Core\Config\ConfigFactoryInterface;
use Drupal\Core\Hook\Attribute\Hook;

/**
 * API hook implementations for quantity.
 */
class ApiHooks {

  public function __construct(
    protected ConfigFactoryInterface $configFactory,
  ) {}

  /**
   * Implements hook_farm_api_meta_alter().
   */
  #[Hook('farm_api_meta_alter')]
  public function farmApiMetaAlter(&$data) {

    // Add the quantity system of measurement.
    $data['system_of_measurement'] = $this->configFactory->get('quantity.settings')->get('system_of_measurement');
  }

}
