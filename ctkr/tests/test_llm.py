"""LLM client tests.

Three layers:

1. Mock-provider tests for cache, cost log, structured output, and
   retry — these run on every push, no API key required.
2. Fail-closed tests for missing API keys.
3. A skip-when-key-missing live smoke test that hits Anthropic for one
   cheap Haiku call. Runs locally when ``ANTHROPIC_API_KEY`` is set;
   skipped on machines that don't have a key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, Field

from ctkr.llm import (
    AnthropicProvider,
    Completion,
    KeyMissingError,
    LLMClient,
    StructuredCompletion,
    StructuredOutputError,
    _ProviderResponse,
)

# ----- mock provider used by most tests -----


class MotifLabel(BaseModel):
    """A motif's natural-language label."""

    label: str = Field(description="short canonical name (~3 words)")
    confidence: float = Field(ge=0, le=1)


@dataclass
class _MockAnthropicProvider:
    """Records calls and returns scripted responses."""

    name: ClassVar[str] = "anthropic"
    env_var: ClassVar[str] = "ANTHROPIC_API_KEY"

    completions: Iterable[str] = field(default_factory=lambda: ["hello", "world"])
    structured: Iterable[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 12
    output_tokens: int = 5
    calls: list[dict[str, Any]] = field(default_factory=list)
    _it: Any = None
    _sit: Any = None

    def __post_init__(self) -> None:
        self._it = iter(self.completions)
        self._sit = iter(self.structured)

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        system: str | None,
    ) -> _ProviderResponse:
        self.calls.append({"prompt": prompt, "model": model, "temperature": temperature})
        return _ProviderResponse(
            text=next(self._it),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )

    def complete_structured(
        self,
        prompt: str,
        *,
        model: str,
        schema: type[BaseModel],
        temperature: float,
        max_tokens: int,
        system: str | None,
    ) -> tuple[_ProviderResponse, dict[str, Any]]:
        self.calls.append({"prompt": prompt, "model": model, "schema": schema.__name__})
        raw = next(self._sit)
        return (
            _ProviderResponse(
                text=json.dumps(raw),
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
            ),
            raw,
        )


# ----- fixtures -----


@pytest.fixture
def client(tmp_path: Path) -> LLMClient:
    c = LLMClient(
        cache_dir=tmp_path / "cache",
        cost_log=tmp_path / "cost.jsonl",
        default_model="claude-haiku-4-5-20251001",
        max_attempts=1,
    )
    return c


# ----- cache + cost telemetry -----


