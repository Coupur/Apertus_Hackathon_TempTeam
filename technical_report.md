# Technical report — Focused Bern Research Highlights

- **Challenge:** Bern Economic Development Agency — Research & Expertise Navigator
- **Event:** On-site Liebefeld
- **Team:** TempTeam
- **Demo:** Not yet recorded

## Implementation

The focused collector surveys the supplied University of Bern inventory, ARTORG and Diabetes Center Berne. It retains at most 700 findings with short source excerpts, URLs and English explanations. Local deterministic rules perform selection without Apertus, a model endpoint, an API key or a GPU. The legacy company-search implementation remains separate.

The data flow is HTML or same-domain WordPress JSON, temporary plain text, rule selection, evidence validation, deduplication and SQLite persistence. `navigator focused-crawl` collects; `navigator highlights` inspects and exports JSON. Raw HTML and full page text are never archived by these commands.

## Boundaries and resource limits

Only original inventory hosts and the two named centers are allowed. Every redirect destination is checked before fetching. Robots rules and a minimum one-second domain delay apply. Defaults are 2,000 content requests, four concurrent domains, depth eight, 10,000 queued URLs, 2 MB per response and 36,000 characters per document evaluation. There is no model-call budget because there are no model calls.

The complete workflow uses `--complete` to remove request, depth and frontier ceilings and traverse all eligible reachable links. It keeps the global 700-record ceiling, the original domain boundary, robots checks and response limits. Pending/in-flight URLs are persisted per batch; completed versioned URLs are skipped on resumption, while failed work is retried. Live reports and exports are written atomically approximately every 30 seconds. Compact URL state is retained for the full traversal rather than pruned to 10,000 rows. This mode can run for hours and still cannot discover unlinked or inaccessible content.

The crawler does not import discovered domains or fetch external references, PDFs, BORIS metadata or full texts. DCB's WordPress endpoints provide structured content on its original domain. Navigation pages remain useful traversal points without becoming records. Historic archives have no age cutoff.

## Selection and interpretation

English and German patterns retain substantive research findings, projects with defined objectives, developed technologies and specified research services. Stronger patterns identify controlled and prospective comparative results, documented technology adoption, validated capabilities with external use, specialized facilities, named strategic programs and recognized scholarly achievements. The complete workflow retains the highest-scoring 700 collected candidates across the traversed content, without manufacturing a quota. General institutional introductions, metadata cards and routine announcements remain excluded.

Scientific, practical and capability scores remain separate. Substantive matches receive 2, stronger matches receive 3, and unmatched dimensions receive 0. Acceptance starts at 2; `highlights --min-score 3` shows the stronger subset. The rules do not assign exceptional scores of 4. These values indicate review priority, not independently established impact. Every candidate is labeled `selection_method: rules`, `review_status: unreviewed`, with named `matched_rules` and verbatim evidence. Research aims are eligible as project descriptions, not completed outcomes.

Version `evidence-v1` adds seven evidence criteria (methodology, quantitative evidence, validation, adoption, accessibility, collaboration and reproducibility), scored 0–4 with explicit weights of 20/20/20/15/10/10/5. Ranking uses the weighted 0–100 selection score and stable ID, descending; legacy tiers remain work acceptance gates only. Each nonzero criterion has a supporting assertion and source URL. Repeated mentions do not add points, and missing evidence is not proof of poor research. The weights are initial policy choices requiring independent calibration.

Authored summaries and rationale use English templates. Original names and source excerpts retain source language; automatic translation and detailed scientific paraphrasing are not implemented. Unsupported fields remain empty or unknown. Completion dates are extracted only from explicit completion statements. Expert extraction is conservative and the current rules leave expert lists empty.

## Storage and updates

`data/focused.sqlite` contains findings, bounded source observations, identity keys, compact URL state and the latest ten reports. The 700-record ceiling applies across runs. Repeated mentions do not increase scores. Explicit shared identifiers and matching source names support deduplication; generic template titles do not merge unrelated findings.

