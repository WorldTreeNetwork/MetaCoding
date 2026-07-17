"""Value-equivalence oracle (port-loop Phase 2, bead MetaCoding-04q).

Acceptance = same VALUE delivered, not same data model. Semantic fixtures in
domain-glossary terms, distilled from observed behavior of a live farmOS at its
JSON:API boundary, verified through a thin per-implementation adapter.

Modules:

* :mod:`ctkr.oracle.glossary` — the closed domain vocabulary + storage-leak lint.
* :mod:`ctkr.oracle.fixtures` — semantic-fixture schema, JSONL IO, validator.
* :mod:`ctkr.oracle.adapter` — the implementation-adapter contract.
* :mod:`ctkr.oracle.farmos_adapter` — the live-farmOS JSON:API adapter.
* :mod:`ctkr.oracle.recorder` — scripted value-flows → distilled fixtures.
* :mod:`ctkr.oracle.runner` — verify fixtures against any adapter (pass/fail).
"""

from __future__ import annotations

__all__ = [
    "adapter",
    "farmos_adapter",
    "fixtures",
    "glossary",
    "recorder",
    "runner",
]
