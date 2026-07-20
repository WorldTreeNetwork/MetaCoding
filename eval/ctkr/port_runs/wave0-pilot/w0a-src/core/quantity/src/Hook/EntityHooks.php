<?php

declare(strict_types=1);

namespace Drupal\quantity\Hook;

use Drupal\Core\Hook\Attribute\Hook;
use Drupal\quantity\Entity\QuantityInterface;
use Drupal\quantity\Event\QuantityEvent;
use Symfony\Component\DependencyInjection\Attribute\Autowire;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

/**
 * Entity hook implementations for quantity.
 */
class EntityHooks {

  public function __construct(
    #[Autowire(service: 'event_dispatcher')]
    protected EventDispatcherInterface $eventDispatcher,
  ) {}

  /**
   * Implements hook_ENTITY_TYPE_presave().
   */
  #[Hook('quantity_presave')]
  public function quantityPresave(QuantityInterface $quantity) {

    // Dispatch an event on quantity presave.
    // @todo Replace this with core event via https://www.drupal.org/node/2551893.
    $event = new QuantityEvent($quantity);
    $this->eventDispatcher->dispatch($event, QuantityEvent::PRESAVE);
  }

  /**
   * Implements hook_ENTITY_TYPE_delete().
   */
  #[Hook('quantity_delete')]
  public function quantityDelete(QuantityInterface $quantity) {

    // Dispatch an event on quantity delete.
    // @todo Replace this with core event via https://www.drupal.org/node/2551893.
    $event = new QuantityEvent($quantity);
    $this->eventDispatcher->dispatch($event, QuantityEvent::DELETE);
  }

}
