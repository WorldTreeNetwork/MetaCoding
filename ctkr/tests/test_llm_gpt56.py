"""GPT-5.6 agent-tier wiring (Sol/Terra/Luna): request-kwargs contract,
pricing, hash stability, and provider guards. Hermetic — no network."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from ctkr.llm import (
    LLMClient,
    LLMError,
    OpenAIProvider,
    _estimate_cost,
    _hash_prompt,
    _is_openai_reasoning_model,
    _ProviderResponse,
)

# ----- tier detection -----


@pytest.mark.parametrize(
    "model", ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5"]
)
def test_gpt5x_detected_as_reasoning(model: str) -> None:
    assert _is_openai_reasoning_model(model)


@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4o-mini", "claude-haiku-4-5-20251001"])
def test_legacy_models_not_reasoning(model: str) -> None:
    assert not _is_openai_reasoning_model(model)


# ----- request kwargs contract -----


def test_reasoning_kwargs_use_max_completion_tokens_and_omit_temperature() -> None:
    kw = OpenAIProvider._request_kwargs(
        model="gpt-5.6-sol", temperature=0.0, max_tokens=1024, reasoning_effort=None
    )
    assert kw == {"max_completion_tokens": 1024}
    assert "temperature" not in kw and "max_tokens" not in kw


def test_reasoning_effort_passed_through_on_gpt56() -> None:
    kw = OpenAIProvider._request_kwargs(
        model="gpt-5.6-terra", temperature=0.0, max_tokens=256, reasoning_effort="high"
    )
    assert kw["reasoning_effort"] == "high"
    assert kw["max_completion_tokens"] == 256


def test_legacy_kwargs_keep_temperature_and_max_tokens() -> None:
    kw = OpenAIProvider._request_kwargs(
        model="gpt-4o", temperature=0.0, max_tokens=512, reasoning_effort=None
    )
    assert kw == {"temperature": 0.0, "max_tokens": 512}


def test_reasoning_effort_on_legacy_model_raises() -> None:
    with pytest.raises(LLMError):
        OpenAIProvider._request_kwargs(
            model="gpt-4o", temperature=0.0, max_tokens=512, reasoning_effort="low"
        )


# ----- pricing -----


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.6-sol", (1_000_000 / 1_000_000) * 5.00 + (1_000_000 / 1_000_000) * 30.00),
        ("gpt-5.6-terra", 2.50 + 15.00),
        ("gpt-5.6-luna", 1.00 + 6.00),
    ],
)
def test_gpt56_tier_pricing(model: str, expected: float) -> None:
    assert _estimate_cost(model, 1_000_000, 1_000_000) == pytest.approx(expected)


# ----- hash stability -----


def test_hash_unchanged_when_reasoning_effort_unset() -> None:
    base = dict(
        provider="openai",
        model="gpt-5.6-luna",
        prompt="p",
        temperature=0.0,
        max_tokens=64,
        system=None,
        structured_schema=None,
    )
    legacy = _hash_prompt(**base)  # pre-gpt-5.6 call signature semantics
    explicit_none = _hash_prompt(**base, reasoning_effort=None)
    assert legacy == explicit_none  # existing cache entries stay valid


def test_hash_changes_when_reasoning_effort_set() -> None:
    base = dict(
        provider="openai",
        model="gpt-5.6-luna",
        prompt="p",
        temperature=0.0,
        max_tokens=64,
        system=None,
        structured_schema=None,
    )
    assert _hash_prompt(**base) != _hash_prompt(**base, reasoning_effort="high")
    assert _hash_prompt(**base, reasoning_effort="low") != _hash_prompt(
        **base, reasoning_effort="high"
    )


# ----- client plumbing + anthropic guard -----


class _RecordingProvider:
    """Mock OpenAI-shaped provider that records reasoning_effort."""

    name: ClassVar[str] = "openai"
    env_var: ClassVar[str] = "OPENAI_API_KEY"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        system: str | None,
        reasoning_effort: str | None = None,
    ) -> _ProviderResponse:
        self.calls.append({"model": model, "reasoning_effort": reasoning_effort})
        return _ProviderResponse(text="ok", input_tokens=3, output_tokens=2)

    def complete_structured(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


def test_client_threads_reasoning_effort_to_provider(tmp_path: Any) -> None:
    client = LLMClient(cache_dir=tmp_path / "cache", cost_log=tmp_path / "cost.jsonl")
    mock = _RecordingProvider()
    client.register_provider(mock)

    out = client.complete(
        "ping", provider="openai", model="gpt-5.6-sol", reasoning_effort="xhigh"
    )
    assert out.text == "ok"
    assert mock.calls == [{"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}]

    # Same call again is a cache hit — no new provider call.
    out2 = client.complete(
        "ping", provider="openai", model="gpt-5.6-sol", reasoning_effort="xhigh"
    )
    assert out2.cache_hit is True
    assert len(mock.calls) == 1


def test_anthropic_provider_rejects_reasoning_effort() -> None:
    from ctkr.llm import AnthropicProvider

    prov = AnthropicProvider.__new__(AnthropicProvider)  # skip SDK client init
    with pytest.raises(LLMError):
        prov.complete(
            "p",
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
            max_tokens=8,
            system=None,
            reasoning_effort="high",
        )