def test_completion_writes_cache_and_cost(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(completions=["first"])
    client.register_provider(mock)

    out = client.complete("ping")
    assert isinstance(out, Completion)
    assert out.text == "first"
    assert out.cache_hit is False
    assert out.cost_estimate_usd > 0  # Haiku is in the price table

    # Cost log has one entry.
    rows = [
        json.loads(line) for line in client.cost_log.read_text().splitlines() if line.strip()  # type: ignore[union-attr]
    ]
    assert len(rows) == 1
    assert rows[0]["cache_hit"] is False
    assert rows[0]["input_tokens"] == mock.input_tokens

    # Cache file is the prompt hash.
    cache_files = list(client.cache_dir.glob("*.json"))  # type: ignore[union-attr]
    assert len(cache_files) == 1
    assert cache_files[0].stem == out.prompt_hash


def test_second_identical_call_is_cache_hit(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(completions=["one"])
    client.register_provider(mock)

    a = client.complete("same-prompt")
    b = client.complete("same-prompt")

    assert a.text == b.text == "one"
    assert a.cache_hit is False
    assert b.cache_hit is True
    # Mock saw exactly one underlying call.
    assert len(mock.calls) == 1

    # Cost log has TWO entries (one per call), second flagged cache_hit.
    rows = [
        json.loads(line) for line in client.cost_log.read_text().splitlines() if line.strip()  # type: ignore[union-attr]
    ]
    assert [r["cache_hit"] for r in rows] == [False, True]


def test_cache_hit_rate_measurable(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(completions=["a", "b", "c"])
    client.register_provider(mock)
    client.complete("p1")
    client.complete("p2")
    client.complete("p1")  # cache hit
    client.complete("p1")  # cache hit

    rows = [
        json.loads(line) for line in client.cost_log.read_text().splitlines() if line.strip()  # type: ignore[union-attr]
    ]
    hits = sum(1 for r in rows if r["cache_hit"])
    assert hits / len(rows) == 0.5


def test_different_params_dont_collide(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(completions=["t0-out", "t1-out"])
    client.register_provider(mock)
    a = client.complete("p", temperature=0.0)
    b = client.complete("p", temperature=0.7)
    assert a.text != b.text
    assert len(mock.calls) == 2


# ----- structured output -----


def test_complete_structured_validates_against_schema(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(
        structured=[{"label": "tool-registry", "confidence": 0.92}]
    )
    client.register_provider(mock)

    out = client.complete_structured("describe this motif", schema=MotifLabel)
    assert isinstance(out, StructuredCompletion)
    assert isinstance(out.parsed, MotifLabel)
    assert out.parsed.label == "tool-registry"
    assert out.parsed.confidence == 0.92


def test_complete_structured_invalid_payload_raises(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(
        structured=[{"label": "x", "confidence": 1.7}]  # out of bounds
    )
    client.register_provider(mock)
    with pytest.raises(StructuredOutputError):
        client.complete_structured("x", schema=MotifLabel)


def test_complete_structured_caches(client: LLMClient) -> None:
    mock = _MockAnthropicProvider(
        structured=[{"label": "x", "confidence": 0.5}, {"label": "y", "confidence": 0.1}]
    )
    client.register_provider(mock)
    a = client.complete_structured("p", schema=MotifLabel)
    b = client.complete_structured("p", schema=MotifLabel)
    assert a.parsed.label == "x"
    assert b.parsed.label == "x"  # served from cache
    assert b.cache_hit is True
    assert len(mock.calls) == 1


def test_structured_and_unstructured_paths_dont_share_cache(client: LLMClient) -> None:
    """A plain `complete()` and a `complete_structured()` with the same
    prompt should be different cache keys — the schema participates in
    the hash."""
    mock = _MockAnthropicProvider(
        completions=["plain"],
        structured=[{"label": "x", "confidence": 0.5}],
    )
    client.register_provider(mock)
    p = client.complete("p")
    s = client.complete_structured("p", schema=MotifLabel)
    assert p.prompt_hash != s.prompt_hash
    assert len(mock.calls) == 2


# ----- one-shot repair retry (MetaCoding-9h5.9) -----


def test_repair_retry_fires_once_and_carries_validation_error(client: LLMClient) -> None:
    """On a schema-validation failure with repair on, the client re-prompts
    exactly once, appends the validation error to the second prompt, and returns
    the corrected parse."""
    mock = _MockAnthropicProvider(
        structured=[
            {"label": "x", "confidence": 1.7},  # 1st: out of bounds → invalid
            {"label": "x", "confidence": 0.5},  # 2nd (repair): valid
        ]
    )
    client.register_provider(mock)

    out = client.complete_structured("distill this", schema=MotifLabel, repair=True)

    assert out.parsed.confidence == 0.5
    # Exactly two underlying provider calls — the original and one repair.
    assert len(mock.calls) == 2
    # The repair prompt is the original plus the appended validation error.
    repair_prompt = mock.calls[1]["prompt"]
    assert "distill this" in repair_prompt
    assert "failed schema validation" in repair_prompt
    assert "MotifLabel" in repair_prompt
    # The failed first attempt's spend is still logged (honest cost) plus the
    # successful repair → two structured cost rows, neither a cache hit.
    rows = [
        json.loads(line) for line in client.cost_log.read_text().splitlines() if line.strip()  # type: ignore[union-attr]
    ]
    assert len(rows) == 2
    assert all(r["structured"] and not r["cache_hit"] for r in rows)


def test_repair_off_by_default_raises_without_retry(client: LLMClient) -> None:
    """Without opting in, a single invalid payload raises and does NOT retry."""
    mock = _MockAnthropicProvider(
        structured=[{"label": "x", "confidence": 1.7}, {"label": "x", "confidence": 0.5}]
    )
    client.register_provider(mock)
    with pytest.raises(StructuredOutputError):
        client.complete_structured("x", schema=MotifLabel)
    assert len(mock.calls) == 1  # no repair attempt


def test_repair_retry_that_also_fails_raises_after_one_attempt(client: LLMClient) -> None:
    """If the repair attempt also fails validation, the client gives up after
    exactly one retry (two calls total) and raises."""
    mock = _MockAnthropicProvider(
        structured=[
            {"label": "x", "confidence": 1.7},  # invalid
            {"label": "x", "confidence": 2.9},  # repair also invalid
        ]
    )
    client.register_provider(mock)
    with pytest.raises(StructuredOutputError, match="even after one repair retry"):
        client.complete_structured("x", schema=MotifLabel, repair=True)
    assert len(mock.calls) == 2


def test_repair_dial_enables_retry_client_wide(tmp_path: Path) -> None:
    """The ``structured_repair`` client dial opts every structured call in,
    without a per-call flag."""
    client = LLMClient(
        cache_dir=tmp_path / "cache",
        cost_log=tmp_path / "cost.jsonl",
        default_model="claude-haiku-4-5-20251001",
        max_attempts=1,
        structured_repair=True,
    )
    mock = _MockAnthropicProvider(
        structured=[{"label": "x", "confidence": 1.7}, {"label": "x", "confidence": 0.5}]
    )
    client.register_provider(mock)
    out = client.complete_structured("p", schema=MotifLabel)
    assert out.parsed.confidence == 0.5
    assert len(mock.calls) == 2


# ----- fail-closed on missing key -----


def test_unset_key_raises_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure no real key leaks into this test.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = LLMClient(cache_dir=tmp_path / "cache", cost_log=tmp_path / "cost.jsonl")
    with pytest.raises(KeyMissingError) as exc:
        client.complete("hello")
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_unknown_provider_raises(client: LLMClient) -> None:
    from ctkr.llm import LLMError

    with pytest.raises(LLMError):
        client.complete("hello", provider="not-a-real-provider")


# ----- retry on transient errors -----


class RateLimitError(Exception):
    """Mimics anthropic.RateLimitError — the retry heuristic looks for
    'RateLimit' in the type name."""


def test_retry_eventually_succeeds(tmp_path: Path) -> None:
    """A transient failure should be retried; the second attempt succeeds."""

    class FlakyMock(_MockAnthropicProvider):
        def __init__(self) -> None:  # noqa: D401 — test scaffolding
            super().__init__(completions=["worked"])
            self.fail_count = 1

        def complete(self, *args: Any, **kwargs: Any) -> _ProviderResponse:  # type: ignore[override]
            if self.fail_count > 0:
                self.fail_count -= 1
                raise RateLimitError("too fast")
            return super().complete(*args, **kwargs)

    c = LLMClient(
        cache_dir=tmp_path / "cache",
        cost_log=tmp_path / "cost.jsonl",
        max_attempts=3,
        backoff_initial=0.001,
        backoff_factor=1.0,
    )
    flaky = FlakyMock()
    c.register_provider(flaky)  # type: ignore[arg-type]
    out = c.complete("p")
    assert out.text == "worked"


def test_retry_gives_up_on_non_transient(tmp_path: Path) -> None:
    class FatalMock(_MockAnthropicProvider):
        def complete(self, *args: Any, **kwargs: Any) -> _ProviderResponse:  # type: ignore[override]
            raise ValueError("schema violation in your prompt; not retryable")

    c = LLMClient(
        cache_dir=tmp_path / "cache",
        cost_log=tmp_path / "cost.jsonl",
        max_attempts=3,
        backoff_initial=0.001,
    )
    c.register_provider(FatalMock())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        c.complete("p")


# ----- live integration (skip when key missing) -----


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping live smoke test",
)
def test_live_anthropic_haiku_smoke(tmp_path: Path) -> None:
    """One cheap real call against Haiku — verifies env wiring."""
    client = LLMClient(
        cache_dir=tmp_path / "cache",
        cost_log=tmp_path / "cost.jsonl",
        default_model="claude-haiku-4-5-20251001",
        max_attempts=2,
    )
    out = client.complete(
        "Respond with exactly one word: 'pong'.",
        max_tokens=8,
        temperature=0.0,
    )
    assert out.provider == "anthropic"
    assert out.input_tokens > 0
    assert out.output_tokens > 0
    assert out.text.strip()


# ----- registry shape -----


def test_anthropic_provider_env_var_constant() -> None:
    """A regression check — registry lookup keys must match these."""
    assert AnthropicProvider.env_var == "ANTHROPIC_API_KEY"
    assert AnthropicProvider.name == "anthropic"
