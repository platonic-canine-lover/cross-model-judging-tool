"""OpenAI Chat Completions, via the official SDK (optional extra `openai`). Also the base for Azure OpenAI."""

from __future__ import annotations

from typing import Any

from jury.adapters.base import env, register
from jury.types import Message, Reply, Target, Usage


class OpenAITarget:
    def __init__(self, model: str, client: Any | None = None, provider: str = "openai", temperature: float | None = None) -> None:
        import openai

        self.id = f"{provider}:{model}"
        self.model = model
        self.temperature = temperature
        self._client = client or openai.AsyncOpenAI(api_key=env("OPENAI_API_KEY", provider="openai"))

    async def ask(self, messages: list[Message]) -> Reply:
        kwargs: dict[str, Any] = {"model": self.model, "messages": [{"role": m.role, "content": m.content} for m in messages]}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        u = resp.usage
        cached = None
        if u is not None and getattr(u, "prompt_tokens_details", None) is not None:
            cached = getattr(u.prompt_tokens_details, "cached_tokens", None)
        return Reply(
            text=choice.message.content or "",
            model=resp.model,
            usage=Usage(
                input_tokens=u.prompt_tokens if u else None, output_tokens=u.completion_tokens if u else None, cached_tokens=cached
            ),
            raw=resp.model_dump(mode="json"),
        )


@register("openai")
def _factory(model: str, temperature: float | None) -> Target:
    return OpenAITarget(model, temperature=temperature)


@register("azure")
def _azure_factory(deployment: str, temperature: float | None) -> Target:
    """Azure OpenAI: the models behind Copilot. AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION."""
    import openai

    client = openai.AsyncAzureOpenAI(
        azure_endpoint=env("AZURE_OPENAI_ENDPOINT", provider="azure"),
        api_key=env("AZURE_OPENAI_API_KEY", provider="azure"),
        api_version=env("AZURE_OPENAI_API_VERSION", provider="azure"),
    )
    return OpenAITarget(deployment, client=client, provider="azure", temperature=temperature)
