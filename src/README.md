# Navigator backend

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

```
Company request ──► 1. understand (Apertus: need → terms + EN/DE synonyms)
                    2. retrieve   (BM25 over crawled + enriched pages)
                    3. judge      (Apertus: keep relevant units, write reason)
                 ──► SearchResponse (units, people, expertise, infra, reason, source URLs)

Offline pipeline:  sources (xlsx + sources.json) → crawl → enrich (Apertus) → data/*.jsonl
```

## Run

```bash
pip install -r src/requirements.txt
export PYTHONPATH=src
export LLM_NAME=swiss-ai/Apertus-v1.5-8B LLM_BASE_URL=http://<host>:8000/v1 LLM_API_KEY=...
# or: cp .env.example .env and add your Keera key (CSCS-hosted Apertus; loaded automatically, gitignored)

python -m navigator sources                          # list the 42+ configured sites
python -m navigator crawl --only artorg dcberne inf  # or no --only for everything
python -m navigator enrich                           # LLM structured extraction
python -m navigator search "partner to validate a wearable glucose sensor"

uvicorn navigator.api:app --app-dir src --port 8000  # POST /search, GET /health
```

Without `LLM_BASE_URL` everything still runs as plain keyword search (no synonyms, no reasons).

## Retrieval layer and test bench

```bash
python -m navigator pages        # raw HTML -> data/pages.jsonl (incremental, safe while the net crawls)
python -m navigator cards        # net records + pages -> data/index/to_embed.jsonl
python -m navigator embed        # embeds only new lines (person cards first), GPU if available
python -m navigator ask "who works on organ-on-chip models?"     # people, units, pages + evidence
python -m navigator bench --label cards-rollup                   # score vs bench/gold.jsonl
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

## Embeddings on a GPU

`navigator embed` uses CUDA automatically when torch can see it (override with `EMBED_DEVICE=cpu|cuda`).
The default pip torch is CPU-only. For an NVIDIA GPU install the CUDA build first:

```bash
pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu128 torch
python -c "import torch; print(torch.cuda.is_available())"   # must print True
```

The index is the same either way: vectors built on CPU and GPU can be mixed, and later runs only embed new chunks.

## Manage website sources

Use the signed-in **Admin** page to add, edit, or remove a website source.
Changes are stored in `.data/auth.sqlite` and picked up by
`python -m navigator sources`; run the crawler to collect pages from changed
sources. The supplied UniBE subdomain inventory remains a separate discovery
map for the University of Bern ecosystem.

For source configuration committed with the project, append an entry to
[sources.json](sources.json) (`id`, `name`, `url`, `institution`, optional
`seed_paths`).

## Input / output contract

See [navigator/models.py](navigator/models.py). Only `need` is required:

```json
{"need": "We build wearable glucose sensors and need clinical validation",
 "company_name": "Acme", "sector": "MedTech", "keywords": ["CGM"],
 "looking_for": ["expert", "infrastructure"], "max_results": 10}
```

## Traceability

- People, projects and infrastructure that the LLM extracts are kept only if they appear verbatim in the page text.
- The judge can only select candidate ids it was given; each result carries the source URLs it came from.
- If nothing scores above the threshold, `no_reliable_match: true` is returned instead of a guess.
