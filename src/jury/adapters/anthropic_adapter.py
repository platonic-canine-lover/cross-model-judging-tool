"""Anthropic Messages API, via the official SDK (optional extra `anthropic`)."""

from __future__ import annotations

from typing import Any, cast

from jury.adapters.base import env, register
from jury.types import Message, Reply, Target, Usage


class AnthropicTarget:
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float | None = None) -> None:
        import anthropic  # local import so the package is optional

        self.id = f"anthropic:{model}"
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = anthropic.AsyncAnthropic(api_key=env("ANTHROPIC_API_KEY", provider="anthropic"))

    async def ask(self, messages: list[Message]) -> Reply:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        kwargs: dict[str, object] = {"model": self.model, "max_tokens": self.max_tokens, "messages": turns}
        if system:
            kwargs["system"] = system
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = await self._client.messages.create(**cast(Any, kwargs))
        text = "".join(getattr(block, "text", "") for block in resp.content)
        u = resp.usage
        return Reply(
            text=text,
            model=resp.model,
            usage=Usage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cached_tokens=getattr(u, "cache_read_input_tokens", None),
            ),
            raw=resp.model_dump(mode="json"),
        )


@register("anthropic")
def _factory(model: str, temperature: float | None) -> Target:
    return AnthropicTarget(model, temperature=temperature)
