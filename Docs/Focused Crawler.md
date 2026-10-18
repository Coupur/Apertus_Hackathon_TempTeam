# Focused Crawler: High-Value Bern Research Highlights

The collector uses local rules to keep up to 500 research candidates across the University of Bern ecosystem, ARTORG, and Diabetes Center Berne. It is not an exhaustive university catalogue. All authored summaries, rationale, CLI output, and documentation are English. No model endpoint, API key, prompt or GPU is required. Proper names and verbatim source excerpts retain their original language.

The collection objective is to traverse the eligible reachable pages across all three source groups and retain the best 500 candidates by the implemented ranking. Use `--complete` for this workflow. A bounded 2,000-request run remains available for sampling. The broader selector includes substantive research alongside stronger achievements; it never creates records or inflates scores to fill the ceiling.

## Source boundaries

The registry comes from `Docs/unibe_sous_domaines_publics_etendus.xlsx`, with canonical ARTORG and DCB entries. `src/sources_discovered.json` and arbitrary additions to the bulk crawler's extra-source configuration are not imported. ARTORG and DCB entries are deduplicated by host.

Allowed hosts are exact inventory hosts plus ARTORG and DCB, treating `www.` and bare-host spellings as aliases. This does not permit arbitrary `*.unibe.ch` traversal. `--only` restricts both starting sources and allowed hosts for that run. Omitting it restores the full original inventory.

Every request and redirect destination is checked before fetching. Robots rules apply to the actual destination origin. Missing robots files (404/410) permit access; unavailable, forbidden, or HTML error responses fail closed for the run. Declared integer crawl delays longer than the configured minimum are respected. External references may be stored but are never fetched.

The collector reads HTML and DCB's same-domain WordPress `project`, `publication`, `posts`, and `pages` endpoints, with 20 items per API request. Items retain both public page and actual API retrieval URLs. An API item without substantive body content queues its public page; long titles and publication timestamps do not count as body content. No bulk BORIS, external publication API, PDF download, OCR, browser rendering, or full-text harvesting runs in this mode.

## Traversal and budgets

Source homepages are surveyed first. Research, project, achievement, service, news, and archive links are prioritized using URL, anchor text, surrounding context, and parent title. Concrete outcome and facility links receive higher priority; calls, newsletters and event announcements receive lower priority. DCB projects and news are surveyed before publication metadata. Old archives remain eligible; there is no date cutoff or recency bonus. Navigation pages can lead to useful content without qualifying as findings.

Subject keywords in the anchor or URL add a bounded priority bonus, with medical subjects favored over general science. This changes discovery order, not source boundaries, eligibility or finding scores. A medical institution name or parent page alone does not add the subject bonus. Complete runs still visit all eligible links; already queued URLs retain their saved priorities when resumed.

Routine jobs, teaching, privacy, search, and administrative content is filtered inexpensively. Other substantive pages are evaluated locally using English and German signal patterns, yielding zero, one or several unreviewed candidates. Full downloaded text exists only in memory. Source checks visit homepages without candidate selection or frontier expansion.

| Setting | Default | Meaning |
| --- | --- | --- |
| `--max-fetches` | 2,000 | Content requests, including failures and redirect hops |
| `--max-findings` | 500 | Retained findings; configurable from 1 to 500 |
| `--concurrency` | 4 | Concurrent HTTP requests; frontier batches use distinct domains |
| `--delay` | 1 second | Minimum request spacing per normalized domain |
| `--max-depth` | 8 | Traversal depth; API pagination does not increase depth |
| Frontier bound | 10,000 URLs | Stronger queued links replace weaker ones at capacity |
| Response bound | 2 MB | Decoded response bytes per request |
| Document bound | 36,000 characters | Overlapping 12,000-character evaluation pieces |

