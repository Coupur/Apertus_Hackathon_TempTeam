# Navigator backend

## Focused research highlights

The focused workflow produces a separate SQLite database with **at most 500 research candidates** from the supplied University of Bern inventory, ARTORG, and Diabetes Center Berne. Local rules select concrete significance signals and retain English explanations, short source excerpts and URLs. No model server, API key or GPU is required. Candidates are marked `selection_method: rules` and `review_status: unreviewed`.

The broader selection includes substantive findings, projects, technologies and services at priority 2, and stronger evidence at priority 3. Complete collection traverses the eligible reachable content of all source groups and retains the best 500 candidates. Use `highlights --min-score 3` to inspect only the stronger subset.

From the repository root in PowerShell:

```powershell
pip install -r src/requirements-focused.txt
$env:PYTHONPATH = "src"

# Optionally check original source homepages without selecting findings.
python -m navigator focused-crawl --source-check --only www artorg dcberne

# Collect with deterministic local rules.
python -m navigator focused-crawl --complete --report data/focused-complete-run.json --export data/highlights.json

python -m navigator highlights --limit 20
python -m navigator highlights --organization "ARTORG" --out data/artorg-highlights.json
python -m navigator highlights --json

# Backfill detailed medical/scientific subject tags from stored evidence.
python -m navigator refresh-keywords
python -m navigator highlights --keyword "CGM" --json
python -m navigator highlights --keyword "oncology" --keyword "genomics" --json
```

On POSIX shells, use `export PYTHONPATH=src`. Python's standard-library SQLite implementation is used; no database server is required.

HTML is converted to plain text temporarily. Only selected structured facts, excerpts and compact crawl state persist in `data/focused.sqlite`; `highlights --out` exports JSON. Rules prioritize material for review and do not independently verify scientific importance or translate source text. `LLM_*` environment variables have no effect on focused collection.

Findings include subject `keywords` with detailed medical coverage: diseases, specialties, diagnostics, therapies, devices and research methods. English/German terms map to English labels. Tags derive from the original name and supporting excerpts; they describe mentions, not verified clinical efficacy. They are separate from `type`, `organizations` and the existing selection-rule `topics`. New and merged results are tagged automatically; collection startup backfills existing records without recrawling. Keyword filters accept aliases such as `CGM` and `Typ-1-Diabetes`; repeated filters require all terms. Medical subject terms also receive a bounded bonus when prioritizing newly discovered links.

See [the medical keyword sample](../bench/medical-keywords-smoke.json) for output from a small live test on October 18, 2026: five pages produced seven records, with no traversal of discovered links. The sample retains names, keywords, evidence excerpts and source URLs. Local databases and crawl output stay under the ignored `data/` directory.

See [the focused workflow guide](../Docs/Focused%20Crawler.md) for limits, selection rules, persistence, the export contract, and evaluation. The focused commands do not call the legacy publication harvester, PDF downloader, vector index, company search, or HTTP API.

## Legacy bulk collection and company search

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

python -m navigator sources                          # list the 42+ configured sites
python -m navigator crawl --only artorg dcberne inf  # or no --only for everything
python -m navigator enrich                           # LLM structured extraction
python -m navigator search "partner to validate a wearable glucose sensor"

uvicorn navigator.api:app --app-dir src --port 8000  # POST /search, GET /health
```

Without `LLM_BASE_URL` everything still runs as plain keyword search (no synonyms, no reasons).

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
