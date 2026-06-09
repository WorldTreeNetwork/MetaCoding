"""Tests for ctkr.label_roles — clustering, ID stability, prompt rendering."""

from __future__ import annotations

import polars as pl
import pytest

from ctkr.label_roles import (
    DEFAULT_GRANULARITY,
    SOURCE_KIND,
    RoleCluster,
    cluster_id_for_members,
    compute_role_clusters,
    pattern_id_for_role_cluster,
    profile_bucket_key,
    render_prompt,
)

# ---------- profile_bucket_key ----------


def test_bucket_key_identical_raw_counts_match() -> None:
    a = [1, 2, 3, 0]
    b = [1, 2, 3, 0]
    assert profile_bucket_key(a, 4) == profile_bucket_key(b, 4)


def test_bucket_key_scale_invariant_within_normalisation() -> None:
    # [1,1,2] and [10,10,20] both normalise to [0.25, 0.25, 0.5].
    assert profile_bucket_key([1, 1, 2], 4) == profile_bucket_key([10, 10, 20], 4)


def test_bucket_key_zero_vector_is_stable_distinct_key() -> None:
    zero_a = profile_bucket_key([0, 0, 0, 0], 4)
    zero_b = profile_bucket_key([0, 0, 0, 0], 4)
    assert zero_a == zero_b
    nonzero = profile_bucket_key([1, 0, 0, 0], 4)
    assert zero_a != nonzero


def test_bucket_key_granularity_can_split_or_collapse() -> None:
    # a normalises to [0.3, 0.7], b to [0.5, 0.5].
    a = [3, 7]
    b = [5, 5]
    # k=2: a rounds to [0.5, 0.5], b is [0.5, 0.5] → same key (collapsed).
    assert profile_bucket_key(a, 2) == profile_bucket_key(b, 2)
    # k=10: distinct.
    assert profile_bucket_key(a, 10) != profile_bucket_key(b, 10)


def test_bucket_key_rejects_non_positive_granularity() -> None:
    with pytest.raises(ValueError, match="positive"):
        profile_bucket_key([1, 2, 3], 0)
    with pytest.raises(ValueError, match="positive"):
        profile_bucket_key([1, 2, 3], -1)


# ---------- cluster_id_for_members ----------


def test_cluster_id_is_order_invariant() -> None:
    a = cluster_id_for_members(["c", "a", "b"])
    b = cluster_id_for_members(["a", "b", "c"])
    assert a == b


def test_cluster_id_changes_with_membership() -> None:
    a = cluster_id_for_members(["a", "b", "c"])
    b = cluster_id_for_members(["a", "b", "d"])
    assert a != b


# ---------- compute_role_clusters ----------


def _profiles_df(rows: list[tuple[str, list[int]]]) -> pl.DataFrame:
    """Build a minimal hom_profiles DataFrame from (symbol_id, vec) tuples."""
    return pl.DataFrame(
        {
            "symbol_id": [r[0] for r in rows],
            "repo": ["r"] * len(rows),
            "qualified_name": [r[0] for r in rows],
            "profile_vec": [r[1] for r in rows],
            "schema_version": [1] * len(rows),
        }
    )


def test_clusters_group_by_bucket_key() -> None:
    # Three symbols with the same normalised shape, two with another, one alone.
    df = _profiles_df(
        [
            ("s1", [1, 1, 0, 0]),
            ("s2", [2, 2, 0, 0]),
            ("s3", [10, 10, 0, 0]),
            ("s4", [0, 1, 1, 0]),
            ("s5", [0, 2, 2, 0]),
            ("s6", [0, 0, 1, 0]),
        ]
    )
    clusters = compute_role_clusters(df, granularity_k=4, min_cluster_size=2)
    # Three same-shape + two same-shape + one singleton → 2 surviving clusters.
    assert len(clusters) == 2
    members_by_size = {c.size: set(c.members) for c in clusters}
    assert members_by_size[3] == {"s1", "s2", "s3"}
    assert members_by_size[2] == {"s4", "s5"}


