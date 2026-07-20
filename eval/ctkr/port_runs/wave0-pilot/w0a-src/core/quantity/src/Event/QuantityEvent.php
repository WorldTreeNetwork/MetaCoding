<?php

declare(strict_types=1);

namespace Drupal\quantity\Event;

use Drupal\quantity\Entity\QuantityInterface;
use Symfony\Contracts\EventDispatcher\Event;

/**
 * Event that is fired by hook_quantity_OPERATION().
 */
class QuantityEvent extends Event {

  const PRESAVE = 'quantity_presave';
  const DELETE = 'quantity_delete';

  public function __construct(
    public QuantityInterface $quantity,
  ) {}

}
