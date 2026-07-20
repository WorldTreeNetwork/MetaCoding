<?php

declare(strict_types=1);

namespace Drupal\quantity\Entity;

use Drupal\Core\Entity\Attribute\ContentEntityType;
use Drupal\Core\Entity\ContentEntityDeleteForm;
use Drupal\Core\Entity\ContentEntityForm;
use Drupal\Core\Entity\EntityChangedTrait;
use Drupal\Core\Entity\EntityTypeInterface;
use Drupal\Core\Entity\Form\DeleteMultipleForm;
use Drupal\Core\Entity\RevisionLogEntityTrait;
use Drupal\Core\Entity\Sql\SqlContentEntityStorage;
use Drupal\Core\Field\BaseFieldDefinition;
use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\entity\Menu\DefaultEntityLocalTaskProvider;
use Drupal\entity\QueryAccess\UncacheableQueryAccessHandler;
use Drupal\entity\Revision\RevisionableContentEntityBase;
use Drupal\entity\Routing\AdminHtmlRouteProvider;
use Drupal\entity\Routing\RevisionRouteProvider;
use Drupal\entity\UncacheableEntityAccessControlHandler;
use Drupal\entity\UncacheableEntityPermissionProvider;
use Drupal\quantity\Form\QuantityInlineForm;
use Drupal\quantity\QuantityHelper;
use Drupal\quantity\QuantityListBuilder;
use Drupal\quantity\QuantityViewBuilder;
use Drupal\quantity\QuantityViewsData;
use Drupal\user\EntityOwnerTrait;

/**
 * Defines the Quantity entity.
 *
 * @ingroup quantity
 */
#[ContentEntityType(
  id: 'quantity',
  label: new TranslatableMarkup('Quantity'),
  label_collection: new TranslatableMarkup('Quantities'),
  label_singular: new TranslatableMarkup('quantity'),
  label_plural: new TranslatableMarkup('quantities'),
  entity_keys: [
    'id' => 'id',
    'revision' => 'revision_id',
    'bundle' => 'type',
    'label' => 'label',
    'owner' => 'uid',
    'uuid' => 'uuid',
  ],
  handlers: [
    'storage' => SqlContentEntityStorage::class,
    'access' => UncacheableEntityAccessControlHandler::class,
    'inline_form' => QuantityInlineForm::class,
    'list_builder' => QuantityListBuilder::class,
    'permission_provider' => UncacheableEntityPermissionProvider::class,
    'query_access' => UncacheableQueryAccessHandler::class,
    'view_builder' => QuantityViewBuilder::class,
    'views_data' => QuantityViewsData::class,
    'form' => [
      'default' => ContentEntityForm::class,
      'add' => ContentEntityForm::class,
      'edit' => ContentEntityForm::class,
      'delete' => ContentEntityDeleteForm::class,
      'delete-multiple-confirm' => DeleteMultipleForm::class,
    ],
    'route_provider' => [
      'default' => AdminHtmlRouteProvider::class,
      'revision' => RevisionRouteProvider::class,
    ],
    'local_task_provider' => [
      'default' => DefaultEntityLocalTaskProvider::class,
    ],
  ],
  links: [
    'delete-multiple-form' => '/quantity/delete',
  ],
  admin_permission: 'administer quantity',
  collection_permission: 'access quantity collection',
  permission_granularity: 'bundle',
  bundle_entity_type: 'quantity_type',
  base_table: 'quantity',
  revision_table: 'quantity_revision',
  translatable: FALSE,
  show_revision_ui: FALSE,
  label_count: [
    'singular' => '@count quantity',
    'plural' => '@count quantities',
  ],
  common_reference_target: TRUE,
  revision_metadata_keys: [
    'revision_user' => 'revision_user',
    'revision_created' => 'revision_created',
    'revision_log_message' => 'revision_log_message',
  ],
)]
class Quantity extends RevisionableContentEntityBase implements QuantityInterface {

  use EntityChangedTrait;
  use EntityOwnerTrait;
  use RevisionLogEntityTrait;

  /**
   * {@inheritdoc}
   */
  public function label() {
    return $this->id->value;
  }

  /**
   * {@inheritdoc}
   */
  public function getCreatedTime() {
    return $this->get('created')->value;
  }

  /**
   * {@inheritdoc}
   */
  public function setCreatedTime($timestamp) {
    $this->set('created', $timestamp);
    return $this;
  }

  /**
   * {@inheritdoc}
   */
  public static function getCurrentUserId() {
    return [\Drupal::currentUser()->id()];
  }

  /**
   * {@inheritdoc}
   */
  public static function getRequestTime() {
    return \Drupal::time()->getRequestTime();
  }

  /**
   * {@inheritdoc}
   */
  public function getBundleLabel() {
    /** @var \Drupal\quantity\Entity\QuantityTypeInterface $type */
    $type = $this->entityTypeManager()
      ->getStorage('quantity_type')
      ->load($this->bundle());
    return $type->label();
  }

