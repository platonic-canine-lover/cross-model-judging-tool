"""Core types.

A Target is anything that answers a conversation: an API model, a local
model, or an agent built in Copilot Studio. A Judge is a model asked to grade
an answer against a case's rubric. Both are addressed by one string,
"provider:model", resolved by the adapter registry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: Role
    content: str


class Usage(BaseModel):
    """Token counts as the provider reported them; None when it reported nothing (Copilot Studio, for example)."""

    model_config = ConfigDict(frozen=True)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None


class Reply(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str
    usage: Usage = Field(default_factory=Usage)
    model: str = Field(description="what the provider says it ran, which may differ from what was asked for")
    raw: dict[str, object] | None = Field(default=None, description="provider response, kept in recordings")


class Target(Protocol):
    """Something that answers."""

    id: str

    async def ask(self, messages: list[Message]) -> Reply: ...


class Case(BaseModel):
    """One test: a conversation to send, and what a correct answer must and must not do."""

    model_config = ConfigDict(frozen=True)
    id: str
    category: str
    title: str
    system: str | None = Field(default=None, description="system prompt the target runs with; None = the target's own default")
    messages: list[Message]
    rubric: str = Field(description="plain-English statement of what passes, written for a judge")
    must: list[str] = Field(default_factory=list, description="things the answer must do")
    must_not: list[str] = Field(default_factory=list, description="things the answer must not do")
    notes: str | None = None


class Verdict(BaseModel):
    """A judge's structured opinion of one answer."""

    model_config = ConfigDict(frozen=True)
    judge: str
    passed: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    raw_text: str = Field(description="the judge's full reply, for audit")
    parse_ok: bool = True


class CaseResult(BaseModel):
    case_id: str
    target: str
    answer: Reply
    self_verdict: Verdict | None
    panel_verdicts: list[Verdict]
    panel_passed: bool | None = Field(description="majority of panel verdicts; None if the panel is empty")
    panel_split: str = Field(default="", description="e.g. '2-1' pass-fail")


class Run(BaseModel):
    """Everything from one run, enough to replay the judging without any network."""

    run_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    target: str
    judges: list[str]
    self_judge: bool
    cases_dir: str
    results: list[CaseResult] = Field(default_factory=list)
    live: dict[str, bool] = Field(default_factory=dict, description="adapter id → whether it was called live (False = replayed)")
