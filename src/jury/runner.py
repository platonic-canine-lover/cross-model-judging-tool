"""Run cases against a target, judge, record. Replay a recording without any network.

A recording is the Run model as JSON: every answer, every verdict, every raw
response. `jury report` works from a recording alone, and the test suite
and CI replay committed recordings, so neither needs a key.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from jury.judging import judge_one, majority
from jury.types import Case, CaseResult, Message, Reply, Run, Target


def load_cases(directory: Path) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        for item in raw["cases"]:
            cases.append(Case.model_validate(item))
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate case ids: {sorted(dupes)}")
    return cases


def messages_for(case: Case) -> list[Message]:
    msgs: list[Message] = []
    if case.system:
        msgs.append(Message(role="system", content=case.system))
    msgs.extend(case.messages)
    return msgs


async def run_cases(
    target: Target,
    judges: list[Target],
    cases: list[Case],
    cases_dir: Path,
    self_judge: Target | None,
    concurrency: int = 3,
) -> Run:
    run = Run(
        run_id=f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
        target=target.id,
        judges=[j.id for j in judges],
        self_judge=self_judge is not None,
        cases_dir=str(cases_dir),
        live={t.id: True for t in [target, *judges, *([self_judge] if self_judge else [])]},
    )
    sem = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> CaseResult:
        async with sem:
            answer = await target.ask(messages_for(case))
            sv = await judge_one(self_judge, case, answer) if self_judge else None
            pv = list(await asyncio.gather(*(judge_one(j, case, answer) for j in judges)))
            passed, split = majority(pv)
            return CaseResult(
                case_id=case.id, target=target.id, answer=answer, self_verdict=sv, panel_verdicts=pv, panel_passed=passed, panel_split=split
            )

    run.results = list(await asyncio.gather(*(one(c) for c in cases)))
    return run


def save(run: Run, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.model_dump(mode="json"), indent=2))


def load(path: Path) -> Run:
    return Run.model_validate(json.loads(path.read_text()))


class ReplayTarget:
    """Answers from a recording instead of a provider. For re-judging an old run with new judges, and for tests."""

    def __init__(self, run: Run) -> None:
        self.id = run.target
        self._answers: dict[str, Reply] = {r.case_id: r.answer for r in run.results}
        self._by_prompt: dict[str, Reply] = {}

    def answer_for(self, case_id: str) -> Reply:
        return self._answers[case_id]

    async def ask(self, messages: list[Message]) -> Reply:  # pragma: no cover - the runner calls answer_for via rejudge
        raise RuntimeError("ReplayTarget answers by case id; use rejudge()")


async def rejudge(run: Run, judges: list[Target], cases: list[Case], self_judge: Target | None = None) -> Run:
    """Re-grade a recorded run's answers with a different panel. No target calls."""
    replay = ReplayTarget(run)
    new = run.model_copy(
        update={
            "judges": [j.id for j in judges],
            "self_judge": self_judge is not None,
            "results": [],
            "live": {**{k: False for k in run.live}, **{j.id: True for j in judges}},
        }
    )
    by_id = {c.id: c for c in cases}
    results: list[CaseResult] = []
    for r in run.results:
        case = by_id[r.case_id]
        answer = replay.answer_for(r.case_id)
        sv = await judge_one(self_judge, case, answer) if self_judge else None
        pv = list(await asyncio.gather(*(judge_one(j, case, answer) for j in judges)))
        passed, split = majority(pv)
        results.append(
            CaseResult(
                case_id=case.id,
                target=run.target,
                answer=answer,
                self_verdict=sv,
                panel_verdicts=pv,
                panel_passed=passed,
                panel_split=split,
            )
        )
    new.results = results
    return new