  /**
   * {@inheritdoc}
   */
  public static function baseFieldDefinitions(EntityTypeInterface $entity_type) {
    $fields = parent::baseFieldDefinitions($entity_type);
    $fields += static::ownerBaseFieldDefinitions($entity_type);
    $fields += static::revisionLogBaseFieldDefinitions($entity_type);

    $fields['measure'] = BaseFieldDefinition::create('list_string')
      ->setLabel(t('Measure'))
      ->setDescription(t('The measure of the quantity.'))
      ->setRevisionable(TRUE)
      ->setSettings([
        'allowed_values_function' => [QuantityHelper::class, 'quantityMeasureAllowedValues'],
      ])
      ->setDisplayOptions('view', [
        'label' => 'hidden',
        'type' => 'list_default',
        'weight' => 0,
      ])
      ->setDisplayOptions('form', [
        'type' => 'options_select',
        'weight' => 0,
      ])
      ->setDisplayConfigurable('form', FALSE)
      ->setDisplayConfigurable('view', FALSE);

    $fields['value'] = BaseFieldDefinition::create('fraction')
      ->setLabel(t('Value'))
      ->setDescription(t('Value of the quantity.'))
      ->setRevisionable(TRUE)
      ->setDisplayOptions('view', [
        'label' => 'hidden',
        'type' => 'fraction_decimal',
        'weight' => 5,
        'settings' => [
          'precision' => 0,
          'auto_precision' => TRUE,
          'separator' => '/',
          'prefix_suffix' => FALSE,
        ],
      ])
      ->setDisplayOptions('form', [
        'type' => 'fraction_decimal',
        'weight' => 5,
        'settings' => [
          'precision' => 0,
          'auto_precision' => TRUE,
        ],
      ])
      ->setDisplayConfigurable('form', FALSE)
      ->setDisplayConfigurable('view', FALSE);

    $fields['units'] = BaseFieldDefinition::create('entity_reference')
      ->setLabel(t('Units'))
      ->setDescription(t('Units of the quantity.'))
      ->setSetting('target_type', 'taxonomy_term')
      ->setSetting('handler_settings', [
        'target_bundles' => [
          'unit' => 'unit',
        ],
        'auto_create' => TRUE,
        'auto_create_bundle' => 'unit',
      ])
      ->setSetting('handler', 'default')
      ->setRevisionable(TRUE)
      ->setDisplayOptions('view', [
        'label' => 'hidden',
        'type' => 'entity_reference_label',
        'settings' => [
          'link' => FALSE,
        ],
        'weight' => 10,
      ])
      ->setDisplayOptions('form', [
        'type' => 'entity_reference_autocomplete',
        'weight' => 10,
      ])
      ->setDisplayConfigurable('form', FALSE)
      ->setDisplayConfigurable('view', FALSE);

    $fields['label'] = BaseFieldDefinition::create('string')
      ->setLabel(t('Label'))
      ->setDescription(t('Label of the quantity.'))
      ->setRevisionable(TRUE)
      ->setDefaultValue('')
      ->setSetting('max_length', 255)
      ->setSetting('text_processing', 0)
      ->setDisplayOptions('view', [
        'label' => 'hidden',
        'type' => 'string',
        'weight' => 15,
      ])
      ->setDisplayOptions('form', [
        'type' => 'string_textfield',
        'weight' => 15,
      ])
      ->setDisplayConfigurable('form', FALSE)
      ->setDisplayConfigurable('view', FALSE);

    $fields['uid'] = BaseFieldDefinition::create('entity_reference')
      ->setLabel(t('Authored by'))
      ->setDescription(t('The user ID of author of the quantity.'))
      ->setRevisionable(TRUE)
      ->setSetting('target_type', 'user')
      ->setSetting('handler', 'default')
      ->setDefaultValueCallback('Drupal\quantity\Entity\Quantity::getCurrentUserId')
      ->setDisplayOptions('view', [
        'region' => 'hidden',
      ])
      ->setDisplayOptions('form', [
        'region' => 'hidden',
      ])
      ->setDisplayConfigurable('form', FALSE)
      ->setDisplayConfigurable('view', FALSE);

    $fields['created'] = BaseFieldDefinition::create('created')
      ->setLabel(t('Authored on'))
      ->setDescription(t('The time that the quantity was created.'))
      ->setRevisionable(TRUE)
      ->setDefaultValueCallback(static::class . '::getRequestTime')
      ->setDisplayOptions('view', [
        'region' => 'hidden',
      ])
      ->setDisplayOptions('form', [
        'region' => 'hidden',
      ])
      ->setDisplayConfigurable('form', FALSE)
      ->setDisplayConfigurable('view', FALSE);

    $fields['changed'] = BaseFieldDefinition::create('changed')
      ->setLabel(t('Changed'))
      ->setDescription(t('The time the quantity was last edited.'))
      ->setRevisionable(TRUE);

    return $fields;
  }

}
