# Research & Expertise Navigator — code

Four steps, one file each in [navigator/](navigator/):

| Step | File | In → out |
|---|---|---|
| 1. crawl | `crawl.py` | websites from `sources.json` + the UniBE inventory → `data/pages.jsonl` (clean text per page) |
| 2. enrich | `enrich.py` | Apertus reads each page → `data/entities.jsonl` (unit, people, roles, expertise, projects, infrastructure, EN/DE synonyms) |
| 3. index | `index.py` | per-page records → one profile per person and per unit, embedded → `data/profiles.jsonl`, `data/vectors.npy` |
| 4. search | `search.py` | Apertus rewrites the need → similarity search over profiles → Apertus keeps the units that fit and says why |

`api.py` serves the web page (`static/index.html`) and `POST /search`. `llm.py` talks to any
OpenAI-compatible Apertus endpoint; `models.py` is the request / response contract.

## Run

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

If `data/pages.jsonl` and `data/entities.jsonl` are already there, only `index` and the server are needed.

## Add a new institution

Append an entry to [sources.json](sources.json) (`id`, `name`, `url`, `institution`, optional `seed_paths`),
then run `crawl`, `enrich` and `index` again. Each step only processes what is new.

## Traceability

- People, roles, emails, projects and infrastructure are kept only if they appear verbatim in the page text.
- The judge can only pick candidates it was given; every result carries the source URLs it came from.
- If no candidate fits, the response says `no_reliable_match: true` instead of guessing.
- When a page exists in German and English, only the English version is indexed, so units are not listed twice.
