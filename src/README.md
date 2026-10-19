# Research & Expertise Navigator — code

## SvelteKit interface

The SvelteKit and Bits UI interface lives in `src/routes`. Sign in by email to
open the research dashboard; use **Admin** in the top navigation to add, edit,
or remove website sources. The three starting sources are the University of
Bern website, ARTORG, and Diabetes Center Berne. The supplied University of
Bern subdomain inventory adds more sites to the same registry.

Run it from the repository root:

```sh
npm install
npm run dev
```

Set `RESEND_API_KEY` in the ignored root `.env` file. Optionally set
`RESEND_FROM_EMAIL` to a verified sender address and `ORIGIN` to the public
HTTPS origin used in sign-in links and by SvelteKit behind the reverse proxy. The default sender
`onboarding@resend.dev` is suitable for Resend testing; sending to arbitrary
recipients requires a verified sending domain.

Run `npm run check` for Svelte and TypeScript diagnostics, or `npm run build`
to create a production build. Magic links expire after 15 minutes and are
single-use. Verified sign-ins use HTTP-only session cookies. Auth and
admin-managed website sources are stored in the ignored `.data/auth.sqlite`
SQLite database. The Python source registry reads active website sources from
the same database, so additions are available to `python -m navigator sources`
and the crawler. Production deployments need persistent storage for this
database.

The dashboard includes cards for crawled pages, indexed pages, discovered PDF
links, and downloaded PDF files. These remain at zero until an analytics
backend is connected; the frontend does not infer metrics from local crawl
artifacts.

## Deploy with Dokploy

Deploy this repository with the Docker Compose builder using
[docker-compose.yml](../docker-compose.yml). Route the `web` service to
container port `3000`. Set `ORIGIN` to the public HTTPS origin; Compose passes
it at build time for SvelteKit's CSRF origin check and at runtime for magic-link
URLs. Provide `RESEND_API_KEY` and `RESEND_FROM_EMAIL` as Dokploy runtime
environment variables. Do not bake secrets into the image.

The Node adapter is configured to use the proxy's `X-Forwarded-Host` and
`X-Forwarded-Proto` headers when validating POST origins. Keep the app behind
Dokploy's trusted proxy rather than exposing the container port directly.

The Compose file mounts the named `app-data` volume at `/app/.data`, so SQLite
users, sessions, and source settings survive container replacement. If
replacing it with a host bind mount, make sure the directory is writable by
the container's `node` user (UID `1000`).

The Docker image runs the SvelteKit interface only; the Python crawler and API
are not started by this container.

## Navigator backend

### Implemented workflows

The commands below are separate workflows. Having search code in the repository does not mean its input data or model endpoint has been prepared.

| Entry point | Reads | Selection and output | Apertus |
| --- | --- | --- | --- |
| `focused-crawl`, then `highlights` | Source websites, then `data/focused.sqlite` | Local rules collect research candidates; `highlights --keyword` filters their subject tags and exports `findings` JSON. Ranking reflects evidence criteria, not relevance to a company. | Not used |
| `company-report company.json` | Company JSON and `data/focused.sqlite`, then selected source URLs | Keyword overlap selects findings; source HTML becomes clean text; a report evaluates the company's requirements against the selected evidence. Saves JSON and optionally Markdown. | Generates the report, except with `--prepare-only` |
| `search`, or HTTP `POST /search` | `data/profiles.jsonl` and `data/vectors.npy`, built from pages and enriched records | Vector similarity retrieves person and unit profiles; results use the `SearchResponse` contract. | When configured, rewrites the query and judges matching units; otherwise similarity ranking is returned. |
| `search-legacy`, or HTTP `POST /search/legacy` | `data/pages.jsonl`, plus optional `data/entities.jsonl` | BM25 retrieves pages from the company need and keywords; pages are grouped into units. | When configured, expands the query and filters candidates; without it, keyword matches are returned. |
| `embed`, then `retrieve` | `data/pages.jsonl`, then `data/index/` | A separate embedding model compares company queries with page chunks and returns similarity-ranked `matches` JSON. | Not used |

`search` and `retrieve` do not read `focused.sqlite` or its `highlights.json` export. There is no automatic hybrid search or handoff from `retrieve` to Apertus. Use `company-report` for company matching and reporting over focused findings.

