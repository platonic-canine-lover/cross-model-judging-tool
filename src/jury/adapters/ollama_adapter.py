"""Ollama's local chat API (http://localhost:11434 by default, or OLLAMA_HOST). No SDK needed."""

from __future__ import annotations

import os

import httpx

from jury.adapters.base import register
from jury.types import Message, Reply, Target, Usage


class OllamaTarget:
    def __init__(self, model: str, host: str | None = None, timeout: float = 600.0) -> None:
        self.id = f"ollama:{model}"
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    async def ask(self, messages: list[Message]) -> Reply:
        payload = {"model": self.model, "messages": [m.model_dump() for m in messages], "stream": False}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        return Reply(
            text=data.get("message", {}).get("content", ""),
            model=data.get("model", self.model),
            usage=Usage(input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count")),
            raw=data,
        )


@register("ollama")
def _factory(model: str) -> Target:
    return OllamaTarget(model)
