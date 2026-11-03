# Review log

Each public repository in this set is put past an independent reviewer (a
different AI model, reading the code and the CI history, not the author's
account of it) before it is called done. This records what the review
found and what changed. Findings that were not acted on are listed with
the reason.

## Review 1 (commit `cc9bba3` reviewed; fixes in the following commit)

Scores given: portfolio relevance 9.5, problem selection 9.0, architecture
8.5, testing and reproducibility 8.5, evaluation methodology 7.5,
production readiness 6.0.

**High. The headline metric could be read as a measure of accuracy.**
The self-judged minus panel-judged difference is a difference between two
opinions, not proof that a model overestimates itself. Fixed: the report
and README now call it "self-grade inflation relative to the panel"
everywhere, the report line says "a difference of opinion, not a measure
of accuracy", and the README's "Why" and "Honest limits" sections say what
the number does and does not show.

**High. Malformed verdicts were counted as failing votes.** A judge that
ignored the JSON format was treated as having voted against the target,
which mixed "did the target meet the rubric" with "did the judge follow
the format". Fixed: `Verdict.passed` is now `bool | None`; an unusable
verdict is an abstention with `passed: null` and `parse_ok: false`. The
panel verdict is the majority of usable votes and requires a quorum (more
than half of the configured judges usable); without one the case is "no
quorum", not a fail, and it is excluded from the panel pass rate. The
report lists abstentions under "judge format failures" and says they are
about the judge, not the target. The split shows abstentions explicitly
(`2-0 (1 abstained)`). Tests cover abstention not tipping a verdict, no
quorum, and quorum measured against the configured panel size.

**Medium. Rejudge had no safeguard against a changed case set.** A
missing case id raised a bare `KeyError`; an edited rubric silently
changed the basis of comparison. Fixed: every run records a sha256
fingerprint per case (content, excluding human notes).
`check_cases_against` refuses a case set that is missing a recorded case,
and refuses changed cases unless allowed. `jury rejudge` refuses by
default and takes `--allow-changed`, which records the new fingerprints;
`jury report` always runs and flags changed cases with a warning line and
a per-case mark.

**Medium. Judge identity.** The configured judge id is not proof of which
model produced a verdict. Fixed: `Verdict.reported_model` keeps what the
provider said it ran, alongside the configured `judge`; the report shows
the reported identity wherever it differs. The README now says three
judges are not necessarily three independent opinions.

**Noted, no change.** The reviewer asked that the project stay focused and
not add providers, categories, a dashboard or a database. Agreed; none
were added. The Copilot Studio adapter remains documented as not yet run
against a live agent.

## Review 2 (commit `e4d7cb3` reviewed)

**A judge writing `"pass": "false"` as a string.** After review 1 that was
an abstention (non-boolean); before it, `bool("false")` would have been a
pass, the exact failure the tool exists to catch. Fixed: the strings
`true` and `false` (any case) are votes; anything else still abstains. A
test pins `"false"` as a fail vote.

**One failed API call lost the whole run.** Nothing was saved until the
end and an exception anywhere propagated out. Fixed: the recording is
written after every answer; a target call that fails is recorded under
`errors` and the other cases continue; a judge call that fails is an
abstention carrying the error; `jury run --resume <recording>` finishes a
partial run, sending only the missing (case, repeat) pairs, and refuses
if the target or panel differ from the recording.

**One answer per case, no temperature control, no measure of whether the
judges agree.** Fixed: `--repeats N` sends each case N times;
`--temperature` and `--judge-temperature` (default 0) are passed to the
adapters and recorded in the run (a Copilot Studio agent refuses a
temperature rather than ignoring one). The report shows passes per
repeat for each case and marks inconsistent ones, and a judge-agreement
block gives pairwise agreement, the unanimous share, and each judge's
agreement with the panel majority.

**The README's example put the target on its own panel.** Fixed: the
example uses three other models; `jury run` warns if a judge id equals
the target id, the run records `panel_includes_target`, and the report
carries a warning. The README "Why" now says the original finding came
from five runs and a three-model panel, without claiming the panel
excluded the target.

**Model ids.** The reviewer said `claude-haiku-5-5` does not exist. It
does; the reviewer's model list was out of date. The README now says the
ids in the example are examples and to use whatever the account lists.

43 tests.

## Review 3: independent code scan (commit `656b301` reviewed)

**The self-judged rate counted the self-judge's unusable verdicts as
fails, while the panel rate excluded the panel's.** The two rates were
over different answers, so the headline inflation figure could move for
reasons that had nothing to do with self-grading. A self-judge that agreed
with the panel on every answer it graded, but returned unreadable output
on half of them, was reported as "self 50%, panel 100%, inflation -50
points, agreement 2/4". Fixed: the self rate is over usable self verdicts,
with the excluded count printed; inflation, the category table and
agreement are computed on the PAIRED answers (a usable self verdict and a
panel quorum on the same answer), and the report says how many that is.
Tests reproduce the case above (now +0.0 points, 2/2) and check that an
answer without a panel quorum is left out of both sides.

45 tests.

## Fresh-clone check (3 November 2026)

**Installs ignored the lockfile.** The README and CI used `uv pip install
-e`, which resolves the newest releases rather than `uv.lock`: a fresh
install got Anthropic SDK 2.4.0 instead of the locked 1.15.0. Fixed: the
README and CI use `uv sync` (`--locked` in CI, so a stale lock fails the
build), with every extra.

**The Copilot Studio adapter failed `mypy` against client 1.9.** Microsoft
renamed `start_conversation`'s argument; the adapter's protocol named it
the old way. CI never installed the `copilot` extra, so it was never
type-checked. Runtime was unaffected (the adapter passes arguments by
position). Fixed: the protocol's parameters are positional-only, and CI now
installs the extra. Checked against the locked client (1.8.0) and the
newest (1.9.0).

The README now activates the virtual environment, without which `jury` is
not on the PATH, and the pytest-asyncio fixture loop scope is set
explicitly ahead of a default change.