`--complete` removes the content-request, depth and frontier ceilings. It follows every eligible in-boundary HTML link, including low-priority navigation links, until no eligible queued URL remains. The URL exclusions for jobs, teaching, search, calendars, administrative content and downloads still apply. Robots, redirects, request pacing, concurrency and per-response limits remain enforced. Reaching 500 records never stops the crawl.

In complete mode, discovered and in-flight URLs are saved before the next fetch batch. Successful URLs are marked with a traversal/rules version, allowing an interrupted run to resume without fetching them again. Failed requests and evaluations are retried on the next invocation. `--reevaluate` starts a new pass over previously completed URLs. Compact URL state is not pruned in complete mode; it may grow with the sites, while the finding count stays capped at 500. A run can take hours or longer depending on the reachable pages and source response times. Exhausting this frontier does not imply that hidden, blocked or unlinked content has been discovered.

Robots requests are separately counted and cached per origin for the run. Redirect chains permit at most six requests. A failed source does not stop other sources. There is no automatic retry loop; later runs retry reachable failures. Reaching 500 findings does not stop collection: stronger findings can replace weaker ones.

Run from the repository root with `PYTHONPATH=src`:

```text
python -m navigator focused-crawl --source-check
python -m navigator focused-crawl --complete --report data/focused-complete-run.json --export data/highlights.json
python -m navigator focused-crawl --only artorg dcberne --max-fetches 150
python -m navigator focused-crawl --reevaluate --report data/focused-run.json
python -m navigator highlights --limit 20
python -m navigator highlights --min-score 3 --limit 20
python -m navigator highlights --organization "University of Bern" --out data/unibe-highlights.json
```

`LLM_BASE_URL`, `LLM_NAME` and `LLM_API_KEY` are not read by focused selection. Source-check mode is enabled only by `--source-check`; ordinary collection works without a model. The former `--max-model-calls` option has been removed. Content fetch, depth, response-size and frontier budgets bound the work.

With `--report` or `--export`, atomic JSON snapshots are updated approximately every 30 seconds during traversal and once at the end. A live report has `stopping_reason: running` and no `finished_at`. Interrupted complete runs preserve their pending queue. A complete run reports null request, depth and frontier limits.

## Selection and evidence

The versioned selector is in `src/navigator/focused/rules.py`. The strict record schema and verbatim-evidence gate are in `models.py` and `selection.py`.

Rules look for combinations of concrete facts within a short local passage:

At priority **2**, a substantive candidate can qualify through:

- A reported research finding or analysis with a concrete subject, without requiring a clinical trial or numerical effect size.
- A research project or activity with a defined objective or method. Aims remain aims; they are not described as completed achievements.
- A developed technology or method with a described function, without requiring a license or commercial deployment.
- An available scientific method, instrument or research service, without requiring exceptional uniqueness or external adoption.

At priority **3**, the stronger evidence rules remain:

- A controlled or prospective comparative study, a reported outcome and quantitative evidence.
- An identifiable technology or research output with documented adoption or transfer.
- A specified capability, validation or standardization, and external access or use.
- A national or multicenter program with reported funding of at least ten million.
- International prize recognition with a concrete scholarly output.
- A named national or competitive European research program with a confirmed leadership role or funding award.
- A facility offering at least two specific advanced laboratory or clinical capabilities in the same section.

HTML extraction preserves inline sentences and heading boundaries, uses the main heading as the focused title, removes sidebar and related WordPress grid cards, and respects declared character encodings. Links in those cards remain eligible for traversal. Evidence windows remain within a section and select the shortest sufficient excerpt. A future plan in a separate sentence does not invalidate an existing documented capability. Headings and explicit project names provide record identities; arbitrary runs of capitalized words do not. Detail-page subsections describing the same work share its identity. Generic funding portfolios remain traversal pages.

Routine announcements, marketing alone, metadata-only publication cards and unsupported achievement claims do not qualify. General homepages and employee directories only qualify under the stronger rules, preventing broad institutional introductions from filling the shortlist. Broad evidence requires a descriptive passage with a sentence, at least 120 characters and 18 words. There is no publication-date cutoff, recency bonus or institutional quota. A budget ceiling is not a goal to fill.