Successful complete evaluations replace observations from that source. Network, parsing or selection failures preserve previous evidence. Unchanged successful documents skip rule evaluation unless `--reevaluate` is supplied. Source-check mode is explicit and does not update findings. JSON exports use schema version 3 and include selection method, review status and unified selection scores.

## Validation

The offline suite covers domain restrictions, redirects, robots rules and pacing, resource limits, DCB pagination, evidence validation, historical results, record limits, deduplication, reruns and absence of raw-page storage. It also verifies actual rule selection without a model endpoint and rejects mere component integration as technology adoption.

The evaluation set contains 54 authored synthetic development documents: the original 30 classification cases plus 24 cases in six priority groups, including German and humanities examples. Rules `focused-rules-v9` with ranking `evidence-v1` accept all 33 positives and reject all 21 negatives in the development run. Precision, recall and F1 are 1.0; the Wilson 95% lower bounds for precision and recall are about 0.896. These are in-sample diagnostics, not independent or held-out estimates of live accuracy.

On the same selected candidates, the legacy rank resolves 14 of 18 positive-priority comparisons correctly and ties four (77.8% strict accuracy); detailed ranking resolves 18 of 18 (100%). Tie-averaged nDCG@3 changes from 0.958 to 1.0. These small, authored groups test the intended rubric and do not establish general ranking superiority. The evaluator additionally reports true negatives, specificity, false-positive rate, balanced accuracy, Matthews correlation, source/language breakdowns and error IDs. It fails below 90% precision/recall/specificity or 80% positive-only pairwise accuracy, or on malformed selection output.

Regression tests cover evidence provenance, conservative negation/future filtering, repeated evidence, source withdrawal, transactional/idempotent backfill, ranking under ties and missing results, alongside the original crawler behavior. Rule v9 retains the most informative qualifying excerpt, then prefers the shortest equally informative text, within section boundaries and the 600-character bound. Existing stored excerpts can be rescored immediately; reevaluation is needed to recover richer source context and revisit candidates previously evicted under the old ranking. Real-world precision remains unverified.

Run reports record source coverage, fetched content, evaluated pieces, considered candidates, accepted observations, retained unique findings, rejection reasons, errors and the stopping reason. Coverage is bounded and is never described as exhaustive.

## Limitations

Rules miss unfamiliar wording, unsupported languages and important discoveries outside their implemented evidence patterns. Co-occurring statements can be misattributed or misinterpreted. Shared projects and translated names can remain duplicated without a common identifier. Static extraction excludes JavaScript-rendered material and external supporting sources. Short evidence windows and response limits can hide qualifications. Human review is needed before describing candidates as verified achievements.

The focused collector implements collection, storage, inspection and export. The separate `company-report` command now reads the focused database to select findings by company keyword overlap, fetch selected source pages as clean text, and request an Apertus report against the company requirements. JSON output preserves the shortlist and source text; optional Markdown includes canonical source links. Candidate IDs, source membership and verbatim quotations are validated, and two bounded Apertus checks per claim (entailment followed by an unsupported-clause audit) filter unsupported atomic claims. This model check does not independently establish truth or current service availability. Unreachable pages use labeled, dated retained excerpts where available. Offline tests cover matching, source reads and model-response validation; they do not establish the quality of a live Apertus report. Semantic vector search, a new frontend and hosted deployment remain separate from the focused database. Embeddings are not generated by focused collection or company reporting.

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

## Unified methodology update

A fresh rebuild adds experts and teams to the common cap of 700. Work acceptance criteria and evidence scoring are unchanged. The current `entities-v2` method weights contribution/expertise/results/application/recognition/collaboration at 25/15/25/15/5/15, using explicit role and own-activity evidence. Expertise distinguishes a research subject, a concrete method, a completed method-based resource and quantitatively validated methods. Immediate pronouns and first-person prose on an identified team's own page retain their verbatim attribution context; another subject or paragraph ends that context. Topic headings are not people, and research intended for clinical evaluation is not evidence that testing is complete. Ranking is `(selection_score, stable_id)`; company retrieval first compares matched keyword counts. No contacts are emitted, and no institutional or colleague achievements are automatically inherited.

