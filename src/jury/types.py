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
    """A judge's structured opinion of one answer.

    `passed` is None when the judge did not return a usable verdict. That is a
    fact about the judge's output format, not about the target's behaviour,
    and it is kept separate: an unusable verdict is an abstention, never a
    vote against the target.
    """

    model_config = ConfigDict(frozen=True)
    judge: str = Field(description="the judge as configured, provider:model")
    reported_model: str | None = Field(default=None, description="what the provider said it ran, when it says")
    passed: bool | None
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    raw_text: str = Field(description="the judge's full reply, for audit")
    parse_ok: bool = True


class CaseResult(BaseModel):
    case_id: str
    repeat: int = Field(default=0, description="which repeat of the case this is, 0-based")
    target: str
    answer: Reply
    self_verdict: Verdict | None
    panel_verdicts: list[Verdict]
    panel_passed: bool | None = Field(description="majority of usable panel verdicts; None if too few judges returned one")
    panel_split: str = Field(default="", description="e.g. '2-1' pass-fail, with abstentions noted as '2-0 (1 abstained)'")
    panel_quorum: bool = Field(
        default=True, description="False when fewer than a majority of the configured judges returned a usable verdict"
    )


class RunError(BaseModel):
    """A case that produced no result because a call failed. Kept so a run is never silently short."""

    case_id: str
    repeat: int
    stage: Literal["target", "self-judge"]
    error: str


class Run(BaseModel):
    """Everything from one run, enough to replay the judging without any network."""

    run_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    target: str
    judges: list[str]
    self_judge: bool
    cases_dir: str
    repeats: int = Field(default=1, description="how many times each case was sent to the target")
    temperature: float | None = Field(default=None, description="target sampling temperature; None = provider default")
    judge_temperature: float | None = Field(default=None, description="judge sampling temperature; None = provider default")
    panel_includes_target: bool = Field(
        default=False, description="True if a configured judge is the target itself; such a vote is not independent"
    )
    results: list[CaseResult] = Field(default_factory=list)
    errors: list[RunError] = Field(default_factory=list, description="cases with no result because a call failed; retry with --resume")
    complete: bool = Field(default=False, description="False while the run is in progress or was interrupted")
    live: dict[str, bool] = Field(default_factory=dict, description="adapter id → whether it was called live (False = replayed)")
    case_fingerprints: dict[str, str] = Field(
        default_factory=dict,
        description="case id → sha256 of its content at run time, so a later report or rejudge can tell if the cases changed",
    )
