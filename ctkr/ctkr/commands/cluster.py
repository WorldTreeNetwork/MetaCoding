"""``ctkr cluster`` — (stub) role-cluster discovery.

Owned by :issue:`Orchestrators-0l9` (CTKR L3/C2 — Role-cluster labeler).
Note: while the labeler is L3, the actual clustering will likely sit in
L1/C3 (the NN-index issue) — the boundary will be drawn cleanly when
the embedding pipeline ships.
"""

from ctkr.commands._stubs import make_stub

register, _run = make_stub(
    name="cluster",
    summary="(stub) Discover role clusters by embedding-space proximity.",
    description=(
        "Cluster symbols by structural role using the embeddings + NN index. "
        "Not yet implemented; owned by Orchestrators-0l9 (and depends on "
        "Orchestrators-7u7, Orchestrators-1l9)."
    ),
    owning_issue="Orchestrators-0l9",
)