On the frozen 700-record scoring comparison, teams increase from one to seven distinct scores and experts from four to seven. The source-linked assertions are refreshed from dated source text; IDs, work scores and the crawl queue are preserved. Four previously misclassified topic labels receive no person-role credit. The earlier 60-case development control retains its extraction results and within-type preference agreement, but positive cross-type strict agreement decreases from 78.54% to 74.41%. This is improved evidence differentiation within entity types, not demonstrated improvement of overall ranking accuracy. The entity/work scales still need independent calibration. See `data/entity-metrics-v2/comparison.json` for the paired results and `data/entity-metrics-v2/deployment.json` for the application to the sole working database.

The frozen 60-real-candidate development control set supplements the historical synthetic fixtures. Its labels precede the first unified scoring run; reports separate extraction precision/recall from within-type and between-type preference agreement. The dataset was reviewed by the implementing agent, not an independent human panel. Earlier synthetic ranking numbers above describe the previous implementation, not current calibration. See `data/unified/control60-evaluation.json` for the current measured results and failures.

The audited rebuild re-evaluates 1,088 fetched documents (12 fetch failures in 1,100 attempted URLs), accepts 935 unique candidates before trimming, and retains 700: 152 experts, 32 teams and 516 work findings. This selection is installed in the single working database, `data/focused.sqlite`, preserving its crawl queue; continued collection uses the shared 700-record cap. A smaller view is available through `highlights --limit 500`, without a second database. The rebuild's historical validation passed 189 automated tests. The real control set yields 44 true positives, 14 true negatives, no false positives and two false negatives (precision 100%, recall 95.65%). Strict pairwise agreement is 88.01% within types and 84.43% between types; for positive candidates only, these are 81.55% and 78.54%. The audited selection has 18 distinct scores and 99.29% of records share their score with another record, so the ID tie-breaker must not be interpreted as an evidence distinction. The provenance audit checks 7,521 quotation occurrences in findings and observations against the dated source snapshot, including scoring and retained link proofs, with no mismatches or contact details found. Local consolidation and audit results are saved in `data/single-database-migration.json` and `data/single-database-audit.json`; earlier database variants are recovery archives only.

The deliverables use the same `data/focused.sqlite` database for collection and company reporting, alongside the rating-validation report and a real CGM company report produced by Apertus under output contract version 2. Each candidate has its own JSON-Schema-constrained generation call, with at most one syntax retry. Entailment and a separate unsupported-clause audit must both accept each published claim. Truncated replies, duplicate keys and malformed JSON are rejected. This workflow uses REPORT_LLM_NAME independently of the legacy model; the local report model is apertus-v1-5-70b. Source excerpt IDs are resolved to exact quotations before validation. All published factual claims have verified source membership and verbatim quotations; unsupported claims are excluded.

The original CGM run had no surviving recommendations. Two candidate drafts were invalid JSON, so that historical run did not fully assess the shortlist. This is not evidence that Bern lacks suitable partners. The live three-claim verification control correctly rejects the old radar/CGM-accuracy error and a fabricated calibration service, but also rejects a supported ABBA statement. The semantic checker therefore remains a quality limitation. See `data/unified/validation-report.json` for the historical extraction/ranking results and those failures. The repair, repeated CGM output and expanded live controls are recorded separately in `data/unified/report-repair/validation-report.json`; earlier failed attempts remain in that folder for comparison. The final recheck reuses the five recorded live candidate drafts unchanged and makes fresh verification calls; its provenance identifies the original generation records. The frozen labels were assigned by the implementing agent before scoring; they are not independent human validation.


Final CGM repair check: 232 automated tests passed; all 32 recorded model responses parsed and passed their response schemas (five unchanged recorded generation replies, 27 fresh verification replies). The expanded live semantic control passed 24/27, with false acceptances C21/C27 and false rejection C22; the original ABBA control now passes. The output contains three provisional candidates and is explicitly marked `needs_review`, with automatic publication disallowed. The JSON failure is repaired, but semantic-checker reliability is not fully resolved. No claim of a complete semantic fix is made.