Scientific, practical and capability scores remain separate on a 0–4 schema. The selector assigns **2 for substantive evidence, 3 for stronger evidence and 0 for unmatched dimensions**. Acceptance requires at least one dimension of 2 or higher and supporting excerpts. Zero means that no implemented rule qualified that dimension, not that the work has no value. The selector does not automatically assign exceptional scores of 4. These are heuristic review priorities, not independently verified significance assessments. `highlights --min-score 3` filters the stronger shortlist; the default includes both levels.

Every record contains `selection_method: rules`, `review_status: unreviewed`, stable `matched_rules`, English template explanations and verbatim source evidence. English titles describe the matched signal and organization; `original_name` preserves the source name. Template summaries do not translate or paraphrase the underlying research. Read the excerpts to see the actual source claims. Names, contacts and dates that cannot be reliably extracted remain empty or unknown.

### Medical and scientific keywords

`type` describes the record kind and `organizations` its affiliation. The existing `topics` retain selection labels such as "Research project or activity". The additional `keywords` list describes subject matter, using an English/German vocabulary in `src/navigator/focused/keywords.py` with canonical English labels. Its medical coverage includes diseases and specialties (type 1/2 diabetes, oncology, cardiology, neurology), diagnostics and devices (continuous glucose monitoring, MRI, biosensors), treatment (surgical robotics, immunotherapy, drug delivery), and research methods (genomics, organ-on-chip, clinical trials, biostatistics). Other scientific fields remain supported.

Keywords come only from each finding's original name and retained evidence, never from template summaries, unrelated page sections, institution names or source hosts. Up to 24 unique terms are retained, preferring title matches, medical concepts and multiword terms. An empty list means no vocabulary match; no fallback subject is invented. Tags describe mentions, including proposed research, and do not establish clinical efficacy, current service availability or a successful outcome. Vocabulary matching is heuristic and is not a medical ontology or semantic review.

New observations and merged findings are tagged automatically. Replacing or withdrawing source evidence recomputes keywords so unsupported old tags disappear. Collection startup refreshes existing stored findings and observations; source-check mode does not. Refresh existing data without any network request:

```text
python -m navigator refresh-keywords
python -m navigator highlights --keyword "CGM" --json
python -m navigator highlights --keyword "diabetes" --keyword "clinical trials" --out data/diabetes-trials.json
```

`--keyword` accepts canonical labels or recognized English/German aliases, for example `CGM` or `Typ-1-Diabetes`. Repeating it requires all requested concepts. Refresh is transactional and idempotent; it preserves IDs, scores, evidence, crawl progress and all other record fields. It updates SQLite; use `highlights --out` to refresh a static JSON export. Restart an already running collector to load changed code and vocabulary. Read-only inspection does not backfill old databases.

Strict validation checks field types, source-grounded identity, exact excerpts after whitespace normalization and evidence coverage for each selected dimension. It establishes provenance, not truth or semantic entailment. Quoted claims, negation, ambiguous subjects and unsupported languages can still fool or evade rules.

Status supports `active`, `completed`, `historical` and `unknown`. The current rules extract explicit completion statements and their dates; other statuses remain unknown. A publication timestamp is never assumed to be a study date or proof of current activity.

## Persistence, updates, and export

The default path is `data/focused.sqlite`; change it with `NAVIGATOR_DATA_DIR` or `--db`. Existing bulk data is not deleted or migrated. The legacy search and API do not read the focused database.

SQLite contains findings, identity keys, bounded accepted observations, URL state, and the latest ten run reports. It stores neither raw HTML nor full rejected texts. URLs, hashes, and evaluation status are compact crawl metadata; bounded runs keep the latest 10,000 URL states, while complete runs retain all URL states for reliable resumption. A finding retains at most eight source observations and twenty evidence excerpts.

