# Pipeline review and plan

Oct 19, 2026. A full re-run of everything after the crawl (no crawling), a critical read of the outputs, and the plan from
here to a working end-to-end prototype and the submission. Raw outputs: [eval_2026-10-19/](eval_2026-10-19/).

## In one paragraph

The parts work one by one, but they are not one pipeline yet. On the rebuilt index (67,851 lines), the expert bench reaches
Recall@10 0.816. That passes the brief's 80% bar, but the 22 gold questions are all unchecked drafts, so the 95% range is
0.66–0.95. The company flow produced questions and queries for 8 test companies in 20–40 s each on Apertus 70B. Its answers
are weak: the top page is a good answer for 6 of 40 questions, partial for 20, and wrong for 14. The answer step labels 41
of 45 questions "clear", including all five questions of a crypto-mining negative control. Nothing yet turns retrieved
pages into the result the brief asks for: people, role, unit, why it matches, and source. That is the missing "report"
stage. Six agent workstreams (W1–W6, see [the workstreams](#the-six-agent-workstreams-and-what-they-cover)) are fixing
most of what this review found, and W1 builds that report stage. They have not landed yet, so this review measures the code as it was at the
checkpoint (`agents/base` = `f1f476e`, identical to main's working tree). What they don't cover is listed under
[Gaps no workstream covers](#gaps-no-workstream-covers).

## What was run

| Step | Command | Result |
|---|---|---|
| Parse raw HTML | `navigator pages` | +5,155 pages → 24,681 (6,391 parsed, rest too short or duplicate) |
| Cards | `navigator cards` | 10,042 people, 391 units, 57,728 page chunks from 18,761 pages |
| Embed | `navigator embed` | 67,851 lines (was 54,232): 14,632 new, 1,013 dropped, 53 s on the RTX 5050 |
| Expert bench | `navigator bench --label rebuilt-index-1018` | see below; saved in `bench/runs/` |
| Companies | `navigator company --as <kind> "<input>"` × 8 | queries.json per company, Apertus 70B via Keera |
| Company answers | `eval_companies.py` (Retriever + `answers.group_by_need`, and `Ranker.ask` per query) | `matches.json` per company + [companies_eval.md](eval_2026-10-19/companies_eval.md) |
| Near-negatives | 10 agent-drafted "plausible but not in Bern" queries vs the 0.85 floor | 3 of 10 answered anyway |

The previous index is backed up outside the repo; the old company outputs too.

## Results

### Expert bench (22 questions: 19 with an answer, 3 without)

| Metric | before-agents (old index) | rebuilt-index-1018 |
|---|---|---|
| Hit@3 | 0.579 | 0.632 |
| Recall@10 | 0.763 | **0.816** |
| MRR | 0.543 | 0.593 |
| nDCG@10 | 0.570 | 0.616 |
| Candidate recall@50 | 0.842 | 0.868 |
| No-answer accuracy | 1.000 | 0.667 |
| Paraphrase overlap | 0.209 | 0.209 |
| Median latency | 0.023 s | 0.033 s |

Read this critically:
- **The whole gain is one question.** `gnss-orbits` improved because new AIUB pages were crawled (Jäggi 23 → 1, Dach absent → 4).
  The other 21 questions rank exactly as before.
- **The no-answer floor has no margin.** "wholesale cryptocurrency mining hardware" now scores 0.851 against the cryptography group's
  theses page and passes the 0.85 floor. The lowest real answer scores 0.867, while the hardest near-negative ("industrial injection moulding")
  scores 0.865. A raw-cosine floor cannot separate these.
- **Wording still changes the answer** (brief criterion 2). The top 10s of questions with the same intent overlap by only
  0.21 (Jaccard). Sznitman ranks 3 for the EN question, 7 for the paraphrase and 2 for the DE one.
- **Units work, people don't.** 5 of the 6 unit questions have the answer at rank 1 (sequencing is 12th). Person questions miss
  Zysset entirely (his card is his CV from the BME master site) and Mougiakakou on all three DCB questions. They also rank Guenat 7th, behind
  five microscopy staff credited from one news page.

### Company flow: 8 test companies

Chosen to cover input types, sectors and one negative control:

| Company (input) | Needs | Template fallbacks | Ties found | Top answer: good / partial / wrong | Notes |
|---|---|---|---|---|---|
| Ypsomed (name) | 6 | 2 | 13 | 1 / 3 / 2 | "clinical study support" → forensic toxicology; training answers are right |
| Beyond Gravity (name) | 5 | 0 | 1 | 0 / 3 / 2 | misses the RUAG Space ties (W5 adds aliases) |
| lindt-spruengli.com (URL) | 5 | 2 | 13 | 2 / 2 / 1 | CDE cocoa projects are an excellent find; 5 of the first 6 ties are the anthropologist Angela Lindt |
| Lameness-detection startup (idea) | 6 | 2 | – | 0 / 4 / 2 | Vetsuisse surfaces only indirectly |
| Die Mobiliar (name) | 6 | 0 | **0** | 1 / 2 / 3 | Mobiliar Lab für Naturrisiken found by retrieval, but ties = 0 (bug); 3 needs are leaked prompt examples |
| CSL Behring (name) | 5 | 3 | 35 | 0 / 3 / 2 | home page HTTP 400; templates paste the whole summary sentence into queries |
| MRI/CT segmentation startup (idea) | 7 | 3 | – | 2 / 3 / 2 | ARTORG MIA, Sznitman, Reyes: the best result of the run |
| Crypto-mining hardware (idea, negative control) | 5 | 1 | – | should all be "not in data" | all 5 labelled **clear**; saved as `bern-economic-development-agency` |
| **Total (7 real companies)** | **40** | **13 of 45** | | **6 / 20 / 14** | |

"Good / partial / wrong" is one person's judgement of the top page per question, from
[companies_eval.md](eval_2026-10-19/companies_eval.md). Treat it as a starting point for the team's rating, not as gold.

By section, the pattern is clear:

| Section | Questions | Top answer quality |
|---|---|---|
| B/C units, expertise | 6 | 3 good, 2 partial, 1 wrong: the strongest sections |
| M talent | 3 | right answers (CAS/DAS/MAS, BME master, DDM courses) |
| F services | 8 | 6 wrong: "services for companies" pulls generic service pages (forensic toxicology, text editing, BWL) |
| H publications | 5 | none good: publications are not in the index (BORIS is harvested, 470 MB, but never embedded) |
| G tech transfer, K ecosystem | 15 | mostly partial: the right office pages appear, but often second, behind export-control FAQs or news |

The ranker's people lists, run on the same queries, give a plausible contact in the top 3 for roughly one question in three.
The rest are students, alumni, IT and admin staff, or people from unrelated institutes, credited because a page lists them.

### What works

- Collect → profile → needs → queries runs end to end on 70B in 20–40 s per company, with quotes for every profile item
  and a trace of every page read.
- When the data holds the answer and the query is good, retrieval finds it. Examples: Mobiliar Lab (+2.0 z), CDE's cocoa projects,
  ARTORG Medical Image Analysis, Unitectra, the Medical Faculty's CAS/DAS/MAS.
- Ties: "Bern pages that already name the company" is a strong, cheap signal (Ypsomed 13, CSL 35) and needs no LLM.
- Incremental pages → cards → embed takes about 2.5 minutes on new crawl data.

## What is wrong, ranked by impact

Each finding has its evidence, the fix, and who owns it. Wn = an agent workstream already doing it; **GAP** = nobody.

| # | Finding | Evidence | Fix | Owner |
|---|---|---|---|---|
| 1 | No step turns evidence into an answer | `company --retrieve` returns page chunks; `ask` returns people without reasons; `/search` runs the old BM25 path over pages.jsonl | One `pipeline.answer_need` used by CLI, API and bench; Apertus judge grades candidates with verbatim quotes; verdict found / partial / not_in_data | W1 |
| 2 | Confidence labels are meaningless | 41/45 "clear", 0 "weak"; crypto control 5/5 clear, with the run's highest margin (+2.02 z) | Verdict from the judge; without LLM, never "found" | W1, W2 |
| 3 | No-answer floor has no margin | 3/10 near-negatives and 1/3 bench negatives answered at 0.85 | Reranker relevance (opt-in) + judge | W2, W1 |
| 4 | Every www.unibe.ch page credits "CSH"; every Vetsuisse page credits "Veterinär-Anatomie" | `rank.py` `unit_of_source.setdefault`; CSH is in the unit list of nearly every company question | Attribute by host + longest path prefix; no unit credit from aggregator sites | W2 |
| 5 | Listing and news pages flood the people lists | DCB monthly archives and the MIC news page credit up to 8 people each; `Ranker` never applies the listing penalty | Listing penalty + no roll-up from listings and news | W2, W3 (page types) |
| 6 | Person cards are nearly empty | 88% of 10,042 cards have no expertise/research/projects text; 49% are under 15 words | Profile sections, group pages, BORIS publications into cards | W3 |
| 7 | Exact terms missed by dense search | Zysset: dense rank 513, BM25 rank 2 (W2's probe) | Hybrid dense + BM25 | W2 |
| 8 | Queries written as questions get dropped | 13/45 needs fell back to templates; raw 70B replies are "Which Bern institute …?" despite the prompt | Don't pass the question to the queries call; lint | W5 |
| 9 | Company never asks for people, units or projects | Sections chosen across 45 needs: A 0, B 2, D 0, F 8, G 8 | Always include A and B (C/D when there is a topic); let the LLM add the rest | **GAP** |
| 10 | Prompt examples leak into the needs | Mobiliar (insurer) got "clinical study services", "usability testing", "diabetes technology", all from `NEEDS_SYSTEM`'s Ypsomed examples; the K style example was copied verbatim ("…collaborates with Roche, Swisscom and the Insel Gruppe"); H queries name *Nature Biotechnology*, *The Lancet* | Examples from unrelated fields; a lint that flags queries sharing ≥5 words with an example | **GAP** (W5 changes only the queries prompt) |
| 11 | Ties miss the company's own short name | "Swiss Mobiliar insurance cooperative" → searched only that string ("Swiss" is a common word); 320 pages say "Mobiliar" | Aliases and distinctive tokens | W5 (add Mobiliar as a test case) |
| 12 | Idea inputs get wrong names and colliding folders | crypto idea → "Bern Economic Development Agency" (the profile prompt mentions the agency); MRI idea → "The startup (unnamed)"; old idea folders pile up | For ideas: slug from the idea text, name "Idea: …", drop the agency from the profile prompt | **GAP** |
| 13 | LLM calls have no retry | A network drop overnight: 6/7 needs of one company silently became templates | Retry on transport errors too (W1 retries 429/5xx), and print "n of m needs used templates" | W1 (partly) + **GAP** |
| 14 | Junk person names and groups | "Dr. med.", "med. vet.", "Coordination", "et phil. nat. Ruben Bill"; groups "S", "B", "." from A–Z headings; 76 title-only or one-word names | Name and group sanity rules in extraction and cards | **GAP** (W3 fixes reversed DCR names only) |
| 15 | Units named by their slug | 59 of 369: `crypto`, `cgg`, `muehlemann-dcbp`, `jobs` | Name from the site's title or header | **GAP** |
| 16 | Admin, IT and students rank as "contacts" | IT-Support, Administration Office, workshop head, MSc students in top 3 | A role class on each card (lead / researcher / staff / student / former); the judge prefers leads as the contact. Not a penalty: everyone stays findable | **GAP**, decision for the team (W2 dropped a junior penalty for fairness) |
| 17 | Publications aren't results | Section H answers are publication-list pages at best | W3 puts BORIS into person cards; publication results would be a later step | W3 (partly) |
| 18 | Pages never re-checked; dead links returned | 1,463 dead URLs; a person result links a 404 (both W6's findings) | Revisits, freshness, dead-link replacement | W6 |
| 19 | Small query bugs | "Bern-based" → "based publications"; template inserts the whole summary sentence when the lexicon has no topic | `PLACE_SUBS`; template guard | W5 (partly) |

## The pipeline end to end

| Stage | Command | State today | Main gap | Owner |
|---|---|---|---|---|
| Sources | `sources.json` + xlsx | 627 sites done, 1 blocked | adding a non-UniBE site to the net crawl doesn't register it | W6 |
| Crawl | `net run` | finished Oct 18 21:28; 10,042 people, 325 unit records | no revisits | W6 |
| Pages | `pages` | 24,681 | changed pages never re-parsed; net page types not read | W3, W6 |
| Cards | `cards` | 10,042 / 391 / 57,728 | empty person cards, site-sized units | W3, W2 |
| Enrich (Apertus) | `enrich` | never run; not connected to cards | the "semantic enrichment" step of the brief has no Apertus in it | decision |
| Embed | `embed` | 67,851 lines, e5-small | (bigger model only if W2's results ask for it) | – |
| Rank | `ask`, `bench` | Recall@10 0.816 | attribution, listings, hybrid, floor | W2 |
| Company → queries | `company` | works; 29% template fallback | sections, leakage, idea names | W5 + GAP |
| **Answer + report** | – | **missing** | judge, verdict, cards with reason and source; `answers.md` per company | W1 |
| Report rendering | – | `report.md` describes the questions, not the answers | an HTML/PDF per company for the agency and the demo | **GAP** |
| API | `uvicorn navigator.api:app` | `/search` = old BM25 | `/answer`, `/companies` | W1 |
| UI | – | three on branches, none on the new path | pick one, wire it | **GAP** |
| Evaluation | `bench` | 22 draft gold; no company gold | company suite, verdict metrics, gold lint | W4 + team |
| Deploy | – | none | Docker, runbook, air-gapped notes | W6 |
| Submission | `technical_report.md` | stub | report, deck, video | team |

## The six agent workstreams and what they cover

Plans and shared contracts live in the multi-agent session's scratchpad (`…/9a15f113-…/scratchpad/handoff/`). The lead merges in this order:
W3 → W2 → W1 → W4 → W5 → W6. As of Oct 19 07:45, none had committed yet. The lead adopted `rebuilt-index-1018` from this review as
the new baseline.

| Workstream | Builds | Covers findings |
|---|---|---|
| W1 | `pipeline.py` + `judge.py`: one answer path for CLI, API and bench; verdicts; cards with grade, quote, reason; `answers.json/md`; `/answer` API; LLM retry on 429/5xx | 1, 2, 3, 13 (partly) |
| W2 | Ranker v2: unit attribution, listing penalty, BM25 hybrid, dedupe, `ask_many`, opt-in reranker | 3, 4, 5, 7 |
| W3 | Person topics from profiles, group pages, BORIS and mentions; refined page types; email cleanup | 5, 6, 17 |
| W4 | Bench v2: company gold (15 questions), verdict metrics, traceability, success-criteria block, gold lint | evaluation |
| W5 | Company layer: one-thing questions, page-voice queries, aliases and typed ties, answerability, fallback contacts | 8, 11, 19 (partly) |
| W6 | Freshness: revisits, dead links, `refresh`, Docker, `Docs/operations.md` | 18 |

## Plan

### Step 1: land the workstreams, then measure again

Merge in the lead's order, then on main (commands per the workstream plans; check their final reports for changes):

```bash
export PYTHONPATH=src
python -m navigator pages && python -m navigator people && python -m navigator cards && python -m navigator embed
python -m navigator bench --label after-merge                      # experts suite, compare with rebuilt-index-1018
python -m navigator bench --suite company --label after-merge-co   # W4's company gold
python -m navigator.company.regen --all                            # W5: regenerate the companies
python -m navigator answer --all                                   # W1: answers.md per company
python Docs/eval_2026-10-19/eval_companies.py <out-dir> <company slugs…>   # the same view as this review
```

Pass condition: no lower than this review on Hit@3 and Recall@10; all 3 bench negatives refused again; the crypto control gets
`not_in_data` on every question.

### Step 2: close the loop for the demo

1. One path from question to result: `/answer` and `/search` both go through `pipeline` (W1). Retire `company --retrieve` and
   `answers.py`'s labels from anything user-facing; keep them as diagnostics.
2. **Report rendering (GAP).** From `answers.json`: one page per company. Start with existing ties, then each question with its
   verdict, the people and units with role, unit, reason and source link, and "not in our data, ask: …" where it applies.
   The same view serves the agency, the demo and the technical report's screenshots. HTML first; PDF from it if needed.
3. **UI (GAP).** Pick one of the three: Jordan's SvelteKit dashboard (auth, sources admin, Dokploy deploy, no search page yet),
   Niclas's static page on `feature/backend_optimisations` (old pipeline), or Trista's React app in `src/company_match/web`
   on origin/main. Wire it to `/answer` and `/companies/{slug}`. A free-text search box plus the company report page is enough for a 2-minute demo.

### Step 3: gaps no workstream covers

In order of value for the demo:

1. **Always ask for people and units** ([needs.py](../src/navigator/company/needs.py) `llm_needs` / `build_needs`): add A and B
   deterministically (C or D when the profile has a topic) and let Apertus add up to 5 more. This is the section the bench is
   good at and the brief asks for first.
2. **Neutral prompt examples** ([prompts.py](../src/navigator/company/prompts.py) `NEEDS_SYSTEM`, `PAGE_EXAMPLES`): examples from
   fields no test company is in, and a lint for copied example text. Regenerate Mobiliar to check.
3. **Idea inputs** ([company/\_\_init\_\_.py](../src/navigator/company/__init__.py), profile prompt): slug from the idea text, no agency
   name in the profile prompt, delete stale idea folders.
4. **Robust LLM calls** ([llm.py](../src/navigator/llm.py)): retry `httpx.TransportError` as well, and show the template-fallback
   count in the company summary.
5. **Clean person and unit names** (person extraction in `net/`, [cards.py](../src/navigator/cards.py)): drop title-only names,
   strip leading degrees ("et phil. nat."), ignore single-letter group labels, name slug-only units from the site title.
6. **Role class on person cards**, so the judge and the UI can say "contact: group head" and still list everyone (team decision, see below).
7. **Apertus in the enrichment stage** (team decision): one call per unit to write "what this group does and for whom" from its
   own pages, with the same verbatim-quote check the profile step uses. This strengthens the "purposeful use of AI" criterion
   and fixes thin unit cards.

### Step 4: evaluation the team has to do by hand

- Check the 22 expert gold answers (all `draft`) and W4's 15 company gold questions: open the source, confirm, set `checked`.
  Our 0.816 is not a result until this is done.
- Rate the company answers after the merge: good / partial / wrong per question, starting from the table above, 2 raters if possible.
- Confirm the two near-negatives the agents flagged ("GMP cleanroom manufacturing", "injection moulding") really have no Bern answer.

### Step 5: submission

- **Blocker before the repo goes public:** commit `d4149e4` pushed 3,775 raw HTML pages with staff names, emails and phones (W6 found
  it). Purge the history or submit from a fresh repo. This needs a human decision.
- **Sovereignty:** origin/main's `src/company_match/llm_client.py` has a fallback to Kimi (api.moonshot.ai), a foreign closed service.
  That conflicts with the brief's sovereign-deployment criterion; remove it or keep it off by default.
- Reconcile origin/main's `company_match` (Trista's collaboration scoring and Ollama web enrich) with `company/` and W1's pipeline.
  There should be one company flow in the demo.
- Technical report (≤6 pages, PDF): architecture, the bench and company evaluation with honest ranges, traceability numbers,
  costs, deployment. `technical_report.md` is still the template.
- Pitch deck (≤10 slides) and a demo video (≤2 min): one company end to end, one free-text question, and one "not in our data" answer.

## Decisions for the team

1. Which UI goes into the demo.
2. Whether person cards get a role class and the judge prefers leads as contacts (fairness: everyone stays findable, only the
   "who to call" line changes).
3. Whether Apertus runs an enrichment pass on unit pages (cost: about one call per unit, ~400 calls).
4. The reranker: W2 keeps it opt-in because both candidate models were trained partly on MS MARCO (non-commercial terms).
5. History purge vs fresh repo for the public submission.
6. 8B vs 70B per step: W1 found the 8B judge over-generous and the 70B discriminating (3.6 s per need).

## How to rerun this evaluation

```bash
export PYTHONPATH=src
python Docs/eval_2026-10-19/eval_companies.py /tmp/eval ypsomed-holding beyond-gravity lindt-sprungli \
  bern-lameness-detection-startup swiss-mobiliar-insurance-cooperative csl-behring the-startup-unnamed bern-economic-development-agency
```

It needs the companies' `queries.json` in `data/companies/` and writes `companies_eval.md` (pages per question, the ranker's people
and units, near-negative floor check) plus a `matches.json` per company. Company inputs used here:
`Ypsomed`, `Beyond Gravity`, `https://www.lindt-spruengli.com`,
`startup in Bern that detects lameness in dairy cows with cameras and AI`, `Die Mobiliar`, `CSL Behring`,
`startup building AI software that segments MRI and CT scans to plan orthopaedic surgery`,
`wholesale supplier of cryptocurrency mining hardware`.
