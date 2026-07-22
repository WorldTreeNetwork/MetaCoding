"""Provider-agnostic LLM client for L3 labelers.

Surface
-------

::

    client = LLMClient(cache_dir=..., cost_log=...)
    out = client.complete("Hello", model="claude-haiku-4-5-20251001")
    parsed = client.complete_structured("...", model=..., schema=MotifLabel)

Two providers are wired today: Anthropic (primary) and OpenAI (alt for
multi-model consensus, Orchestrators-gss). Adding a third (Gemini,
local llama.cpp, etc.) means writing one more :class:`Provider`
implementation — the cache, cost log, retry logic, and structured-output
path are all provider-agnostic.

Design constraints
------------------

* No agent-framework dependency (no langchain, no DSPy, no LiteLLM).
* On-disk cache so re-runs are free (``~/.cache/ctkr/<command>/llm_cache/`` —
  SCRATCH, never a sandbox data-dir; see :func:`scratch_dir`).
* Cost telemetry to JSONL (``~/.cache/ctkr/<command>/llm_cost.jsonl``).
* Deterministic mode is the default (``temperature=0``, fixed seed where
  supported).
* Fails *closed* on missing API keys — raise a clear ``KeyMissingError``
  rather than silently returning empty completions.

The structured-output path uses pydantic models as the schema. Anthropic
gets ``tool_use`` with the model's ``input_schema``; OpenAI gets
``response_format={'type': 'json_schema', ...}``. Both routes validate
the parsed payload through ``schema.model_validate`` before returning.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeVar

import blake3
from pydantic import BaseModel

logger = logging.getLogger("ctkr.llm")


# ----- scratch discipline (MetaCoding-7xr, lever 4) -----
#
# Wave-1 prep wrote llm_cache/ + llm_cost.jsonl INTO the shared graph data-dir
# the commands were reading — a sandbox declared read-only, mutated by its own
# reader. LLM cache/cost artifacts are operational scratch, not evidence, and
# they live under the user cache root, per command.

#: Root for all ctkr LLM scratch artifacts. Never inside a data-dir.
SCRATCH_ROOT = Path.home() / ".cache" / "ctkr"


def scratch_dir(command: str) -> Path:
    """The per-command scratch directory for LLM cache/cost artifacts."""
    return SCRATCH_ROOT / command


def sandbox_write_guard(data_dir: str | Path | None, *paths: str | Path) -> None:
    """Refuse any LLM cache/cost path inside the data-dir a command reads.

    A sandbox a command reads is READ-ONLY; writing operational artifacts into
    it mutates the evidence environment (and pollutes exports, digests, and
    disk-level comparisons). Raises ``ValueError`` — loudly, at argument
    resolution, before any provider is touched.
    """
    if data_dir is None:
        return
    root = Path(data_dir).expanduser().resolve()
    for p in paths:
        rp = Path(p).expanduser().resolve()
        if rp == root or root in rp.parents:
            raise ValueError(
                f"{p} is inside the data-dir {data_dir} — a sandbox a command "
                f"reads is READ-ONLY. LLM cache/cost artifacts belong in "
                f"scratch ({SCRATCH_ROOT}/<command>). (MetaCoding-7xr lever 4)"
            )


# ----- public errors -----


class LLMError(Exception):
    """Base class for ctkr LLM errors."""


class KeyMissingError(LLMError):
    """Raised on call when the provider's API key env var is unset.

    Fails closed: this is preferred over silently returning empty
    completions because L3 labelers run thousands of calls and a
    silent no-op would corrupt the patterns.jsonl downstream.
    """


class StructuredOutputError(LLMError):
    """Raised when the provider returns text that doesn't parse as JSON
    or fails pydantic validation against the requested schema."""


# ----- public dataclasses -----


@dataclass(slots=True, frozen=True)
class Completion:
    """Result of a plain ``complete()`` call."""

    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_estimate_usd: float
    cache_hit: bool
    prompt_hash: str


T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True, frozen=True)
class StructuredCompletion[T: BaseModel]:
    """Result of a ``complete_structured()`` call. ``parsed`` is a
    validated instance of the requested pydantic schema."""

    parsed: T
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_estimate_usd: float
    cache_hit: bool
    prompt_hash: str


# ----- pricing -----
# (USD per 1M tokens) — input, output. Update as official prices change.
# When a model isn't listed we log a warning and set cost to 0.0; the
# token counts are the ground truth.

_PRICES_PER_M: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    # GPT-5.6 agent tiers (2026-07 list prices).
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5": (10.00, 30.00),  # placeholder; replace when officially priced
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def _is_openai_reasoning_model(model: str) -> bool:
    """GPT-5.x-family reasoning models have a different Chat Completions
    contract: ``max_completion_tokens`` instead of ``max_tokens``, no
    ``temperature`` (the API rejects it), and an optional
    ``reasoning_effort``. Determinism for these tiers therefore rests on
    the prompt-hash cache, not on a pinned temperature."""
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


def _estimate_cost(model: str, in_toks: int, out_toks: int) -> float:
    prices = _PRICES_PER_M.get(model)
    if prices is None:
        logger.warning("no price entry for model %s; cost_estimate_usd=0", model)
        return 0.0
    in_p, out_p = prices
    return round((in_toks / 1_000_000) * in_p + (out_toks / 1_000_000) * out_p, 6)


# ----- provider protocol -----


@dataclass(slots=True, frozen=True)
class _ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    """The thin contract every provider implements."""

    name: ClassVar[str]
    env_var: ClassVar[str]

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        system: str | None,
    ) -> _ProviderResponse: ...

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
        """Return (raw text response, parsed JSON dict)."""


# ----- Anthropic provider -----


class AnthropicProvider:
    name: ClassVar[str] = "anthropic"
    env_var: ClassVar[str] = "ANTHROPIC_API_KEY"

    def __init__(self, api_key: str | None = None) -> None:
        # Lazy import keeps tests that mock the provider free of SDK weight.
        import anthropic  # type: ignore[import-untyped]

        self._client = anthropic.Anthropic(api_key=api_key or os.environ[self.env_var])

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
        if reasoning_effort is not None:
            raise LLMError(
                "reasoning_effort is an OpenAI GPT-5.x parameter; "
                "not supported by the anthropic provider"
            )
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = self._client.messages.create(**kwargs)
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return _ProviderResponse(
            text="".join(text_parts),
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
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
        reasoning_effort: str | None = None,
    ) -> tuple[_ProviderResponse, dict[str, Any]]:
        if reasoning_effort is not None:
            raise LLMError(
                "reasoning_effort is an OpenAI GPT-5.x parameter; "
                "not supported by the anthropic provider"
            )
        tool_name = "emit_" + schema.__name__.lower()
        json_schema = schema.model_json_schema()
        # Anthropic requires the top-level schema to be type=object.
        if json_schema.get("type") != "object":
            raise StructuredOutputError(
                f"{schema.__name__} must serialize to a JSON object schema; "
                f"got {json_schema.get('type')}"
            )
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": tool_name,
                    "description": (
                        schema.__doc__
                        or f"Emit a {schema.__name__} object conforming to the provided schema."
                    ),
                    "input_schema": json_schema,
                },
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        if system:
            kwargs["system"] = system
        resp = self._client.messages.create(**kwargs)

        parsed: dict[str, Any] | None = None
        text_parts: list[str] = []
        for b in resp.content:
            t = getattr(b, "type", None)
            if t == "tool_use" and b.name == tool_name:
                parsed = b.input  # type: ignore[attr-defined]
            elif t == "text":
                text_parts.append(b.text)
        if parsed is None:
            raise StructuredOutputError(
                f"Anthropic did not return a tool_use block named {tool_name}"
            )
        return (
            _ProviderResponse(
                text=json.dumps(parsed),
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
            parsed,
        )


# ----- OpenAI provider -----


class OpenAIProvider:
    name: ClassVar[str] = "openai"
    env_var: ClassVar[str] = "OPENAI_API_KEY"

    def __init__(self, api_key: str | None = None) -> None:
        import openai  # type: ignore[import-untyped]

        self._client = openai.OpenAI(api_key=api_key or os.environ[self.env_var])

    @staticmethod
    def _request_kwargs(
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        """GPT-5.x reasoning tiers (Sol/Terra/Luna) reject ``temperature``
        and ``max_tokens``; they take ``max_completion_tokens`` and an
        optional ``reasoning_effort``. Legacy models keep the old contract."""
        if _is_openai_reasoning_model(model):
            kwargs: dict[str, Any] = {"max_completion_tokens": max_tokens}
            if reasoning_effort is not None:
                kwargs["reasoning_effort"] = reasoning_effort
            return kwargs
        if reasoning_effort is not None:
            raise LLMError(
                f"reasoning_effort is only supported on GPT-5.x reasoning models, not {model!r}"
            )
        return {"temperature": temperature, "max_tokens": max_tokens}

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
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **self._request_kwargs(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            ),
        )
        usage = resp.usage
        return _ProviderResponse(
            text=resp.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
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
        reasoning_effort: str | None = None,
    ) -> tuple[_ProviderResponse, dict[str, Any]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        json_schema = schema.model_json_schema()
        # OpenAI requires a name on the schema envelope.
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **self._request_kwargs(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            ),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": False,
                },
            },
        )
        usage = resp.usage
        text = resp.choices[0].message.content or ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise StructuredOutputError(f"OpenAI returned non-JSON: {text[:200]}") from e
        return (
            _ProviderResponse(
                text=text,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            parsed,
        )


# ----- client -----


@dataclass(slots=True)
class _CostRow:
    ts: str
    provider: str
    model: str
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    cost_estimate_usd: float
    cache_hit: bool
    structured: bool


_PROVIDER_REGISTRY: dict[str, type[Provider]] = {
    AnthropicProvider.name: AnthropicProvider,  # type: ignore[type-abstract]
    OpenAIProvider.name: OpenAIProvider,  # type: ignore[type-abstract]
}


@dataclass(slots=True)
class LLMClient:
    """Cached, costed, retried LLM access.

    Pass an explicit ``provider`` instance to bypass auto-construction
    (tests inject mocks this way). Otherwise, the first call to a given
    provider name lazily constructs that provider — and raises
    :class:`KeyMissingError` if its env var is unset.
    """

    cache_dir: Path | None = None
    cost_log: Path | None = None
    default_provider: str = "anthropic"
    default_model: str = "claude-haiku-4-5-20251001"
    default_temperature: float = 0.0
    default_max_tokens: int = 1024
    # GPT-5.x reasoning tiers bill *reasoning* tokens against
    # ``max_completion_tokens``. A stage cap sized for Claude output (900–2000)
    # can be fully consumed by reasoning, truncating the structured payload to
    # empty. For reasoning models only, floor the completion budget so the
    # visible output has room; the cap is not billed unless the model uses it,
    # so this is cost-safe and leaves the Anthropic path untouched. Set to
    # ``None`` to disable the floor.
    reasoning_max_tokens: int | None = 16000
    max_attempts: int = 3
    backoff_initial: float = 1.0
    backoff_factor: float = 2.0
    # One-shot repair retry: when a provider returns JSON that parses but fails
    # schema validation, re-prompt ONCE with the validation error appended, then
    # fail as before if the retry also fails. Off by default (zero behavior change
    # for callers that don't opt in); nested-schema stages (e.g. ScenarioDistillOut
    # in T5b) set the dial or pass ``repair=True`` per call. Generic — not tied to
    # any one schema — because reasoning models trip nested-required-field
    # validation on other schemas too.
    structured_repair: bool = False
    _providers: dict[str, Provider] = field(default_factory=dict)
    _injected: dict[str, Provider] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.cost_log is not None:
            self.cost_log = Path(self.cost_log)
            self.cost_log.parent.mkdir(parents=True, exist_ok=True)

    def register_provider(self, provider: Provider) -> None:
        """Inject a provider instance — bypasses lazy construction.

        Used by tests to swap in mocks, and by callers that want to
        configure non-env-var API keys.
        """
        self._injected[provider.name] = provider

    # ----- public entry points -----

    def complete(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system: str | None = None,
        reasoning_effort: str | None = None,
    ) -> Completion:
        prov_name = provider or self.default_provider
        m = model or self.default_model
        t = self.default_temperature if temperature is None else temperature
        mt = max_tokens or self.default_max_tokens
        if self.reasoning_max_tokens and _is_openai_reasoning_model(m):
            mt = max(mt, self.reasoning_max_tokens)

        prompt_hash = _hash_prompt(
            provider=prov_name,
            model=m,
            prompt=prompt,
            temperature=t,
            max_tokens=mt,
            system=system,
            structured_schema=None,
            reasoning_effort=reasoning_effort,
        )

        cached = self._cache_load(prompt_hash)
        if cached is not None:
            self._cost_append(
                _CostRow(
                    ts=_now(),
                    provider=prov_name,
                    model=m,
                    prompt_hash=prompt_hash,
                    input_tokens=cached["input_tokens"],
                    output_tokens=cached["output_tokens"],
                    cost_estimate_usd=cached["cost_estimate_usd"],
                    cache_hit=True,
                    structured=False,
                )
            )
            return Completion(
                text=cached["text"],
                provider=prov_name,
                model=m,
                input_tokens=cached["input_tokens"],
                output_tokens=cached["output_tokens"],
                cost_estimate_usd=cached["cost_estimate_usd"],
                cache_hit=True,
                prompt_hash=prompt_hash,
            )

        prov = self._provider(prov_name)
        effort_kw: dict[str, Any] = (
            {} if reasoning_effort is None else {"reasoning_effort": reasoning_effort}
        )
        resp = _retry(
            lambda: prov.complete(
                prompt, model=m, temperature=t, max_tokens=mt, system=system, **effort_kw
            ),
            attempts=self.max_attempts,
            initial=self.backoff_initial,
            factor=self.backoff_factor,
        )
        cost = _estimate_cost(m, resp.input_tokens, resp.output_tokens)
        payload = {
            "text": resp.text,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "cost_estimate_usd": cost,
        }
        self._cache_store(prompt_hash, payload)
        self._cost_append(
            _CostRow(
                ts=_now(),
                provider=prov_name,
                model=m,
                prompt_hash=prompt_hash,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_estimate_usd=cost,
                cache_hit=False,
                structured=False,
            )
        )
        return Completion(
            text=resp.text,
            provider=prov_name,
            model=m,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_estimate_usd=cost,
            cache_hit=False,
            prompt_hash=prompt_hash,
        )

    def complete_structured(
        self,
        prompt: str,
        *,
        schema: type[T],
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system: str | None = None,
        reasoning_effort: str | None = None,
        repair: bool | None = None,
    ) -> StructuredCompletion[T]:
        prov_name = provider or self.default_provider
        m = model or self.default_model
        t = self.default_temperature if temperature is None else temperature
        mt = max_tokens or self.default_max_tokens
        if self.reasoning_max_tokens and _is_openai_reasoning_model(m):
            mt = max(mt, self.reasoning_max_tokens)

        prompt_hash = _hash_prompt(
            provider=prov_name,
            model=m,
            prompt=prompt,
            temperature=t,
            max_tokens=mt,
            system=system,
            structured_schema=schema.model_json_schema(),
            reasoning_effort=reasoning_effort,
        )

        cached = self._cache_load(prompt_hash)
        if cached is not None:
            parsed = schema.model_validate(json.loads(cached["text"]))
            self._cost_append(
                _CostRow(
                    ts=_now(),
                    provider=prov_name,
                    model=m,
                    prompt_hash=prompt_hash,
                    input_tokens=cached["input_tokens"],
                    output_tokens=cached["output_tokens"],
                    cost_estimate_usd=cached["cost_estimate_usd"],
                    cache_hit=True,
                    structured=True,
                )
            )
            return StructuredCompletion(
                parsed=parsed,
                text=cached["text"],
                provider=prov_name,
                model=m,
                input_tokens=cached["input_tokens"],
                output_tokens=cached["output_tokens"],
                cost_estimate_usd=cached["cost_estimate_usd"],
                cache_hit=True,
                prompt_hash=prompt_hash,
            )

        prov = self._provider(prov_name)
        effort_kw: dict[str, Any] = (
            {} if reasoning_effort is None else {"reasoning_effort": reasoning_effort}
        )

        def _provider_call(p: str) -> tuple[Any, dict[str, Any]]:
            return _retry(
                lambda: prov.complete_structured(
                    p,
                    model=m,
                    schema=schema,
                    temperature=t,
                    max_tokens=mt,
                    system=system,
                    **effort_kw,
                ),
                attempts=self.max_attempts,
                initial=self.backoff_initial,
                factor=self.backoff_factor,
            )

        do_repair = self.structured_repair if repair is None else repair
        resp, raw = _provider_call(prompt)
        try:
            parsed = schema.model_validate(raw)
        except Exception as e:
            if not do_repair:
                raise StructuredOutputError(
                    f"Provider returned JSON that didn't validate against {schema.__name__}: {e}"
                ) from e
            # Log the failed attempt's spend (the tokens were really billed), then
            # re-prompt exactly once with the validation error appended so the model
            # can self-correct the offending field.
            self._cost_append(
                _CostRow(
                    ts=_now(),
                    provider=prov_name,
                    model=m,
                    prompt_hash=prompt_hash,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    cost_estimate_usd=_estimate_cost(
                        m, resp.input_tokens, resp.output_tokens
                    ),
                    cache_hit=False,
                    structured=True,
                )
            )
            logger.warning(
                "structured %s failed validation; issuing one repair retry: %s",
                schema.__name__,
                e,
            )
            repair_prompt = (
                f"{prompt}\n\nYour previous output failed schema validation: {e}\n"
                "Re-emit a single JSON object that conforms exactly to the schema; "
                "fix the reported field(s) and include every required field. "
                "Do not add commentary."
            )
            resp, raw = _provider_call(repair_prompt)
            try:
                parsed = schema.model_validate(raw)
            except Exception as e2:
                raise StructuredOutputError(
                    f"Provider returned JSON that didn't validate against "
                    f"{schema.__name__} even after one repair retry: {e2}"
                ) from e2
        cost = _estimate_cost(m, resp.input_tokens, resp.output_tokens)
        text = json.dumps(raw)
        payload = {
            "text": text,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "cost_estimate_usd": cost,
        }
        self._cache_store(prompt_hash, payload)
        self._cost_append(
            _CostRow(
                ts=_now(),
                provider=prov_name,
                model=m,
                prompt_hash=prompt_hash,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_estimate_usd=cost,
                cache_hit=False,
                structured=True,
            )
        )
        return StructuredCompletion(
            parsed=parsed,
            text=text,
            provider=prov_name,
            model=m,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_estimate_usd=cost,
            cache_hit=False,
            prompt_hash=prompt_hash,
        )

    # ----- internals -----

    def _provider(self, name: str) -> Provider:
        if name in self._injected:
            return self._injected[name]
        if name in self._providers:
            return self._providers[name]
        cls = _PROVIDER_REGISTRY.get(name)
        if cls is None:
            raise LLMError(f"unknown provider: {name!r}")
        env_var = cls.env_var  # type: ignore[attr-defined]
        if not os.environ.get(env_var):
            raise KeyMissingError(
                f"{env_var} is not set; refusing to call provider {name!r}"
            )
        p = cls()  # type: ignore[call-arg]
        self._providers[name] = p
        return p

    def _cache_load(self, key: str) -> dict[str, Any] | None:
        if self.cache_dir is None:
            return None
        p = self.cache_dir / f"{key}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            logger.warning("corrupt cache entry at %s; ignoring", p)
            return None

    def _cache_store(self, key: str, payload: dict[str, Any]) -> None:
        if self.cache_dir is None:
            return
        p = self.cache_dir / f"{key}.json"
        p.write_text(json.dumps(payload))

    def _cost_append(self, row: _CostRow) -> None:
        if self.cost_log is None:
            return
        with self.cost_log.open("a") as f:
            f.write(json.dumps(asdict(row)) + "\n")


# ----- module utilities -----


def _hash_prompt(
    *,
    provider: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    system: str | None,
    structured_schema: dict[str, Any] | None,
    reasoning_effort: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "system": system,
        "schema": structured_schema,
    }
    # Only included when set, so pre-existing cache entries keep their hashes.
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return blake3.blake3(canon).hexdigest(length=16)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _retry(
    fn: Any,
    *,
    attempts: int,
    initial: float,
    factor: float,
) -> Any:
    last_exc: Exception | None = None
    delay = initial
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — provider exceptions vary
            if not _is_transient(e) or i == attempts - 1:
                raise
            last_exc = e
            logger.warning("transient error %s; retrying in %.1fs", type(e).__name__, delay)
            time.sleep(delay)
            delay *= factor
    raise last_exc  # pragma: no cover — unreachable but keeps mypy happy


def _is_transient(exc: Exception) -> bool:
    """Heuristic — anthropic/openai SDKs raise typed errors but we
    don't want to depend on those specific classes in the retry path."""
    name = type(exc).__name__
    if "RateLimit" in name or "APIConnection" in name or "Timeout" in name:
        return True
    if "InternalServer" in name or "Overloaded" in name:
        return True
    status = getattr(exc, "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    return False


__all__ = [
    "Completion",
    "KeyMissingError",
    "LLMClient",
    "LLMError",
    "Provider",
    "StructuredCompletion",
    "StructuredOutputError",
    "AnthropicProvider",
    "OpenAIProvider",
]