For behavior, see the [CLI dispatch](navigator/__main__.py), [focused commands](navigator/focused/cli.py), [company reports](navigator/focused/company_report.py), [profile search](navigator/search.py), [legacy BM25 search](navigator/legacy_search.py), and [chunk retrieval](navigator/retrieve.py). The [bulk collection technical plan](../Docs/Bern%20Data%20Collection%20%E2%80%93%20Technical%20Plan.md) is a historical design, not a description of the complete current implementation.

## Focused research highlights

The focused workflow uses one working SQLite database, `data/focused.sqlite`, with **at most 700 findings**, including experts and teams, from the supplied University of Bern inventory, ARTORG, and Diabetes Center Berne. Collection, highlights and company reports all use this same database by default. Local rules select concrete significance signals and retain English explanations, short source excerpts and URLs. No model server, API key or GPU is required. Candidates are marked `selection_method: rules` and `review_status: unreviewed`.

The portal list is [Docs/unibe_sous_domaines_publics_etendus.xlsx](../Docs/unibe_sous_domaines_publics_etendus.xlsx), stored in `Docs/`. Both crawlers automatically load all 42 sites from this workbook, including ARTORG and Diabetes Center Berne. Run without `--only` to include the entire inventory; `--only` restricts the run to the named source IDs. The bulk crawler also includes configured extra and discovered sources.

The broader selection includes substantive findings, projects, technologies and services at priority 2, and stronger evidence at priority 3. Complete collection traverses the eligible reachable content of all source groups and retains the highest-scoring 700 collected candidates. Use `highlights --min-score 3` to inspect only the stronger subset.

From the repository root in PowerShell:

```powershell
pip install -r src/requirements-focused.txt
$env:PYTHONPATH = "src"

# Optionally check every inventory homepage without selecting findings.
python -m navigator focused-crawl --source-check

# Collect across all inventory portals with deterministic local rules.
python -m navigator focused-crawl --complete --report data/focused-complete-run.json --export data/highlights.json

python -m navigator highlights --limit 20 --explain
python -m navigator highlights --organization "ARTORG" --out data/artorg-highlights.json
python -m navigator highlights --json

# Inspect the fixed project vocabulary (no database required).
python -m navigator keywords --json

# Reapply that vocabulary to subject tags from stored evidence.
python -m navigator refresh-keywords
python -m navigator refresh-evaluations
python -m navigator highlights --keyword "CGM" --json
python -m navigator highlights --keyword "oncology" --keyword "genomics" --json
```

On POSIX shells, use `export PYTHONPATH=src`. Python's standard-library SQLite implementation is used; no database server is required.

HTML is converted to plain text temporarily. Only selected structured facts, excerpts and compact crawl state persist in `data/focused.sqlite`; `highlights --out` exports JSON. Rules prioritize material for review and do not independently verify scientific importance or translate source text. `LLM_*` environment variables have no effect on focused collection.

The fixed project vocabulary is [keyword_vocabulary.json](navigator/focused/keyword_vocabulary.json), version `keywords-v1`: 136 canonical terms with English/German aliases. It changes only through explicit repository edits and version increments; crawling and refresh do not add terms. `navigator keywords --json` exposes the catalog for UI filters. Per-finding tags can still change when their evidence changes.

Findings include subject `keywords` with detailed medical coverage: diseases, specialties, diagnostics, therapies, devices and research methods. English/German terms map to English labels. Tags derive from the original name and supporting excerpts; they describe mentions, not verified clinical efficacy. They are separate from `type`, `organizations` and the existing selection-rule `topics`. New and merged results are tagged automatically; explicit refresh commands can retag old records, while new unified fields require re-reading sources. Keyword filters accept aliases such as `CGM` and `Typ-1-Diabetes`; repeated filters require all terms. Medical subject terms also receive a bounded bonus when prioritizing newly discovered links.

See [the medical keyword sample](../bench/medical-keywords-smoke.json) for output from a small live test on October 18, 2026: five pages produced seven records, with no traversal of discovered links. The sample retains names, keywords, evidence excerpts and source URLs. Local databases and crawl output stay under the ignored `data/` directory.

Candidates also carry seven evidence criteria: methodology, quantitative evidence, validation, adoption, accessibility, collaboration and reproducibility. Their weighted 0–100 score orders works alongside the separately scored entities; each nonzero criterion includes a source assertion and URL. This is a heuristic evidence score, not a probability or verified impact. `highlights --explain` displays the breakdown. `refresh-evaluations` backfills existing excerpts without network requests. The offline evaluator now covers 54 synthetic development cases, classification error rates and ranking quality.

