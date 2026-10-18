# Technical report — Focused Bern Research Highlights

- **Challenge:** Bern Economic Development Agency — Research & Expertise Navigator
- **Event:** On-site Liebefeld
- **Team:** TempTeam
- **Demo:** Not yet recorded

## Implementation

The focused collector surveys the supplied University of Bern inventory, ARTORG and Diabetes Center Berne. It retains at most 500 research candidates with short source excerpts, URLs and English explanations. Local deterministic rules perform selection without Apertus, a model endpoint, an API key or a GPU. The legacy company-search implementation remains separate.

The data flow is HTML or same-domain WordPress JSON, temporary plain text, rule selection, evidence validation, deduplication and SQLite persistence. `navigator focused-crawl` collects; `navigator highlights` inspects and exports JSON. Raw HTML and full page text are never archived by these commands.

## Boundaries and resource limits

Only original inventory hosts and the two named centers are allowed. Every redirect destination is checked before fetching. Robots rules and a minimum one-second domain delay apply. Defaults are 2,000 content requests, four concurrent domains, depth eight, 10,000 queued URLs, 2 MB per response and 36,000 characters per document evaluation. There is no model-call budget because there are no model calls.

The complete workflow uses `--complete` to remove request, depth and frontier ceilings and traverse all eligible reachable links. It keeps the global 500-record ceiling, the original domain boundary, robots checks and response limits. Pending/in-flight URLs are persisted per batch; completed versioned URLs are skipped on resumption, while failed work is retried. Live reports and exports are written atomically approximately every 30 seconds. Compact URL state is retained for the full traversal rather than pruned to 10,000 rows. This mode can run for hours and still cannot discover unlinked or inaccessible content.

The crawler does not import discovered domains or fetch external references, PDFs, BORIS metadata or full texts. DCB's WordPress endpoints provide structured content on its original domain. Navigation pages remain useful traversal points without becoming records. Historic archives have no age cutoff.

## Selection and interpretation

English and German patterns retain substantive research findings, projects with defined objectives, developed technologies and specified research services. Stronger patterns identify controlled and prospective comparative results, documented technology adoption, validated capabilities with external use, specialized facilities, named strategic programs and recognized scholarly achievements. The complete workflow retains the best 500 candidates across the traversed content, without manufacturing a quota. General institutional introductions, metadata cards and routine announcements remain excluded.

Scientific, practical and capability scores remain separate. Substantive matches receive 2, stronger matches receive 3, and unmatched dimensions receive 0. Acceptance starts at 2; `highlights --min-score 3` shows the stronger subset. The rules do not assign exceptional scores of 4. These values indicate review priority, not independently established impact. Every candidate is labeled `selection_method: rules`, `review_status: unreviewed`, with named `matched_rules` and verbatim evidence. Research aims are eligible as project descriptions, not completed outcomes.

Authored summaries and rationale use English templates. Original names and source excerpts retain source language; automatic translation and detailed scientific paraphrasing are not implemented. Unsupported fields remain empty or unknown. Completion dates are extracted only from explicit completion statements. Expert extraction is conservative and the current rules leave expert lists empty.

## Storage and updates

`data/focused.sqlite` contains findings, bounded source observations, identity keys, compact URL state and the latest ten reports. The 500-record ceiling applies across runs. Repeated mentions do not increase scores. Explicit shared identifiers and matching source names support deduplication; generic template titles do not merge unrelated findings.

Successful complete evaluations replace observations from that source. Network, parsing or selection failures preserve previous evidence. Unchanged successful documents skip rule evaluation unless `--reevaluate` is supplied. Source-check mode is explicit and does not update findings. JSON exports use schema version 2 and include selection method and review status.

## Validation

The offline suite covers domain restrictions, redirects, robots rules and pacing, resource limits, DCB pagination, evidence validation, historical results, record limits, deduplication, reruns and absence of raw-page storage. It also verifies actual rule selection without a model endpoint and rejects mere component integration as technology adoption.

The 30 manually authored synthetic rubric examples span all three source groups, with 15 positives and 15 negatives. Rules version `focused-rules-v5` selected all 15 positives and none of the negatives in the development run. This is an in-sample diagnostic, not a held-out measurement of real-world precision. Live inspection also identified missed prospective comparisons, metadata-only API items, loss of inline sentence structure, cross-section evidence mixing and unstable inferred names. Regression tests now cover these cases. Heading boundaries constrain evidence; the shortest sufficient excerpts are retained. Explicit project names support deduplication, and generic funding portfolios do not qualify as projects. The 90% real-world precision target remains unverified.

The expanded offline suite passes 94 tests, including complete traversal beyond sample budgets, durable interruption/resumption, retries, broader selection, research objectives, single-method services, related-card removal and stable identity across record-type changes. An earlier strict-rule live run on October 18, 2026 used 80 content requests and retained seven candidates spanning the three source groups. That historical count predates the broader selector and is not its expected yield. The current run report records the actual collection result; candidate counts do not establish real-world precision.

Run reports record source coverage, fetched content, evaluated pieces, considered candidates, accepted observations, retained unique findings, rejection reasons, errors and the stopping reason. Coverage is bounded and is never described as exhaustive.

## Limitations

Rules miss unfamiliar wording, unsupported languages and important discoveries outside their implemented evidence patterns. Co-occurring statements can be misattributed or misinterpreted. Shared projects and translated names can remain duplicated without a common identifier. Static extraction excludes JavaScript-rendered material and external supporting sources. Short evidence windows and response limits can hide qualifications. Human review is needed before describing candidates as verified achievements.

This version implements collection, storage, inspection and export. Semantic search, company matching, a new frontend and hosted deployment are not connected to the focused database. Embeddings are not generated by this workflow.

## Reproduction

Use Python 3.10 or later. The focused workflow needs only `src/requirements-focused.txt` and Python's standard SQLite implementation. Collection requires access to source websites; tests and synthetic evaluation run offline.

```text
pip install -r src/requirements-focused.txt
python -m unittest discover -s tests -v
python -m navigator focused-crawl --only www artorg dcberne --max-fetches 80 --reevaluate --report data/focused-run.json
python -m navigator highlights --out data/highlights.json
python -m navigator.focused.evaluate --out data/focused-rules-evaluation.json
```

Set `PYTHONPATH=src` before running these commands. Record the repository revision and ruleset version with evaluation results. See [Focused Crawler](Docs/Focused%20Crawler.md) for configuration and the export contract.

## License and sources

This report uses CC-BY-4.0; project code follows the repository's Apache-2.0 license. Source content retains its own rights. The collector retains brief excerpts rather than a redistributed page corpus.

The scope comes from the supplied `Docs/unibe_sous_domaines_publics_etendus.xlsx` inventory, [ARTORG](https://www.artorg.unibe.ch/) and [Diabetes Center Berne](https://www.dcberne.com/).
