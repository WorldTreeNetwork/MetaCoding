<?php

declare(strict_types=1);

namespace Drupal\farm_birth\Hook;

use Drupal\Core\Hook\Attribute\Hook;
use Drupal\Core\Messenger\MessengerInterface;
use Drupal\Core\StringTranslation\StringTranslationTrait;
use Drupal\log\Entity\LogInterface;

/**
 * Entity hook implementations for farm_birth.
 */
class EntityHooks {

  use StringTranslationTrait;

  public function __construct(
    protected MessengerInterface $messenger,
  ) {}

  /**
   * Implements hook_ENTITY_TYPE_insert().
   */
  #[Hook('log_insert')]
  public function logInsert(LogInterface $log) {
    $this->syncBirthChildren($log);
  }

  /**
   * Implements hook_ENTITY_TYPE_update().
   */
  #[Hook('log_update')]
  public function logUpdate(LogInterface $log) {
    $this->syncBirthChildren($log);
  }

  /**
   * Sync child asset fields to reflect those saved in a birth log.
   *
   * @param \Drupal\log\Entity\LogInterface $log
   *   The log entity.
   */
  public function syncBirthChildren(LogInterface $log): void {

    // If this is not a birth log, bail.
    if ($log->bundle() != 'birth') {
      return;
    }

    // Load mother asset.
    /** @var \Drupal\asset\Entity\AssetInterface[] $mothers */
    $mothers = $log->get('mother')->referencedEntities();
    $mother = reset($mothers);

    // Load children assets.
    /** @var \Drupal\asset\Entity\AssetInterface[] $children */
    $children = $log->get('asset')->referencedEntities();

    // If the log doesn't reference any children, bail.
    if (empty($children)) {
      return;
    }

    // Iterate through the children.
    foreach ($children as $child) {
      $save = FALSE;
      $revision_log = [];

      // If the child is an animal, and their date of birth does not match the
      // timestamp of the birth log, sync it.
      if ($child->bundle() == 'animal' && $child->get('birthdate')->value != $log->get('timestamp')->value) {
        $args = [
          ':child_url' => $child->toUrl()->toString(),
          '%child_name' => $child->label(),
          ':birth_url' => $log->toUrl()->toString(),
        ];
        $message = $this->t('<a href=":child_url">%child_name</a> date of birth was updated to match their <a href=":birth_url">birth log</a>.', $args);
        $this->messenger->addMessage($message);
        $revision_log[] = $message;
        $child->set('birthdate', $log->get('timestamp')->value);
        $save = TRUE;
      }

      // If a mother is specified, and the child does not have any parents,
      // add the mother to the child's parent reference field.
      if (!empty($mother)) {
        $parents = $child->get('parent')->referencedEntities();
        if (empty($parents)) {
          $args = [
            ':mother_url' => $mother->toUrl()->toString(),
            '%mother_name' => $mother->label(),
            ':child_url' => $child->toUrl()->toString(),
            '%child_name' => $child->label(),
          ];
          $message = $this->t('<a href=":mother_url">%mother_name</a> added as a parent of <a href=":child_url">%child_name</a>.', $args);
          $this->messenger->addMessage($message);
          $revision_log[] = $message;
          $child->get('parent')->appendItem($mother->id());
          $save = TRUE;
        }
      }

      // Save the child, if necessary.
      if ($save) {
        $child->setRevisionLogMessage(implode(" ", $revision_log));
        $child->save();
      }
    }
  }

}