Identity matching uses explicit identifiers, or normalized original names with the same unit and source. Record type is not part of the identity: a project description and a later research result about the same named work can merge. Existing databases receive the current identity keys when opened for collection. The storage layer preserves DOI punctuation. The current rules extract explicit project acronyms, NCCR names and labeled project or grant IDs from evidence; they do not infer a DOI from an unrelated page reference. Generic rule-authored titles are not identity keys. Distinct named findings on a page can remain separate. Cross-source duplicates require a shared identifier; ambiguous paraphrases or differently translated names may remain separate. Duplicate mentions add no ranking points. Rank uses the highest dimension, then the total dimension score, then a stable identifier; neither age nor mention count breaks ties.

Repeated runs revisit seeds and remaining queued links. Unchanged, successfully evaluated documents skip rule evaluation unless `--reevaluate` is supplied. Successful evaluations replace source observations and withdraw findings no longer supported by that source; independent supporting observations remain. Network, parsing, and selection failures do not withdraw findings. Source-check mode never changes findings. Evicted or unreachable findings cannot be reconstructed from a raw archive because none is kept; use `--reevaluate` for a fresh selection pass.

`highlights --json` or `--out PATH` exports:

- Envelope: `schema_version` (2), `language`, `count`, `findings`, `last_run`, `exhaustive`.
- Finding: `id`, `title`, `original_name`, `selection_method`, `review_status`, `matched_rules`, `type`, `organizations`, `unit`, `summary`, `rationale`, `scores`, `topics`, `keywords`, `experts`, `identifiers`, `date`, `status`, `status_quote`, `source_ids`, `source_urls`, `external_references`, `fetched_at`, `evidence`. `keywords` is an additive field in schema version 2; older exports may omit it. A separately updated status also has `status_source_url`.
- Evidence: `quote`, `supports`, `source_url`, `retrieval_url`, `fetched_at`.

Inspection opens SQLite read-only and does not create a missing database. ARTORG findings may belong to both ARTORG and University of Bern while remaining one stored record, so group counts need not sum to the total.

Reports distinguish documents, rule evaluations, selected candidates, accepted observations, and retained unique findings. They include candidate rejection counts/reasons, source coverage, API page fallbacks, errors, truncated documents, pending URLs, limits, and a stopping reason. `selection_threshold` states the minimum accepted score; `retained_by_priority` counts `high_priority` and `substantive` findings. `exhaustive` is always false. A successful source check with zero findings is not a completed scientific evaluation.

## Tests and evaluation

```text
python -m unittest discover -s tests -v
```

Tests cover source boundaries, redirects, robots failures/pacing, concurrency, budgets, evidence gates, the 500-record cap, multiple findings per page, language duplicates, joint projects, historical results, unchanged pages, source updates, API pagination, and absence of raw/rejected-text storage. Regression tests also cover heading boundaries, inline markup, declared encodings, prospective clinical comparisons, existing facilities alongside future plans, metadata-only API items and repeated project names. Injected selectors verify persistence mechanics; real local rules are also exercised without network or model access.

`bench/focused_examples.json` contains 30 manually authored and labeled **synthetic** examples, ten per source group, with strong positives and difficult negatives. They are fictional and must not be presented as institutional facts or inserted into the production database.

Run the deterministic benchmark locally, without an endpoint:

```text
python -m navigator.focused.evaluate --out data/focused-evaluation.json
```

This measures example-level selection after evidence validation, reports precision and recall, and exits unsuccessfully if precision is below 90%, no findings are accepted, or invalid selection output occurs. Synthetic precision is a rubric diagnostic, not a substitute for manual review of individual live findings across all three groups.

Limitations include bounded coverage, static HTML only, truncation, conservative identity matching, inaccessible sources, unavailable external verification, and rule misclassification. The database contains candidates for review, not an independently verified ranking of scientific impact. The rules cover a subset of evidence styles; valuable discoveries in any discipline can be missed. They cannot reliably resolve every shared project or translated name without common identifiers.
