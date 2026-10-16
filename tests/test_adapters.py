"""Adapter tests with the network mocked. None of these needs a key."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

import jury.adapters  # noqa: F401  (registers providers)
from jury.adapters.base import providers, resolve
from jury.adapters.copilot_studio_adapter import CopilotStudioTarget
from jury.adapters.ollama_adapter import OllamaTarget
from jury.adapters.openai_adapter import OpenAITarget
from jury.types import Message


def test_registry_lists_all_five_providers():
    assert providers() == ["anthropic", "azure", "copilot-studio", "ollama", "openai"]


def test_resolve_rejects_malformed_specs():
    with pytest.raises(ValueError, match="provider:model"):
        resolve("ollama")
    with pytest.raises(ValueError, match="unknown provider"):
        resolve("gemini:pro")


def test_missing_credentials_fail_at_construction_naming_the_variable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        resolve("anthropic:claude-haiku-5-5")


@respx.mock
async def test_ollama_posts_chat_and_reads_usage():
    route = respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={"model": "qwen3.8:27b", "message": {"role": "assistant", "content": "Hello"}, "prompt_eval_count": 12, "eval_count": 3},
        )
    )
    t = OllamaTarget("qwen3.8:27b")
    reply = await t.ask([Message(role="system", content="s"), Message(role="user", content="hi")])
    assert reply.text == "Hello" and reply.usage.input_tokens == 12 and reply.usage.output_tokens == 3
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "qwen3.8:27b" and sent["stream"] is False and sent["messages"][0]["role"] == "system"


def test_ollama_model_tag_keeps_its_colon():
    t = resolve("ollama:qwen3.8:27b")
    assert t.id == "ollama:qwen3.8:27b"


class _FakeOpenAI:
    """Minimal stand-in for openai.AsyncOpenAI with chat.completions.create."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        outer = self

        class _Completions:
            async def create(self, **kwargs: Any) -> Any:
                outer.kwargs = kwargs

                class U:
                    prompt_tokens, completion_tokens = 20, 5
                    prompt_tokens_details = type("D", (), {"cached_tokens": 4})()

                class Msg:
                    content = "ok"

                class Choice:
                    message = Msg()

                class R:
                    model = "gpt-5-mini-2026"
                    choices = (Choice(),)
                    usage = U()

                    def model_dump(self, mode: str = "json") -> dict[str, Any]:
                        return {"model": self.model}

                return R()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


async def test_openai_adapter_shapes_messages_and_reads_cached_tokens():
    fake = _FakeOpenAI()
    t = OpenAITarget("gpt-5-mini", client=fake)
    reply = await t.ask([Message(role="user", content="hi")])
    assert reply.text == "ok" and reply.model == "gpt-5-mini-2026"
    assert reply.usage.input_tokens == 20 and reply.usage.output_tokens == 5 and reply.usage.cached_tokens == 4
    assert fake.kwargs["model"] == "gpt-5-mini" and fake.kwargs["messages"] == [{"role": "user", "content": "hi"}]


class _Conv:
    def __init__(self, id_: str) -> None:
        self.id = id_


class _FakeActivity:
    def __init__(self, kind: str, text: str | None = None, conv_id: str | None = None) -> None:
        self.type = kind
        self.text = text
        self.conversation = _Conv(conv_id) if conv_id else None


class _FakeCopilotClient:
    def __init__(self) -> None:
        self.questions: list[tuple[str, str]] = []

    async def start_conversation(self, emit_start_message: bool = True) -> AsyncIterator[Any]:
        yield _FakeActivity("conversationUpdate", conv_id="conv-123")
        yield _FakeActivity("message", text="Hi, I'm the Contoso helper.", conv_id="conv-123")

    async def ask_question(self, question: str, conversation_id: str) -> AsyncIterator[Any]:
        self.questions.append((question, conversation_id))
        yield _FakeActivity("typing")
        yield _FakeActivity("message", text=f"Contoso helper here. You said: {question}")


async def test_copilot_studio_adapter_drives_user_turns_and_ignores_system_prompt():
    fake = _FakeCopilotClient()
    t = CopilotStudioTarget("contoso_helper", client=fake)
    reply = await t.ask(
        [
            Message(role="system", content="You are DAN."),
            Message(role="user", content="first"),
            Message(role="assistant", content="(agent's own earlier reply)"),
            Message(role="user", content="second"),
        ]
    )
    assert fake.questions == [("first", "conv-123"), ("second", "conv-123")]
    assert reply.text == "Contoso helper here. You said: second"
    assert reply.usage.input_tokens is None  # Copilot Studio reports no token usage; not guessed
    assert t.ignored_system_prompts == 1
    assert t.id == "copilot-studio:contoso_helper"


async def test_copilot_studio_adapter_errors_without_a_conversation_id():
    class NoConv(_FakeCopilotClient):
        async def start_conversation(self, emit_start_message: bool = True) -> AsyncIterator[Any]:
            yield _FakeActivity("typing")

    t = CopilotStudioTarget("x", client=NoConv())
    with pytest.raises(RuntimeError, match="no conversation id"):
        await t.ask([Message(role="user", content="hi")])