See [the focused workflow guide](../Docs/Focused%20Crawler.md) for limits, selection rules, persistence, the export contract, and evaluation. The focused commands do not call the legacy publication harvester, PDF downloader, vector index, company search, or HTTP API.

## Company JSON to a report over focused findings

Use [company-request.example.json](../bench/company-request.example.json) as the input example. It is fictional. `keywords` must be a nonempty array of strings; also supply `need`, `requirements`, or `goals`. Optional fields include `company_name` and `report_language` (default `English`). Additional JSON fields are retained as company context for Apertus.

Configuration loads automatically from the repository-root `.env`, which Git ignores. Copy [`.env.example`](../.env.example) to `.env` if it does not exist, then enter the team API key locally. The template uses the CSCS Keera gateway and `apertus-v1-5-8b`. Existing environment variables take precedence over `.env`; values in the file are not expanded as shell variables. Keep actual credentials out of tracked files. Install `src/requirements-focused.txt` to include the configuration loader.

```powershell
$env:PYTHONPATH = "src"

# Inspect the shortlist and fetched text before configuring the model.
python -m navigator company-report bench/company-request.example.json --prepare-only --out data/company-context.json

# Generate the report using the credentials in your local .env.
python -m navigator company-report bench/company-request.example.json --out data/company-report.json --markdown-out data/company-report.md
```

The implemented sequence is:

1. Read the selected database without modifying it. Match the existing keywords and EN/DE aliases. Count concepts once, then sort by `(keyword_match_count, selection_score, stable_id)`, descending.
2. Select 5 findings by default; `--top-k` accepts 1–10. There are no institution or type quotas.
3. Read up to three permitted pages per finding: prefer a work's own detail pages over multi-article catalogues; for people/teams include significant-work evidence and a profile page. Clean contact lines, select exact windows on natural text boundaries, and share a total source budget of 60,000 characters. `--source-chars` remains 1500–6000 per page. Failed refreshes use only that source's dated retained excerpts.
4. Apertus proposes atomic claims: fit, competencies, related projects, infrastructure, services, experts/teams with roles, and supported requirements. It selects source excerpt IDs; code inserts their exact text as citations. Direct quotations are also checked. Database IDs, names, affiliations and scores are injected by code.
5. Validate the schema, candidate/source membership, verbatim quotations, explicit named roles and absence of contacts. Check each claim in isolation: an Apertus entailment decision must pass, then a separate evidence audit must find no unsupported clause. Neither stage may accept for the other. A project can evidence research experience; an ongoing study is not a completed trial, and joint involvement is not sole authorship. Exclude unsupported assertions and omit a candidate if no fit claim survives. These checks are not a truth guarantee.
6. Render JSON and Markdown from the same verified result. Contract version 2 contains structured recommendations, score breakdowns, original company input, gaps and a verification audit. Unknown information stays empty; gaps are the original requirements not confirmed by a surviving claim.

`--prepare-only` writes `status: prepared` without calling Apertus. Generation requires `LLM_BASE_URL` and an endpoint supporting `response_format: json_schema`. Each candidate receives an isolated, schema-constrained request; only that candidate's excerpt IDs are allowed. An invalid or truncated response gets at most one syntax retry with the same evidence constraints. Duplicate JSON keys, non-JSON numbers and unfinished completions are rejected rather than repaired. Individual malformed or unattributed facts are logged and excluded before semantic checking.

`REPORT_LLM_NAME` selects the company-report model independently of legacy `LLM_NAME`; if omitted it falls back to `LLM_NAME`. The validated local setup uses `apertus-v1-5-70b` for this workflow. Generation allows 2000 output tokens per call, and the entailment call allows 1400 and the separate audit allows 700. Both checkers judge the exact assertions, with paired examples distinguishing joint participation from sole conduct. Only the concise decision and reason enter the report. At most two generation calls per candidate are allowed; each of at most 60 claims gets one entailment call and, only if supported, one audit call. With up to two additional claims plus one fit per candidate, the normal maximum is `8 * top_k` calls including all syntax retries. Source text stays within 60,000 characters, individual generation inputs within 120,000, and the combined claim verification input within 100,000.

An empty shortlist returns `no_matches`; absent evidence or no surviving fit claims returns `insufficient_evidence`. Generation failures and rejected claims are recorded without publishing unchecked facts. Unhandled endpoint errors preserve the prepared JSON. JSON and Markdown use the same accepted claims and original requirement gaps.

