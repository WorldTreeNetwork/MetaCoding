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
* On-disk cache so re-runs are free (``.metacoding/ctkr/llm_cache/``).
* Cost telemetry to JSONL (``.metacoding/ctkr/llm_cost.jsonl``).
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

import blake3
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("ctkr.llm")


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
    "gpt-5": (10.00, 30.00),  # placeholder; replace when officially priced
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


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
    ) -> _ProviderResponse:
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
    ) -> tuple[_ProviderResponse, dict[str, Any]]:
        tool_name = "emit_" + schema.__name__.lower()
        json_schema = schema.model_json_schema()
        # Anthropic requires the top-level schema to be type=object.
        if json_schema.get("type") != "object":
            raise StructuredOutputError(
                f"{schema.__name__} must serialize to a JSON object schema; got {json_schema.get('type')}"
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

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        system: str | None,
    ) -> _ProviderResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
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
            temperature=temperature,
            max_tokens=max_tokens,
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
    max_attempts: int = 3
    backoff_initial: float = 1.0
    backoff_factor: float = 2.0
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
    ) -> Completion:
        prov_name = provider or self.default_provider
        m = model or self.default_model
        t = self.default_temperature if temperature is None else temperature
        mt = max_tokens or self.default_max_tokens

        prompt_hash = _hash_prompt(
            provider=prov_name,
            model=m,
            prompt=prompt,
            temperature=t,
            max_tokens=mt,
            system=system,
            structured_schema=None,
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
        resp = _retry(
            lambda: prov.complete(
                prompt, model=m, temperature=t, max_tokens=mt, system=system
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
    ) -> StructuredCompletion[T]:
        prov_name = provider or self.default_provider
        m = model or self.default_model
        t = self.default_temperature if temperature is None else temperature
        mt = max_tokens or self.default_max_tokens

        prompt_hash = _hash_prompt(
            provider=prov_name,
            model=m,
            prompt=prompt,
            temperature=t,
            max_tokens=mt,
            system=system,
            structured_schema=schema.model_json_schema(),
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
        resp, raw = _retry(
            lambda: prov.complete_structured(
                prompt,
                model=m,
                schema=schema,
                temperature=t,
                max_tokens=mt,
                system=system,
            ),
            attempts=self.max_attempts,
            initial=self.backoff_initial,
            factor=self.backoff_factor,
        )
        try:
            parsed = schema.model_validate(raw)
        except Exception as e:
            raise StructuredOutputError(
                f"Provider returned JSON that didn't validate against {schema.__name__}: {e}"
            ) from e
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
) -> str:
    canon = json.dumps(
        {
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system": system,
            "schema": structured_schema,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return blake3.blake3(canon).hexdigest(length=16)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


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