def test_clusters_drop_isolates_by_default() -> None:
    df = _profiles_df(
        [
            ("z1", [0, 0, 0, 0]),
            ("z2", [0, 0, 0, 0]),
            ("a1", [1, 1, 0, 0]),
            ("a2", [2, 2, 0, 0]),
        ]
    )
    clusters = compute_role_clusters(df, granularity_k=4, min_cluster_size=2)
    assert {c.size for c in clusters} == {2}
    assert all("z1" not in c.members and "z2" not in c.members for c in clusters)


def test_clusters_keep_isolates_when_requested() -> None:
    df = _profiles_df(
        [
            ("z1", [0, 0, 0, 0]),
            ("z2", [0, 0, 0, 0]),
            ("a1", [1, 1, 0, 0]),
            ("a2", [2, 2, 0, 0]),
        ]
    )
    clusters = compute_role_clusters(
        df, granularity_k=4, min_cluster_size=2, drop_isolates=False
    )
    # Two surviving clusters: the all-zeros bucket and the [0.5, 0.5, 0, 0] bucket.
    assert len(clusters) == 2


def test_clusters_drop_singletons() -> None:
    df = _profiles_df([("solo", [1, 2, 3, 0])])
    clusters = compute_role_clusters(df, granularity_k=4, min_cluster_size=2)
    assert clusters == []


def test_clusters_are_deterministic_and_ordered_by_size_desc() -> None:
    df = _profiles_df(
        [
            ("a", [1, 1, 0, 0]),
            ("b", [2, 2, 0, 0]),
            ("c", [3, 3, 0, 0]),
            ("d", [0, 1, 1, 0]),
            ("e", [0, 2, 2, 0]),
        ]
    )
    c1 = compute_role_clusters(df, granularity_k=4, min_cluster_size=2)
    c2 = compute_role_clusters(df, granularity_k=4, min_cluster_size=2)
    assert [c.cluster_id for c in c1] == [c.cluster_id for c in c2]
    # Largest first.
    assert c1[0].size >= c1[-1].size


# ---------- pattern_id_for_role_cluster ----------


def test_pattern_id_is_deterministic_under_same_provenance() -> None:
    a = pattern_id_for_role_cluster(
        "abc12345", prompt_version="role-labeler:v1", llm_model="claude-x"
    )
    b = pattern_id_for_role_cluster(
        "abc12345", prompt_version="role-labeler:v1", llm_model="claude-x"
    )
    assert a == b
    assert a.startswith("role:abc12345@")


def test_pattern_id_changes_with_prompt_version_or_model() -> None:
    base = pattern_id_for_role_cluster(
        "abc12345", prompt_version="role-labeler:v1", llm_model="claude-x"
    )
    v2 = pattern_id_for_role_cluster(
        "abc12345", prompt_version="role-labeler:v2", llm_model="claude-x"
    )
    m2 = pattern_id_for_role_cluster(
        "abc12345", prompt_version="role-labeler:v1", llm_model="claude-y"
    )
    assert base != v2
    assert base != m2
    assert v2 != m2


# ---------- render_prompt ----------


def _stub_evidence_pack(cluster: RoleCluster) -> object:
    """Minimal EvidencePack-shaped stub for prompt rendering."""
    from ctkr.evidence import EvidencePack, InstanceEvidence
    from ctkr.schema_l3 import LineRange

    return EvidencePack(
        source_kind=SOURCE_KIND,
        source_ref=cluster.cluster_id,
        instances=[
            InstanceEvidence(
                symbol_id="s1",
                repo="repoA",
                file="src/a.py",
                qualified_name="a.f",
                kind="function",
                line_range=LineRange(start=1, end=4),
                snippet="def f():\n    return 1\n",
                docstring="A test function.",
                neighbors=[],
            )
        ],
        estimated_tokens=100,
        token_budget=1000,
        truncated=False,
        repos_covered=["repoA"],
        notes=[],
    )


def test_render_prompt_includes_cluster_id_granularity_and_snippet() -> None:
    cluster = RoleCluster(
        cluster_id="cluster-xyz",
        bucket_key="0.5|0.5|0|0",
        members=("s1", "s2"),
    )
    pack = _stub_evidence_pack(cluster)
    prompt = render_prompt(cluster, pack, granularity_k=DEFAULT_GRANULARITY)
    assert "cluster-xyz" in prompt
    assert f"1/{DEFAULT_GRANULARITY} buckets" in prompt
    assert "RoleClusterLabelOutput" in prompt
    assert "def f():" in prompt
