"""OpenAI Chat Completions, via the official SDK (optional extra `openai`). Also the base for Azure OpenAI."""

from __future__ import annotations

from typing import Any, cast

from jury.adapters.base import env, register
from jury.types import Message, Reply, Target, Usage


class OpenAITarget:
    def __init__(self, model: str, client: Any | None = None, provider: str = "openai") -> None:
        import openai

        self.id = f"{provider}:{model}"
        self.model = model
        self._client = client or openai.AsyncOpenAI(api_key=env("OPENAI_API_KEY", provider="openai"))

    async def ask(self, messages: list[Message]) -> Reply:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=cast(Any, [{"role": m.role, "content": m.content} for m in messages]),
        )
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
def _factory(model: str) -> Target:
    return OpenAITarget(model)


@register("azure")
def _azure_factory(deployment: str) -> Target:
    """Azure OpenAI: the models behind Copilot. AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION."""
    import openai

    client = openai.AsyncAzureOpenAI(
        azure_endpoint=env("AZURE_OPENAI_ENDPOINT", provider="azure"),
        api_key=env("AZURE_OPENAI_API_KEY", provider="azure"),
        api_version=env("AZURE_OPENAI_API_VERSION", provider="azure"),
    )
    return OpenAITarget(deployment, client=client, provider="azure")
