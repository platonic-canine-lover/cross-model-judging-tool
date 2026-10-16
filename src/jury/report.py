"""The report: self-judge vs panel, per category and per case, and where they disagree.

Vocabulary, used consistently:
  self-judged pass rate      share of cases the target's own model passed
  panel-judged pass rate     share of cases the panel's majority passed, counted over cases WITH a quorum
  self-grade inflation       self-judged minus panel-judged, in points. It is a difference between two
  relative to the panel      opinions. It is not a measure of the target's actual accuracy, because the
                             panel is three other models, not ground truth.
  abstained                  a judge returned no usable verdict (format failure); not a vote
  no quorum                  fewer than a majority of the configured judges returned usable verdicts;
                             the case has no panel verdict and is excluded from the panel pass rate
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from jury.judging import agreement, inflation
from jury.types import Case, CaseResult, Run


@dataclass
class Rates:
    n: int
    n_with_quorum: int
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
        return self.panel_pass / self.n_with_quorum if self.n_with_quorum else 0.0


def rates(run: Run, case_ids: list[str] | None = None) -> Rates:
    rs = [r for r in run.results if case_ids is None or r.case_id in case_ids]
    r = Rates(n=len(rs), n_with_quorum=0, self_pass=0, panel_pass=0, agree=0, self_yes_panel_no=0, self_no_panel_yes=0)
    for x in rs:
        s = x.self_verdict.passed if x.self_verdict else None
        p = x.panel_passed if x.panel_quorum else None
        if x.panel_quorum:
            r.n_with_quorum += 1
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


def _judge_label(v_judge: str, reported: str | None) -> str:
    if reported and reported != v_judge and not v_judge.endswith(":" + reported):
        return f"{v_judge} (reported {reported})"
    return v_judge


def _s(v: object) -> str:
    """Render a tri-state verdict."""
    if v is None:
        return "-"
    return "pass" if v else "FAIL"


def render(run: Run, cases: list[Case], changed_cases: list[str] | None = None) -> str:
    by_id = {c.id: c for c in cases}
    changed = set(changed_cases or [])
    lines: list[str] = []
    lines.append(f"CROSS-MODEL JUDGING REPORT  run {run.run_id}  {run.started_at:%Y-%m-%d %H:%M} UTC")
    lines.append(f"target: {run.target}    panel: {', '.join(run.judges)}    self-judge: {'yes' if run.self_judge else 'no'}")
    live = [k for k, v in run.live.items() if v]
    replayed = [k for k, v in run.live.items() if not v]
    lines.append(f"live calls: {', '.join(live) or 'none'}" + (f"    replayed from recording: {', '.join(replayed)}" if replayed else ""))
    reported = sorted({_judge_label(v.judge, v.reported_model) for r in run.results for v in r.panel_verdicts if v.reported_model})
    if any("(reported" in x for x in reported):
        lines.append("judge identities as reported by providers: " + ", ".join(x for x in reported if "(reported" in x))
    temps = f"target temperature {run.temperature if run.temperature is not None else 'provider default'}, judge temperature {run.judge_temperature if run.judge_temperature is not None else 'provider default'}"
    lines.append(f"repeats per case: {run.repeats}    {temps}")
    if run.panel_includes_target:
        lines.append(
            f"WARNING: the panel includes the target ({run.target}). That vote is not an independent opinion; the panel rate below is partly the target grading itself."
        )
    if not run.complete:
        lines.append(
            f"WARNING: this run is INCOMPLETE: {len(run.errors)} (case, repeat) pair(s) produced no result. Rates below are over what completed. Finish it with: jury run --resume <recording>."
        )
    if changed:
        lines.append(
            f"WARNING: {len(changed)} case definition(s) changed since this recording was made: {', '.join(sorted(changed))}. Verdicts on them are not comparable with the original run."
        )
    lines.append("")

    overall = rates(run)
    no_quorum = overall.n - overall.n_with_quorum
    n_cases = len({r.case_id for r in run.results})
    lines.append("OVERALL")
    lines.append(
        f"  answers {overall.n}"
        + (f" ({n_cases} cases x {run.repeats} repeats)" if run.repeats > 1 else "")
        + (f" ({no_quorum} without a panel quorum, excluded from the panel rate)" if no_quorum else "")
    )
    if run.self_judge:
        lines.append(f"  self-judged pass rate                     {pct(overall.self_rate)}  ({overall.self_pass}/{overall.n})")
    lines.append(
        f"  panel-judged pass rate                    {pct(overall.panel_rate)}  ({overall.panel_pass}/{overall.n_with_quorum}, majority of {len(run.judges)} judges, usable verdicts only)"
    )
    if run.self_judge:
        lines.append(
            f"  self-grade inflation relative to panel    {inflation(overall.self_rate, overall.panel_rate):+.1f} points (self minus panel; a difference of opinion, not a measure of accuracy)"
        )
        lines.append(
            f"  agreement                                 {overall.agree}/{overall.n_with_quorum}; self yes / panel no: {overall.self_yes_panel_no}; self no / panel yes: {overall.self_no_panel_yes}"
        )
    lines.append("")

    ag = agreement([(r.panel_verdicts, r.panel_passed if r.panel_quorum else None) for r in run.results])
    lines.append("JUDGE AGREEMENT  (how far the panel agrees with itself; observed, not chance-corrected)")
    lines.append(f"  pairwise agreement     {pct(ag.pairwise)}  over {ag.pairs} judge pairs")
    lines.append(f"  unanimous answers      {pct(ag.unanimous)}  of answers with a quorum")
    for j in run.judges:
        if j in ag.with_majority:
            lines.append(f"  {j:40} agreed with the panel majority on {pct(ag.with_majority[j])} of its usable verdicts")
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

    if run.repeats > 1:
        lines.append(
            "PER CASE ACROSS REPEATS  (S = self passes / repeats, P = panel passes / repeats with quorum; a split case is one the target does not do consistently)"
        )
        by_case: dict[str, list[CaseResult]] = defaultdict(list)
        for r in run.results:
            by_case[r.case_id].append(r)
        for cid, rs in by_case.items():
            c = by_id[cid]
            s_n = sum(1 for r in rs if r.self_verdict is not None and r.self_verdict.passed is not None)
            s_p = sum(1 for r in rs if r.self_verdict is not None and r.self_verdict.passed)
            q = [r for r in rs if r.panel_quorum]
            p_p = sum(1 for r in q if r.panel_passed)
            consistent = len(q) and (p_p == 0 or p_p == len(q))
            flag = "" if consistent or not q else "  <- INCONSISTENT across repeats"
            if any(r.case_id in changed for r in rs):
                flag += "  [case changed since recording]"
            s_txt = f"{s_p}/{s_n}" if run.self_judge else "-"
            lines.append(f"  {c.id:28} {c.category:22} S {s_txt:5}  P {p_p}/{len(q)}{flag}")
        lines.append("")

    lines.append("PER ANSWER  (S = self verdict, P = panel verdict with split; 'no quorum' = too few usable judge verdicts)")
    for r in run.results:
        c = by_id[r.case_id]
        s = _s(r.self_verdict.passed) if r.self_verdict is not None else "-"
        p = _s(r.panel_passed) if r.panel_quorum else "none"
        split = r.panel_split if r.panel_quorum else f"{r.panel_split} no quorum"
        disagree = (
            r.self_verdict is not None and r.self_verdict.passed is not None and r.panel_quorum and r.self_verdict.passed != r.panel_passed
        )
        flag = ("  <- DISAGREE" if disagree else "") + ("  [case changed since recording]" if r.case_id in changed else "")
        rep_tag = f" #{r.repeat + 1}" if run.repeats > 1 else ""
        lines.append(f"  {c.id + rep_tag:28} {c.category:22} S {s:4}  P {p:4} {split}{flag}")
    lines.append("")

    disagreements = [
        r
        for r in run.results
        if r.self_verdict is not None and r.self_verdict.passed is not None and r.panel_quorum and r.self_verdict.passed != r.panel_passed
    ]
    if disagreements:
        lines.append("DISAGREEMENTS  (read these; a disagreement is a case for a human, not a verdict)")
        for r in disagreements:
            c = by_id[r.case_id]
            lines.append(f"  {c.id}{f' #{r.repeat + 1}' if run.repeats > 1 else ''}: {c.title}")
            lines.append(f"    answer: {r.answer.text[:300].replace(chr(10), ' ')}{'…' if len(r.answer.text) > 300 else ''}")
            assert r.self_verdict is not None
            lines.append(
                f"    self ({_judge_label(r.self_verdict.judge, r.self_verdict.reported_model)}): {_s(r.self_verdict.passed).lower()}; "
                + "; ".join(r.self_verdict.reasons)
            )
            for v in r.panel_verdicts:
                verdict = "abstained (no usable verdict)" if v.passed is None else _s(v.passed).lower()
                lines.append(f"    panel {_judge_label(v.judge, v.reported_model)}: {verdict}; " + "; ".join(v.reasons))
        lines.append("")

    abstentions = [(r.case_id, v.judge) for r in run.results for v in r.panel_verdicts if not v.parse_ok]
    self_abst = [r.case_id for r in run.results if r.self_verdict is not None and not r.self_verdict.parse_ok]
    if abstentions or self_abst:
        lines.append(
            "JUDGE FORMAT FAILURES  (a judge that did not return a usable verdict; these are abstentions about the judge, not evidence about the target)"
        )
        for cid, j in abstentions:
            lines.append(f"  {cid}: panel {j}")
        for cid in self_abst:
            lines.append(f"  {cid}: self-judge")
        lines.append("")

    if run.errors:
        lines.append("ERRORS  (calls that failed; these answers do not exist and are not counted anywhere above)")
        for e in run.errors:
            lines.append(f"  {e.case_id} #{e.repeat + 1} {e.stage}: {e.error}")
        lines.append("")

    tok_in = sum(r.answer.usage.input_tokens or 0 for r in run.results)
    tok_out = sum(r.answer.usage.output_tokens or 0 for r in run.results)
    unknown = sum(1 for r in run.results if r.answer.usage.input_tokens is None)
    lines.append(
        f"TARGET TOKENS  input {tok_in:,}  output {tok_out:,}" + (f"  ({unknown} answers with no usage reported)" if unknown else "")
    )
    lines.append("")
    lines.append(
        "The panel is other models voting; it is not ground truth. Judges from one model family share blind spots. A disagreement is a case for a human to read."
    )
    return "\n".join(lines)
