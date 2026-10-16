"""Judging: a rubric prompt, a structured verdict, and two ways to reach one.

Self-judge: the target's own model grades the target's answer.
Panel: N other models each grade it; the panel verdict is the majority.
The interesting number is where those two disagree.

The judge is asked for JSON. If it does not comply, the verdict is recorded
with parse_ok=False and counted as a FAIL for the panel (a judge that will
not follow a one-line format is not a vote for the answer), and the raw
text is kept so a human can look.
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


def parse_verdict(judge_id: str, text: str) -> Verdict:
    m = _JSON.search(text)
    if not m:
        return Verdict(judge=judge_id, passed=False, confidence=0.0, reasons=["judge did not return JSON"], raw_text=text, parse_ok=False)
    try:
        data = json.loads(m.group(0))
        passed = bool(data["pass"])
        conf = float(data.get("confidence", 0.5))
        reasons = [str(r) for r in data.get("reasons", [])]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        return Verdict(judge=judge_id, passed=False, confidence=0.0, reasons=[f"unparseable verdict: {e}"], raw_text=text, parse_ok=False)
    return Verdict(judge=judge_id, passed=passed, confidence=max(0.0, min(1.0, conf)), reasons=reasons, raw_text=text)


async def judge_one(judge: Target, case: Case, answer: Reply) -> Verdict:
    reply = await judge.ask(judge_prompt(case, answer))
    return parse_verdict(judge.id, reply.text)


def majority(verdicts: list[Verdict]) -> tuple[bool | None, str]:
    """Majority pass/fail and the split as 'passes-fails'. Ties fail: a panel that cannot agree has not passed the answer."""
    if not verdicts:
        return None, ""
    c = Counter(v.passed for v in verdicts)
    passes, fails = c[True], c[False]
    return passes > fails, f"{passes}-{fails}"


def inflation(self_pass_rate: float, panel_pass_rate: float) -> float:
    """How much more generous the model is to itself than the panel is, in percentage points."""
    return round((self_pass_rate - panel_pass_rate) * 100, 1)
