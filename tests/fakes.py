"""Fake targets and judges for tests: deterministic, no network."""

from __future__ import annotations

from collections.abc import Callable

from jury.types import Message, Reply, Usage


class ScriptedTarget:
    """Answers from a mapping of the last user message → reply text."""

    def __init__(self, id: str, script: dict[str, str], default: str = "I'm not sure.") -> None:
        self.id = id
        self.script = script
        self.default = default
        self.calls: list[list[Message]] = []

    async def ask(self, messages: list[Message]) -> Reply:
        self.calls.append(messages)
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = self.script.get(last_user, self.default)
        return Reply(
            text=text,
            model=self.id,
            usage=Usage(input_tokens=len(" ".join(m.content for m in messages).split()), output_tokens=len(text.split())),
        )


class RuleJudge:
    """Grades by calling a Python predicate on the answer text, replying in the JSON the harness expects."""

    def __init__(self, id: str, rule: Callable[[str], bool], json_ok: bool = True, reported_model: str | None = None) -> None:
        self.id = id
        self.rule = rule
        self.json_ok = json_ok
        self.reported_model = reported_model or id
        self.calls = 0

    async def ask(self, messages: list[Message]) -> Reply:
        self.calls += 1
        prompt = messages[-1].content
        answer = prompt.split("<<<\n", 1)[1].split("\n>>>", 1)[0]
        if not self.json_ok:
            return Reply(text="I think it's fine, honestly.", model=self.reported_model)
        passed = self.rule(answer)
        return Reply(
            text=f'{{"pass": {str(passed).lower()}, "confidence": 0.9, "reasons": ["rule says {passed}"]}}', model=self.reported_model
        )