This workflow uses the collected Bern inventory, which is not an exhaustive list of options in the canton. No embeddings or bulk `pages.jsonl` corpus are required. `POST /search` remains the separate legacy endpoint; this workflow is exposed by the `company-report` CLI and Python module.

## Legacy bulk collection and company search

```
Company request ──► 1. understand (Apertus: need → terms + EN/DE synonyms)
                    2. retrieve   (BM25 over crawled + enriched pages)
                    3. judge      (Apertus: keep relevant units, write reason)
                 ──► SearchResponse (units, people, expertise, infra, reason, source URLs)

Offline archive pipeline:  sources → crawl-raw → data/raw/ → pages → data/pages.jsonl
                                                        └─► enrich → data/entities.jsonl
```

### Existing and archive workflows

```bash
pip install -r src/requirements.txt
export PYTHONPATH=src
export LLM_NAME=swiss-ai/Apertus-v1.5-8B LLM_BASE_URL=http://<host>:8000/v1 LLM_API_KEY=...
# or: cp .env.example .env and add your Keera key (CSCS-hosted Apertus; loaded automatically, gitignored)

python -m navigator sources                          # list the 42+ configured sites
python -m navigator crawl --only artorg dcberne inf      # direct clean-page collection
python -m navigator crawl-raw --only artorg dcberne inf  # archive raw HTML for offline processing
python -m navigator pages                                # raw archive -> pages.jsonl
python -m navigator enrich                               # optional: Apertus structured extraction

```

Four steps, one file each in [navigator/](navigator/):

| Step | File | In → out |
|---|---|---|
| 1. crawl | `crawl.py` | websites from `sources.json` + the UniBE inventory → `data/pages.jsonl` (clean text per page) |
| 2. enrich | `enrich.py` | Apertus reads each page → `data/entities.jsonl` (unit, people, roles, expertise, projects, infrastructure, EN/DE synonyms) |
| 3. index | `index.py` | per-page records → one profile per person and per unit, embedded → `data/profiles.jsonl`, `data/vectors.npy` |
| 4. search | `search.py` | Apertus rewrites the need → similarity search over profiles → Apertus keeps the units that fit and says why |

`api.py` serves the web page (`static/index.html`) and `POST /search`. `llm.py` talks to any
OpenAI-compatible Apertus endpoint; `models.py` is the request / response contract.

### Four-step profile pipeline

Python 3.12 (see `.python-version`).

```bash
uv venv && source .venv/bin/activate          # with conda: `conda deactivate` first
uv pip install -r src/requirements.txt
cp src/.env.example src/.env                  # fill in LLM_NAME, LLM_BASE_URL, LLM_API_KEY; loaded automatically
cd src

python -m navigator crawl                     # ~10 min for all sites; --only artorg dcberne for a subset
python -m navigator enrich                    # ~35 min with 8 workers; resumable; --limit 20 for a test run
python -m navigator index                     # ~1 min
python -m navigator search "partner to validate a wearable glucose sensor"

uvicorn navigator.api:app --port 8000         # web page on http://localhost:8000
```

Build the profile index with `python -m navigator index` after collecting and enriching pages. Without `LLM_BASE_URL`, `search` returns similarity-ranked profiles without query rewriting or LLM reasons. The prior BM25 workflow remains available as `search-legacy` and `POST /search/legacy`.

## Retrieval layer and test bench

```bash
python -m navigator pages        # raw HTML -> data/pages.jsonl (incremental, safe while the net crawls)
python -m navigator cards        # net records + pages -> data/index/to_embed.jsonl
python -m navigator embed        # embeds only new lines (person cards first), GPU if available
python -m navigator ask "who works on organ-on-chip models?"     # people, units, pages + evidence
python -m navigator bench --label cards-rollup                   # score vs bench/gold.jsonl
python -m navigator search-legacy "clinical validation of glucose sensors"
```

- **cards**: one card per person and unit record from `data/net/net.sqlite`, plus 200-word chunks of
  research/infra/project pages. Sites without a unit record get one from their pages.
- **ask** ([rank.py](navigator/rank.py)): one embedding search, then a roll-up. A page hit also credits
  the people listed on that page (max 8) and its unit. Leads get a small boost. A best score under
  `--floor` returns `no_reliable_match`.
