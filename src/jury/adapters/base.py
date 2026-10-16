"""Adapter registry: "provider:model" → a Target.

    anthropic:claude-haiku-5-5
    openai:gpt-5-mini
    ollama:qwen3.8:27b                (everything after the first colon is the model tag)
    azure:<deployment-name>
    copilot-studio:<agent-schema-name>

Each adapter reads its own credentials from the environment and says so in
`requires_env`. Missing credentials fail at construction with a message that
names the variable, not at the first call.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from jury.types import Target

_FACTORIES: dict[str, Callable[[str, float | None], Target]] = {}


def register(provider: str) -> Callable[[Callable[[str, float | None], Target]], Callable[[str, float | None], Target]]:
    def deco(fn: Callable[[str, float | None], Target]) -> Callable[[str, float | None], Target]:
        _FACTORIES[provider] = fn
        return fn

    return deco


def providers() -> list[str]:
    return sorted(_FACTORIES)


def resolve(spec: str, temperature: float | None = None) -> Target:
    """Build the adapter for provider:model. temperature None means the provider's default."""
    provider, sep, model = spec.partition(":")
    if not sep or not model:
        raise ValueError(f'target "{spec}" must be provider:model, e.g. ollama:qwen3.8:27b; providers: {", ".join(providers())}')
    if provider not in _FACTORIES:
        raise ValueError(f'unknown provider "{provider}"; known: {", ".join(providers())}')
    return _FACTORIES[provider](model, temperature)


def env(name: str, *, provider: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{provider}: set {name} in the environment (see .env.example)")
    return value
