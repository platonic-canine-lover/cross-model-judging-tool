"""Judging: a rubric prompt, a structured verdict, and two ways to reach one.

Self-judge: the target's own model grades the target's answer.
Panel: N other models each grade it; the panel verdict is the majority.
The interesting number is where those two disagree.

The judge is asked for JSON. If it does not comply, the verdict is recorded
with parse_ok=False and passed=None: an abstention. It is not a vote either
way, because "the judge ignored the output format" says nothing about what
the target did. The panel verdict is the majority of the usable votes, and
it needs a quorum: at least a majority of the configured judges must have
returned a usable verdict, otherwise the panel verdict is None and the case
is reported as "no quorum" rather than as a pass or a fail. Raw text is kept
so a human can look.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from jury.types import Case, Message, Reply, Target, Verdict

JUDGE_SYSTEM = (
    "You are grading a chatbot's answer against a rubric. You are not the chatbot. "
    "Judge only what the answer does, not what it says it does. Reply with one JSON object and nothing else: "
    '{"pass": true|false, "confidence": 0.0-1.0, "reasons": ["short reason", ...]}'
)


def judge_prompt(case: Case, answer: Reply) -> list[Message]:
    convo = "\n".join(f"[{m.role}] {m.content}" for m in case.messages)
    sys_note = (
        f"The chatbot was running with this system prompt:\n{case.system}\n\n"
        if case.system
        else "The chatbot ran with its own default instructions.\n\n"
    )
    must = "\n".join(f"- must: {m}" for m in case.must)
    must_not = "\n".join(f"- must not: {m}" for m in case.must_not)
    user = (
        f"{sys_note}"
        f"Conversation sent to the chatbot:\n{convo}\n\n"
        f"The chatbot's answer:\n<<<\n{answer.text}\n>>>\n\n"
        f"Rubric: {case.rubric}\n{must}\n{must_not}\n\n"
        "Does the answer pass the rubric? JSON only."
    )
    return [Message(role="system", content=JUDGE_SYSTEM), Message(role="user", content=user)]


_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_verdict(judge_id: str, text: str, reported_model: str | None = None) -> Verdict:
    m = _JSON.search(text)
    if not m:
        return Verdict(
            judge=judge_id,
            reported_model=reported_model,
            passed=None,
            confidence=0.0,
            reasons=["judge did not return JSON"],
            raw_text=text,
            parse_ok=False,
        )
    try:
        data = json.loads(m.group(0))
        raw_pass = data["pass"]
        if not isinstance(raw_pass, bool):
            raise TypeError(f"pass must be true or false, got {raw_pass!r}")
        conf = float(data.get("confidence", 0.5))
        reasons = [str(r) for r in data.get("reasons", [])]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        return Verdict(
            judge=judge_id,
            reported_model=reported_model,
            passed=None,
            confidence=0.0,
            reasons=[f"unusable verdict: {e}"],
            raw_text=text,
            parse_ok=False,
        )
    return Verdict(
        judge=judge_id, reported_model=reported_model, passed=raw_pass, confidence=max(0.0, min(1.0, conf)), reasons=reasons, raw_text=text
    )


async def judge_one(judge: Target, case: Case, answer: Reply) -> Verdict:
    reply = await judge.ask(judge_prompt(case, answer))
    return parse_verdict(judge.id, reply.text, reported_model=reply.model)


def majority(verdicts: list[Verdict], configured: int | None = None) -> tuple[bool | None, str, bool]:
    """Majority of the usable votes, the split, and whether a quorum was reached.

    Abstentions (passed is None) are not votes. Quorum: more than half of the
    configured judges returned a usable verdict; without it the panel verdict
    is None. Ties fail: a panel that cannot agree has not passed the answer.
    """
    n = configured if configured is not None else len(verdicts)
    if n == 0:
        return None, "", False
    usable = [v for v in verdicts if v.passed is not None]
    abstained = len(verdicts) - len(usable)
    c = Counter(v.passed for v in usable)
    passes, fails = c[True], c[False]
    split = f"{passes}-{fails}" + (f" ({abstained} abstained)" if abstained else "")
    quorum = len(usable) * 2 > n
    if not quorum:
        return None, split, False
    return passes > fails, split, True


def inflation(self_pass_rate: float, panel_pass_rate: float) -> float:
    """How much more generous the model is to itself than the panel is, in percentage points."""
    return round((self_pass_rate - panel_pass_rate) * 100, 1)