- **bench** ([bench.py](navigator/bench.py)): runs every question in [bench/gold.jsonl](../bench/gold.jsonl),
  finds the rank of each expected answer and reports Hit@3, Recall@10, MRR, nDCG@10, candidate
  recall@50, no-answer accuracy, paraphrase overlap and latency, with 95% bootstrap ranges.
  Each run is saved to `bench/runs/<label>.json`, and `bench/report.html` compares all runs.
- Compare setups with flags: `--kinds page --no-rollup` (pages only), `--lead-boost 0`, `--floor 0.84`.
- Gold answers marked `"status": "draft"` were drafted from the sites' own "Head/Leitung" statements.
  Open the `source` URL, confirm, and set `"checked"`.

If `data/pages.jsonl` and `data/entities.jsonl` are already there, only `index` and the server are needed.

## Company → queries

```bash
python -m navigator company "Ypsomed" https://www.lindt-spruengli.com "startup that detects lameness in dairy cows"
```

Given only a name, URL or idea, [company/](navigator/company/) collects the company's own pages
(or Wikidata and Wikipedia for a name). It profiles what the company does and wants: aspirations,
goals, wants and challenges, each with a quote. It maps these onto the resource sections A–M of the
collection net, and writes each question the company would ask, with EN and DE retrieval queries.
Output goes to `data/companies/<slug>/`: `queries.json` (readable by `navigator retrieve`) and `report.md`.
Apertus does the profile, needs and queries; without `LLM_BASE_URL` a lexicon and templates do.
Prompts: [company/prompts.py](navigator/company/prompts.py). Plan: [Docs/company_queries_plan.md](../Docs/company_queries_plan.md).

## Embeddings on a GPU / separate embedding retrieval

After `crawl` and `pages`, build the vector index and run retrieval:

```bash
python -m navigator embed
python -m navigator retrieve "clinical validation of glucose sensors" --out data/matches.json
# Or provide company.json with need, optional goals and keywords:
python -m navigator retrieve company.json --out data/matches.json
```

The default model is `intfloat/multilingual-e5-small`, configurable with `EMBED_MODEL`. `embed` splits page text into chunks and writes `chunks.jsonl`, `vectors.npy` and `meta.json` under `data/index/`. `retrieve` embeds the query with the same model and returns chunks above the similarity threshold, up to `--top-k` per query. Its default threshold of 0.85 is a configurable heuristic, not a probability or a validated guarantee of relevance.

`navigator embed` uses CUDA when the installed torch build can see it, then MPS if available, otherwise CPU. Override with `EMBED_DEVICE=cpu|cuda|mps`. Check CUDA availability with `python -c "import torch; print(torch.cuda.is_available())"`. A GPU is optional.

Later embedding runs reuse unchanged chunk vectors and remove chunks absent from the page corpus; changing the model rebuilds the vectors. These commands do not run Apertus or change the behavior of `search`.

## Manage website sources

Use the signed-in **Admin** page to add, edit, or remove a website source.
Changes are stored in `.data/auth.sqlite` and picked up by
`python -m navigator sources`; run the crawler to collect pages from changed
sources. The supplied UniBE subdomain inventory remains a separate discovery
map for the University of Bern ecosystem.

For source configuration committed with the project, append an entry to
[sources.json](sources.json) (`id`, `name`, `url`, `institution`, optional
`seed_paths`).

For bulk collection, append an entry to [sources.json](sources.json) (`id`, `name`, `url`, `institution`, optional `seed_paths`), then run `crawl`, `pages`, and optionally `enrich` or `embed` for the intended search workflow. This configuration does not expand the focused collector's source inventory.

## Input / output contract

For `POST /search`, see [navigator/models.py](navigator/models.py). Only `need` is required. The CLI `search` accepts the need, `--keywords` and `--n`; it does not accept a company JSON file. `retrieve` accepts a company JSON file but uses a separate output contract.

```json
{"need": "We build wearable glucose sensors and need clinical validation",
 "company_name": "Acme", "sector": "MedTech", "keywords": ["CGM"],
 "looking_for": ["expert", "infrastructure"], "max_results": 10}
```

## Traceability

- Extracted person, project and infrastructure names are kept only if they appear in the page title or text (case-insensitive). This check does not independently verify roles, expertise, summaries or explanations.
- The judge can only select candidate ids it was given; each result carries the source URLs it came from.
- If nothing scores above the threshold, `no_reliable_match: true` is returned instead of a guess.

