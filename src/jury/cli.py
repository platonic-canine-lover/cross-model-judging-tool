"""jury: run, rejudge, report."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from jury.adapters import providers, resolve
from jury.report import render
from jury.runner import CaseSetMismatchError, check_cases_against, load, load_cases, new_run_id, rejudge, run_cases, save

app = typer.Typer(add_completion=False, help="Put an agent through a case set; judge it by itself and by a panel; report the disagreement.")


@app.command()
def run(
    target: Annotated[str, typer.Option(help="provider:model, e.g. ollama:qwen3.8:27b or copilot-studio:my_agent")],
    judge: Annotated[list[str], typer.Option("--judge", help="panel member, repeatable")],
    cases: Annotated[Path, typer.Option(help="directory of case YAML files")] = Path("cases"),
    out: Annotated[Path | None, typer.Option(help="recording path; default runs/<run id>.json")] = None,
    self_judge: Annotated[bool, typer.Option("--self-judge/--no-self-judge", help="also have the target grade itself")] = True,
    self_judge_as: Annotated[
        str | None, typer.Option(help="model to self-judge with, if the target cannot grade (a Copilot Studio agent)")
    ] = None,
    concurrency: Annotated[int, typer.Option()] = 3,
    repeats: Annotated[int, typer.Option(help="send each case this many times; 5 shows whether a behaviour is consistent or luck")] = 1,
    temperature: Annotated[float | None, typer.Option(help="target sampling temperature; omit for the provider default")] = None,
    judge_temperature: Annotated[float | None, typer.Option(help="judge sampling temperature; 0 by default for repeatable grading")] = 0.0,
    resume: Annotated[
        Path | None, typer.Option(help="finish an incomplete recording: keeps its results, sends only what is missing")
    ] = None,
) -> None:
    """Send every case to the target, grade with the panel (and the target itself), save a recording, print the report.

    The recording is written after every answer, so an interrupted or partly
    failed run leaves a partial recording to resume, not nothing.
    """
    t = resolve(target, temperature)
    judges = [resolve(j, judge_temperature) for j in judge]
    if any(j.id == t.id for j in judges):
        typer.echo(
            f"warning: {t.id} is both the target and a panel judge. That vote is not an independent opinion; the report will say so.",
            err=True,
        )
    sj = None
    if self_judge:
        sj = resolve(self_judge_as, judge_temperature) if self_judge_as else resolve(target, judge_temperature)
    case_list = load_cases(cases)
    partial = load(resume) if resume else None
    run_id = partial.run_id if partial else new_run_id()
    path = out or resume or Path("runs") / f"{run_id}.json"
    try:
        result = asyncio.run(
            run_cases(
                t,
                judges,
                case_list,
                cases,
                sj,
                concurrency,
                repeats=repeats,
                temperature=temperature,
                judge_temperature=judge_temperature,
                checkpoint=path,
                resume=partial,
                run_id=run_id,
            )
        )
    except (CaseSetMismatchError, ValueError) as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(render(result, case_list))
    typer.echo(
        f"\nrecording: {path}" + ("" if result.complete else f"    INCOMPLETE: {len(result.errors)} failed; rerun with --resume {path}")
    )


@app.command()
def report(
    recording: Annotated[Path, typer.Argument(help="a run recording (runs/*.json)")],
    cases: Annotated[Path, typer.Option(help="the case directory the run used")] = Path("cases"),
) -> None:
    """Print the report for a saved recording. No network. Cases that changed since the recording are flagged."""
    r = load(recording)
    case_list = load_cases(cases)
    try:
        changed = check_cases_against(r, case_list, allow_changed=True)
    except CaseSetMismatchError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(render(r, case_list, changed_cases=changed))


@app.command("rejudge")
def rejudge_cmd(
    recording: Annotated[Path, typer.Argument()],
    judge: Annotated[list[str], typer.Option("--judge", help="new panel, repeatable")],
    cases: Annotated[Path, typer.Option()] = Path("cases"),
    out: Annotated[Path | None, typer.Option()] = None,
    self_judge_as: Annotated[str | None, typer.Option(help="model to self-judge with; omit for no self-judge")] = None,
    allow_changed: Annotated[
        bool, typer.Option("--allow-changed", help="proceed even if case definitions changed since the recording; the report marks them")
    ] = False,
    judge_temperature: Annotated[float | None, typer.Option(help="judge sampling temperature; 0 by default")] = 0.0,
) -> None:
    """Grade a recording's answers again with a different panel. Calls the judges, not the target.

    Refuses if the case set is missing a recorded case, or if any case changed since the recording (unless --allow-changed).
    """
    r = load(recording)
    case_list = load_cases(cases)
    judges = [resolve(j, judge_temperature) for j in judge]
    sj = resolve(self_judge_as, judge_temperature) if self_judge_as else None
    try:
        changed = check_cases_against(r, case_list, allow_changed=allow_changed)
        new = asyncio.run(rejudge(r, judges, case_list, sj, allow_changed=allow_changed, judge_temperature=judge_temperature))
    except CaseSetMismatchError as e:
        raise typer.BadParameter(str(e)) from e
    path = out or recording.with_name(recording.stem + "-rejudged.json")
    save(new, path)
    typer.echo(render(new, case_list, changed_cases=changed))
    typer.echo(f"\nrecording: {path}")


@app.command("providers")
def providers_cmd() -> None:
    """List the adapter providers available."""
    for p in providers():
        typer.echo(p)


if __name__ == "__main__":
    app()
