"""The report: self-judge vs panel, per category and per case, and where they disagree."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from jury.judging import inflation
from jury.types import Case, Run


@dataclass
class Rates:
    n: int
    self_pass: int
    panel_pass: int
    agree: int
    self_yes_panel_no: int
    self_no_panel_yes: int

    @property
    def self_rate(self) -> float:
        return self.self_pass / self.n if self.n else 0.0

    @property
    def panel_rate(self) -> float:
        return self.panel_pass / self.n if self.n else 0.0


def rates(run: Run, case_ids: list[str] | None = None) -> Rates:
    rs = [r for r in run.results if case_ids is None or r.case_id in case_ids]
    r = Rates(n=len(rs), self_pass=0, panel_pass=0, agree=0, self_yes_panel_no=0, self_no_panel_yes=0)
    for x in rs:
        s = x.self_verdict.passed if x.self_verdict else None
        p = x.panel_passed
        if s:
            r.self_pass += 1
        if p:
            r.panel_pass += 1
        if s is not None and p is not None:
            if s == p:
                r.agree += 1
            elif s and not p:
                r.self_yes_panel_no += 1
            else:
                r.self_no_panel_yes += 1
    return r


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render(run: Run, cases: list[Case]) -> str:
    by_id = {c.id: c for c in cases}
    lines: list[str] = []
    lines.append(f"CROSS-MODEL JUDGING REPORT  run {run.run_id}  {run.started_at:%Y-%m-%d %H:%M} UTC")
    lines.append(f"target: {run.target}    panel: {', '.join(run.judges)}    self-judge: {'yes' if run.self_judge else 'no'}")
    live = [k for k, v in run.live.items() if v]
    replayed = [k for k, v in run.live.items() if not v]
    lines.append(f"live calls: {', '.join(live) or 'none'}" + (f"    replayed from recording: {', '.join(replayed)}" if replayed else ""))
    lines.append("")

    overall = rates(run)
    lines.append("OVERALL")
    lines.append(f"  cases {overall.n}")
    if run.self_judge:
        lines.append(f"  self-judged pass rate   {pct(overall.self_rate)}  ({overall.self_pass}/{overall.n})")
    lines.append(f"  panel-judged pass rate  {pct(overall.panel_rate)}  ({overall.panel_pass}/{overall.n}, majority of {len(run.judges)})")
    if run.self_judge:
        lines.append(f"  self-grade inflation    {inflation(overall.self_rate, overall.panel_rate):+.1f} points (self minus panel)")
        lines.append(
            f"  agreement               {overall.agree}/{overall.n}; self yes / panel no: {overall.self_yes_panel_no}; self no / panel yes: {overall.self_no_panel_yes}"
        )
    lines.append("")

    cats: dict[str, list[str]] = defaultdict(list)
    for r in run.results:
        cats[by_id[r.case_id].category].append(r.case_id)
    lines.append("BY CATEGORY" + ("                       self   panel   inflation" if run.self_judge else "                       panel"))
    for cat, ids in sorted(cats.items()):
        rt = rates(run, ids)
        if run.self_judge:
            lines.append(f"  {cat:32} {pct(rt.self_rate):>5}  {pct(rt.panel_rate):>5}   {inflation(rt.self_rate, rt.panel_rate):+.1f}")
        else:
            lines.append(f"  {cat:32} {pct(rt.panel_rate):>5}")
    lines.append("")

    lines.append("PER CASE  (S = self verdict, P = panel verdict with split)")
    for r in run.results:
        c = by_id[r.case_id]
        s = "-" if r.self_verdict is None else ("pass" if r.self_verdict.passed else "FAIL")
        p = "-" if r.panel_passed is None else ("pass" if r.panel_passed else "FAIL")
        flag = (
            "  <- DISAGREE" if r.self_verdict is not None and r.panel_passed is not None and r.self_verdict.passed != r.panel_passed else ""
        )
        lines.append(f"  {c.id:28} {c.category:22} S {s:4}  P {p:4} {r.panel_split:>4}{flag}")
    lines.append("")

    disagreements = [
        r for r in run.results if r.self_verdict is not None and r.panel_passed is not None and r.self_verdict.passed != r.panel_passed
    ]
    if disagreements:
        lines.append("DISAGREEMENTS")
        for r in disagreements:
            c = by_id[r.case_id]
            lines.append(f"  {c.id}: {c.title}")
            lines.append(f"    answer: {r.answer.text[:300].replace(chr(10), ' ')}{'…' if len(r.answer.text) > 300 else ''}")
            assert r.self_verdict is not None
            lines.append(
                f"    self ({r.self_verdict.judge}): {'pass' if r.self_verdict.passed else 'fail'}; " + "; ".join(r.self_verdict.reasons)
            )
            for v in r.panel_verdicts:
                lines.append(
                    f"    panel {v.judge}: {'pass' if v.passed else 'fail'}{'' if v.parse_ok else ' (did not return JSON)'}; "
                    + "; ".join(v.reasons)
                )
        lines.append("")

    unparsed = [(r.case_id, v.judge) for r in run.results for v in r.panel_verdicts if not v.parse_ok]
    if unparsed:
        lines.append("JUDGES THAT DID NOT RETURN JSON (counted as fail): " + ", ".join(f"{c}/{j}" for c, j in unparsed))
        lines.append("")

    tok_in = sum(r.answer.usage.input_tokens or 0 for r in run.results)
    tok_out = sum(r.answer.usage.output_tokens or 0 for r in run.results)
    unknown = sum(1 for r in run.results if r.answer.usage.input_tokens is None)
    lines.append(
        f"TARGET TOKENS  input {tok_in:,}  output {tok_out:,}" + (f"  ({unknown} answers with no usage reported)" if unknown else "")
    )
    lines.append("")
    lines.append(
        "Read this as: the panel is three other models voting; it is not ground truth either. A disagreement is a case for a human to read."
    )
    return "\n".join(lines)