## Unified collection and real control set

Keep works, experts and teams together in `data/focused.sqlite`, under one shared cap of 700. Resume collection with the current rules to populate the unified fields from source pages. Use `highlights --limit 500` for a smaller view; it does not create another database or reduce the collection cap. Stop an older crawler before restarting it so the process loads the current rules and limit.

```text
python -m navigator focused-crawl --complete --max-findings 700 --report data/focused-complete-run.json --export data/highlights.json
python -m navigator highlights --limit 700 --out data/highlights.json
python -m navigator.focused.evaluate_unified --out data/unified-control-evaluation.json
python -m navigator company-report bench/company-request.example.json --out data/company-report.json --markdown-out data/company-report.md
```

The unified export is schema 3. A fresh record includes `selection_score`, `selection_version: unified-v1`, and `source_read_version`. Experts and teams additionally carry `roles`, `competencies`, `related_works`, `attributed_evidence` and identity evidence. Every related-work link retains its accepted-work evidence even when that work is outside the final cap. A bare name, professor title, contact listing or shared page is insufficient. Same-name entities merge only with a shared explicit profile identity or the same verified local mention; explicit translated project links are recognized. External participants do not inherit the host institution as their employer. Read-only legacy output strips old contact fields without changing the database.

Entity scoring version `entities-v2` uses contribution/expertise/results/application/recognition/collaboration, weighted **25/15/25/15/5/15**. Each is 0–4; the total is `sum(weight * level / 4)`. Expertise distinguishes a specific research subject, a concrete method, a completed method-based tool/resource, and quantitatively validated methods. Missing evidence is `0` with a no-data reason. Contribution must be linked to an accepted work; topic headings are not people.

The scorer uses own assertions, including immediate person pronouns and a named team's first-person prose on its own detail page. Citation text retains the attribution context verbatim. Another subject or paragraph ends the pronoun context. Research plans, prestige, repeated mentions, an institution's achievements and a colleague's results do not add points. A completed study can support a result; research intended for clinical evaluation does not establish completed clinical testing. Exact heuristics and explanations are in `entities.py`; unsupported phrasing can still be missed.

To rescore the same working database, stop its crawler first and run:

```text
python -m navigator refresh-evaluations --source-snapshot data/unified/fresh-sources.jsonl
python -m navigator highlights --out data/highlights.json
```

The optional dated JSONL restores own assertions only when it contains the retained role proof from the same source. It does not create another database, change IDs, or modify the crawl queue. Omit `--source-snapshot` to use retained excerpts only. Restart collection afterwards to load the new scoring/extraction version. The export's `ranking.by_type` reports score distributions, the fraction sharing the most common score, and criterion coverage separately for experts, teams and works. Entity evaluations also report how many of the six criteria have evidence. These coverage counts are diagnostics, not extra points or confidence probabilities.

`bench/unified_control60.json` contains 20 real experts, 20 real teams and 20 real work candidates, including weak examples, with source text and pre-score ordinal preference labels. Its SHA-256 is checked on evaluation. This is an agent-reviewed development set, not independent human validation. Extraction errors and within-/between-type ranking agreement are reported separately, including ties and missed candidates. Do not describe the result as the objectively best 700 objects in Bern.


Run the live positive/negative evidence controls against the configured report model:

```text
python -m navigator.focused.evaluate_entailment --out data/unified/report-repair/entailment-control-final.json
python -m navigator company-report bench/company-request.example.json --out data/company-report.cgm-v2.json --markdown-out data/company-report.cgm-v2.md
```

The entailment controls include ongoing/planned versus completed work, false radar-to-CGM validation, fabricated services, wrong-person achievements, compound overclaims, and valid weaker statements about joint work. They are labelled development regressions, not independent validation. Model replies and earlier failed runs are retained under `data/unified/report-repair/`.

Append an entry to [sources.json](sources.json) (`id`, `name`, `url`, `institution`, optional `seed_paths`),
then run `crawl`, `enrich` and `index` again. Each step only processes what is new.

## Traceability

- People, roles, emails, projects and infrastructure are kept only if they appear verbatim in the page text.
- The judge can only pick candidates it was given; every result carries the source URLs it came from.
- If no candidate fits, the response says `no_reliable_match: true` instead of guessing.
- When a page exists in German and English, only the English version is indexed, so units are not listed twice.
