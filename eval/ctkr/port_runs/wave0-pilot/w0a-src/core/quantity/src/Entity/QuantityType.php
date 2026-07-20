<?php

declare(strict_types=1);

namespace Drupal\quantity\Entity;

use Drupal\Core\Config\Entity\ConfigEntityBundleBase;
use Drupal\Core\Entity\Attribute\ConfigEntityType;
use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\entity\BundleEntityAccessControlHandler;

/**
 * Defines the quantity type entity.
 */
#[ConfigEntityType(
  id: 'quantity_type',
  label: new TranslatableMarkup('Quantity type'),
  label_collection: new TranslatableMarkup('Quantity types'),
  label_singular: new TranslatableMarkup('Quantity type'),
  label_plural: new TranslatableMarkup('Quantity types'),
  config_prefix: 'type',
  entity_keys: [
    'id' => 'id',
    'label' => 'label',
    'uuid' => 'uuid',
  ],
  handlers: [
    'access' => BundleEntityAccessControlHandler::class,
  ],
  bundle_of: 'quantity',
  label_count: [
    'singular' => '@count quantity type',
    'plural' => '@count quantity types',
  ],
  config_export: [
    'id',
    'label',
    'description',
    'new_revision',
  ],
)]
class QuantityType extends ConfigEntityBundleBase implements QuantityTypeInterface {

  /**
   * The quantity type ID.
   *
   * @var string
   */
  protected $id;

  /**
   * The quantity type label.
   *
   * @var string
   */
  protected $label;

  /**
   * A brief description of this quantity type.
   *
   * @var string
   */
  protected $description;

  /**
   * Default value of the 'Create new revision' checkbox of the quantity type.
   *
   * @var bool
   */
  protected $new_revision = TRUE;

  /**
   * {@inheritdoc}
   */
  public function getDescription() {
    return $this->description;
  }

  /**
   * {@inheritdoc}
   */
  public function setDescription($description) {
    return $this->set('description', $description);
  }

  /**
   * {@inheritdoc}
   */
  public function shouldCreateNewRevision() {
    return $this->new_revision;
  }

  /**
   * {@inheritdoc}
   */
  public function setNewRevision($new_revision) {
    return $this->set('new_revision', $new_revision);
  }

}
