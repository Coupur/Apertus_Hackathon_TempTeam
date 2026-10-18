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
