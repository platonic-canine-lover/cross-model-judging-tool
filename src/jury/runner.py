"""Run cases against a target, judge, record. Replay a recording without any network.

A recording is the Run model as JSON: every answer, every verdict, every raw
response. `jury report` works from a recording alone, and the test suite
and CI replay committed recordings, so neither needs a key.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from jury.judging import judge_one, majority
from jury.types import Case, CaseResult, Message, Reply, Run, RunError, Target


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


def fingerprint(case: Case) -> str:
    """sha256 of everything a judge or target sees for the case, so edits are detectable."""
    payload = case.model_dump(mode="json", exclude={"notes"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class CaseSetMismatchError(ValueError):
    """The case definitions supplied do not match the ones a recording was made with."""


def check_cases_against(run: Run, cases: list[Case], allow_changed: bool = False) -> list[str]:
    """Every recorded case must still exist; changed cases are listed, and refused unless allowed.

    Returns the ids whose definition changed since the recording (empty if none).
    """
    by_id = {c.id: c for c in cases}
    missing = [r.case_id for r in run.results if r.case_id not in by_id]
    if missing:
        raise CaseSetMismatchError(f"recording refers to case ids not in the supplied case set: {', '.join(missing)}")
    changed = [cid for cid, fp in run.case_fingerprints.items() if cid in by_id and fingerprint(by_id[cid]) != fp]
    if changed and not allow_changed:
        raise CaseSetMismatchError(
            "these cases have changed since the recording was made, so verdicts would not be comparable: "
            + ", ".join(changed)
            + ". Rejudge with allow_changed to proceed; the report will mark them."
        )
    return changed


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


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
    repeats: int = 1,
    temperature: float | None = None,
    judge_temperature: float | None = None,
    checkpoint: Path | None = None,
    resume: Run | None = None,
    run_id: str | None = None,
) -> Run:
    """Send every case to the target `repeats` times, judge each answer, and record as you go.

    Each (case, repeat) is independent: a failed target call is recorded in
    `run.errors` and the rest of the run continues. After every result the
    whole run is written to `checkpoint` (if given), so an interrupted run
    is a partial recording, not nothing. Pass the partial recording as
    `resume` to finish it: completed results are kept, and only the
    missing or errored (case, repeat) pairs are sent.
    """
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if resume is not None:
        mismatch = [
            name
            for name, want, have in [
                ("target", target.id, resume.target),
                ("judges", [j.id for j in judges], resume.judges),
                ("repeats", repeats, resume.repeats),
            ]
            if want != have
        ]
        if mismatch:
            raise ValueError(f"cannot resume: {', '.join(mismatch)} differ from the recording")
        check_cases_against(resume, cases)
        run = resume.model_copy(update={"errors": [], "complete": False})
    else:
        run = Run(
            run_id=run_id or new_run_id(),
            target=target.id,
            judges=[j.id for j in judges],
            self_judge=self_judge is not None,
            cases_dir=str(cases_dir),
            repeats=repeats,
            temperature=temperature,
            judge_temperature=judge_temperature,
            panel_includes_target=any(j.id == target.id for j in judges),
            live={t.id: True for t in [target, *judges, *([self_judge] if self_judge else [])]},
            case_fingerprints={c.id: fingerprint(c) for c in cases},
        )
    done = {(r.case_id, r.repeat) for r in run.results}
    todo = [(c, k) for c in cases for k in range(repeats) if (c.id, k) not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def record(result: CaseResult | RunError) -> None:
        async with lock:
            if isinstance(result, CaseResult):
                run.results.append(result)
            else:
                run.errors.append(result)
            if checkpoint is not None:
                save(run, checkpoint)

    async def one(case: Case, k: int) -> None:
        async with sem:
            try:
                answer = await target.ask(messages_for(case))
            except Exception as e:
                await record(RunError(case_id=case.id, repeat=k, stage="target", error=f"{type(e).__name__}: {e}"))
                return
            sv = await judge_one(self_judge, case, answer) if self_judge else None
            pv = list(await asyncio.gather(*(judge_one(j, case, answer) for j in judges)))
            passed, split, quorum = majority(pv, configured=len(judges))
            await record(
                CaseResult(
                    case_id=case.id,
                    repeat=k,
                    target=target.id,
                    answer=answer,
                    self_verdict=sv,
                    panel_verdicts=pv,
                    panel_passed=passed,
                    panel_split=split,
                    panel_quorum=quorum,
                )
            )

    await asyncio.gather(*(one(c, k) for c, k in todo))
    order = {c.id: i for i, c in enumerate(cases)}
    run.results.sort(key=lambda r: (order.get(r.case_id, len(order)), r.repeat))
    run.complete = not run.errors
    if checkpoint is not None:
        save(run, checkpoint)
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
        self._answers: dict[tuple[str, int], Reply] = {(r.case_id, r.repeat): r.answer for r in run.results}

    def answer_for(self, case_id: str, repeat: int = 0) -> Reply:
        return self._answers[(case_id, repeat)]

    async def ask(self, messages: list[Message]) -> Reply:  # pragma: no cover - the runner calls answer_for via rejudge
        raise RuntimeError("ReplayTarget answers by case id; use rejudge()")


async def rejudge(
    run: Run,
    judges: list[Target],
    cases: list[Case],
    self_judge: Target | None = None,
    allow_changed: bool = False,
    judge_temperature: float | None = None,
) -> Run:
    """Re-grade a recorded run's answers with a different panel. No target calls.

    Refuses if the case set no longer contains every recorded case, or if any
    case definition changed since the recording (unless allow_changed, in
    which case the new fingerprints are recorded and the report flags them).
    """
    check_cases_against(run, cases, allow_changed=allow_changed)
    replay = ReplayTarget(run)
    new = run.model_copy(
        update={
            "judges": [j.id for j in judges],
            "self_judge": self_judge is not None,
            "results": [],
            "live": {**{k: False for k in run.live}, **{j.id: True for j in judges}},
            "case_fingerprints": {c.id: fingerprint(c) for c in cases if c.id in {r.case_id for r in run.results}},
            "panel_includes_target": any(j.id == run.target for j in judges),
            "judge_temperature": judge_temperature,
        }
    )
    by_id = {c.id: c for c in cases}
    results: list[CaseResult] = []
    for r in run.results:
        case = by_id[r.case_id]
        answer = replay.answer_for(r.case_id, r.repeat)
        sv = await judge_one(self_judge, case, answer) if self_judge else None
        pv = list(await asyncio.gather(*(judge_one(j, case, answer) for j in judges)))
        passed, split, quorum = majority(pv, configured=len(judges))
        results.append(
            CaseResult(
                case_id=case.id,
                repeat=r.repeat,
                target=run.target,
                answer=answer,
                self_verdict=sv,
                panel_verdicts=pv,
                panel_passed=passed,
                panel_split=split,
                panel_quorum=quorum,
            )
        )
    new.results = results
    return new
