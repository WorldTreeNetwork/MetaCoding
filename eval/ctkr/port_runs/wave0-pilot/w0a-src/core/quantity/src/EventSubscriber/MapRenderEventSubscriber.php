<?php

declare(strict_types=1);

namespace Drupal\quantity\EventSubscriber;

use Drupal\Core\Config\ConfigFactoryInterface;
use Drupal\farm_map\Event\MapRenderEvent;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

/**
 * An event subscriber for the MapRenderEvent.
 *
 * Adds the quantity.system_of_measurement setting to maps.
 */
class MapRenderEventSubscriber implements EventSubscriberInterface {

  public function __construct(
    protected ConfigFactoryInterface $configFactory,
  ) {}

  /**
   * {@inheritdoc}
   */
  public static function getSubscribedEvents(): array {
    return [
      MapRenderEvent::EVENT_NAME => 'onMapRender',
    ];
  }

  /**
   * React to the MapRenderEvent.
   *
   * @param \Drupal\farm_map\Event\MapRenderEvent $event
   *   The MapRenderEvent.
   *
   * @throws \Drupal\Component\Plugin\Exception\InvalidPluginDefinitionException
   * @throws \Drupal\Component\Plugin\Exception\PluginNotFoundException
   */
  public function onMapRender(MapRenderEvent $event) {

    // Set a cache tag on the quantity settings in case this ever changes.
    $event->addCacheTags(['config:quantity.settings']);

    // Add the system of measurement to drupalSettings.farm_map.units.
    $measurement = $this->configFactory->get('quantity.settings')->get('system_of_measurement');
    $event->element['#attached']['drupalSettings']['farm_map']['units'] = $measurement;
  }

}
