"""jury: run, rejudge, report."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from jury.adapters import providers, resolve
from jury.report import render
from jury.runner import load, load_cases, rejudge, run_cases, save

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
) -> None:
    """Send every case to the target, grade with the panel (and the target itself), save a recording, print the report."""
    t = resolve(target)
    judges = [resolve(j) for j in judge]
    sj = None
    if self_judge:
        sj = resolve(self_judge_as) if self_judge_as else t
    case_list = load_cases(cases)
    result = asyncio.run(run_cases(t, judges, case_list, cases, sj, concurrency))
    path = out or Path("runs") / f"{result.run_id}.json"
    save(result, path)
    typer.echo(render(result, case_list))
    typer.echo(f"\nrecording: {path}")


@app.command()
def report(
    recording: Annotated[Path, typer.Argument(help="a run recording (runs/*.json)")],
    cases: Annotated[Path, typer.Option(help="the case directory the run used")] = Path("cases"),
) -> None:
    """Print the report for a saved recording. No network."""
    r = load(recording)
    typer.echo(render(r, load_cases(cases)))


@app.command("rejudge")
def rejudge_cmd(
    recording: Annotated[Path, typer.Argument()],
    judge: Annotated[list[str], typer.Option("--judge", help="new panel, repeatable")],
    cases: Annotated[Path, typer.Option()] = Path("cases"),
    out: Annotated[Path | None, typer.Option()] = None,
    self_judge_as: Annotated[str | None, typer.Option(help="model to self-judge with; omit for no self-judge")] = None,
) -> None:
    """Grade a recording's answers again with a different panel. Calls the judges, not the target."""
    r = load(recording)
    case_list = load_cases(cases)
    judges = [resolve(j) for j in judge]
    sj = resolve(self_judge_as) if self_judge_as else None
    new = asyncio.run(rejudge(r, judges, case_list, sj))
    path = out or recording.with_name(recording.stem + "-rejudged.json")
    save(new, path)
    typer.echo(render(new, case_list))
    typer.echo(f"\nrecording: {path}")


@app.command("providers")
def providers_cmd() -> None:
    """List the adapter providers available."""
    for p in providers():
        typer.echo(p)


if __name__ == "__main__":
    app()
