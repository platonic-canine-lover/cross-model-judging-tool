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
