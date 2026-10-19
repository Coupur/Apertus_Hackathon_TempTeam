# Navigator backend

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

## Add a new institution

Append an entry to [sources.json](sources.json) (`id`, `name`, `url`, `institution`, optional `seed_paths`), then re-run `crawl` and `enrich`.

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
