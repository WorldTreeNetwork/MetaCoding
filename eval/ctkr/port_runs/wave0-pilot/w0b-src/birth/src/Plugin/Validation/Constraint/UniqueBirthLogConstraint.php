<?php

declare(strict_types=1);

namespace Drupal\farm_birth\Plugin\Validation\Constraint;

use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\Core\Validation\Attribute\Constraint;
use Symfony\Component\Validator\Constraint as SymfonyConstraint;

/**
 * Checks that only one birth log references an asset.
 */
#[Constraint(
  id: 'UniqueBirthLog',
  label: new TranslatableMarkup('Unique birth log', ['context' => 'Validation']),
)]
class UniqueBirthLogConstraint extends SymfonyConstraint {

  /**
   * The default violation message.
   *
   * @var string
   */
  public string $message = '%child already has a birth log. More than one birth log cannot reference the same child.';

}
