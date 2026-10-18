# Company Search & Match: Bern Life Science

This part of the Research & Expertise Navigator works from the **company side**.
It takes information about a company (a pitch PDF, a website, or plain text in
any language), extracts a structured profile, and scores how well the company
fits the **Canton of Bern's life-science ecosystem** (University of Bern,
ARTORG Center, Diabetes Center Berne).

Every result explains its score: a **collaboration potential** from 0 to 100
(judge verdict + P1–P4 priority), how each point was earned, what would raise
it, and links to the public pages behind each claim.

```
company source (PDF / URL / text / name-only, any language)
        │
        ▼
 1. Ingest          extractors.py   PDF, HTML, JSON, or company name
 2. Translate       i18n.py         → English (bridge; Apertus when configured)
 3. Web enrich      web_enrich.py   name search (Wikipedia…) → context + keywords + website
 4. LLM summary     llm_client.py   local Ollama (qwen2.5) by default; Apertus / Kimi optional
                                    (UI layer view shows the live model label — not Kimi-only)
 5. Extract         extractors.py   name, sector, needs, HQ, Bern presence
    Medical profile medical_profile.py   optional Deep LLM (slow JSON); off for fast demos
 6. Understand      semantics.py    focus clusters by synonym frequency
 7. Match + score   engine.py + scoring.py   collaboration potential % + judge verdict
 8. Hand off        company_output.py / handoff.py → outbox/*.json for the navigator
```

**UI:** `http://127.0.0.1:5173` → API `8088`. Paste a company name or website,
click **Extract & prioritize** (10–30s typical). Layer view steps come from the
API and name the **active** LLM (e.g. `ollama:qwen2.5:3b`).

**Scope: life science only.** Medtech, pharma, biotech, biopharma, digital
health, labtech, CDMO and medical nutrition. Any other company is flagged
`out of scope` and scores **0**; it is never given a made-up partial match.

---

## LLM provider

All LLM calls (medical profile, summary, translation, `--llm`) go through
`llm_client.py`. With `LLM_PROVIDER=auto` (the default), the first available is used:

| Order | Provider | Setup | API key in project? |
|---|---|---|---|
| 1 | **Apertus** | `LLM_NAME` / `LLM_BASE_URL` / `LLM_API_KEY` | yes |
| 2 | **Ollama** (default local `qwen2.5:3b`; free) | Ollama app + `ollama pull qwen2.5:3b` | **no** |
| 3 | Kimi API | `KIMI_API_KEY` | yes |

```bash
ollama pull qwen2.5:3b        # free local model (recommended; faster demos)
ollama run qwen2.5:3b "hi"    # quick check
curl localhost:8088/health    # shows "llm": {"provider": "ollama", "model": "ollama:qwen2.5:3b", ...}
```

Notes:
- Prefer a **local** model (`qwen2.5:3b`). Cloud models like `kimi-k2.6:cloud` need
  paid Ollama credits (HTTP 402); on failure the client auto-retries with a local model.
  Override via `OLLAMA_MODEL` (e.g. `qwen2.5:7b`). A locally pulled Apertus GGUF also works offline.
- Thinking text is discarded. Keep `OLLAMA_THINK=0` for local models (faster + better JSON).
- The challenge requires Apertus v1.5 for the submission. Local Ollama is for demos.

## Medical profile (LLM extraction)

When an LLM is available (see above), it reads the source and returns a
structured **medical profile**. Each field has its own job:

| Field | Content |
|---|---|
| `what_they_do` | **One sentence**: company type + modality + therapeutic area, e.g. *"Medical device company developing a wearable continuous glucose monitoring (CGM) patch for type 1 diabetes."* |
| `summary` | **2–3 sentences on the medical connection only**: diseases, patient groups, technologies, clinical activity. Must add detail, not restate `what_they_do` |
| `therapeutic_areas`, `indications`, `modalities_technologies`, `products_platforms`, `patient_populations`, `development_activities` | lists of medical terms, **each with a verbatim source quote** |
| `business_model` | one of: pharma, biotech, medical device, IVD, digital health / SaMD, CDMO, lab tools, medical nutrition… |
| `partnership_needs` | only needs the company explicitly asks for |
| `information_sufficiency` | `sufficient` / `limited` / `insufficient`, plus `missing_information` |

**How the output stays accurate (prompts in `profile_prompts.py`):**

- **Source-only facts.** The prompt forbids using the model's own knowledge of the
  company. It may reword into medical terms ("blood sugar" → "blood glucose"),
  but may not add facts.
- **Medical wording.** The prompt lists the expected vocabulary (therapeutic
  areas, modalities such as monoclonal antibodies, radioligand therapy, CGM,
  SaMD, IVD; indications).
- **Marketing is ignored.** Slogans, company history and mission statements are
  excluded by the prompt, and marketing lines are moved to the end of the input.
- **One fictional worked example** in the prompt shows the exact format, without
  giving the model any real company's facts.
- **Every item is checked in code.** Its quote must appear in the source (exact,
  or ≥ 85 % word for word), otherwise the item is dropped and listed in
  `dropped_unsupported`. Bracketed additions not in the source are removed
  ("Kisqali (ribociclib)" → "Kisqali"). Needs must come from a sentence that
  asks for something ("looking for", "seeking", "need"…).
- **Generated sentences are checked too.** If `what_they_do` or `summary` uses too
  many words the source doesn't support (below 60 %), or the summary repeats
  `what_they_do`, it is rebuilt from the verified items.
- **Prompt-injection defence.** Web text is wrapped in `<source>` tags as untrusted
  data, and sentences addressed to an AI ("ignore previous instructions…") are
  removed before the call.
- **Honest gaps.** A page with only marketing text gets
  `information_sufficiency: insufficient` and a summary saying what is missing,
  never invented content.
- **Repeatable.** Temperature 0.1, and results are cached in `data/llm_cache/` by
  source + prompt version, so demo re-runs are instant and identical.

Without an LLM, rule-based fallbacks run: `what_they_do` is a one-line
description built from the detected sector, focus and terms, and the summary is
the page's own description.
Set `LLM_PROFILE=0` to turn the LLM profile off.

## Location (headquarters) with provenance

The HQ comes from the first source that has it, and the output records which one
in `hq_source` (`method`, `evidence`, `url`, `verified`):

| # | Method | Example |
|---|---|---|
| 1 | `source` | "Headquarters: Zurich, Switzerland" in the pitch |
| 2 | `json_ld` | schema.org address on the website |
| 3 | `llm_quote` | the LLM found the address and quoted it from the page |
| 4 | `footer` / `imprint` | "Lichtstrasse 35, CH-4056 Basel" in the footer, or on the imprint/contact page (followed automatically) |
| 5 | `wikidata` | public Wikidata record, accepted only if its official website matches the source domain, linked in the output |
| 6 | `llm_knowledge` | model knowledge, **last resort, shown as UNVERIFIED** |

**Canton of Bern presence (scoring input) only comes from verified sources (1–5).**
Model knowledge can fill the display field but never earns points.
Switches: `WIKIDATA_LOOKUP=0`, `LLM_BACKGROUND_FACTS=0`.

## Scoring system

### Approach

The match rate answers one question: **should the Canton of Bern pursue a
collaboration with this company?** It is a number from 0 to 100, the sum of
five named parts, each with a fixed maximum.

The score had to meet five goals:

1. **Tell companies apart.** Earlier versions saturated: first every company
   scored 100, later every medtech scored 80–95, because sector and country
   (shared by many companies) carried most of the points. Now the largest part
   is the **specific overlap with Bern's capabilities**, so the samples spread
   from about 26 to 89.
2. **Count each fact once.** Bern presence counts only under proximity, and
   stated needs only under partnership readiness.
3. **Be explainable.** The output lists each part next to its maximum, plus
   `why_not_higher` hints. Anyone can recompute it by hand (see the worked
   example below).
4. **Reward real evidence over word counts.** Repeating "glucose" ten times
   can't max anything out, and vague words ("sensor", "diagnostic") count less
   than specific phrases ("continuous glucose monitoring").
5. **Prefer verified Bern data.** Capability overlap can only reach its maximum
   when the company matches **real Bern people, units or projects** that
   teammates extracted, each with a public `source_url`. Without that data it
   stops at 34 of 40.

Everything is rule-based: no LLM decides the score, so the same input always
gets the same score and it runs fully offline. (The LLM only improves the
extracted profile that goes in.)

### The five parts

| Part | Max | What earns points |
|---|---:|---|
| `capability_overlap` | **40** | Specific overlap with Bern capabilities (+ Bern records when loaded) |
| `partnership_readiness` | **20** | Stated needs Bern can serve (trials, hospital, university…) |
| `domain_fit` | **15** | Life-science sector Bern prioritises (pharma / medtech / biotech…) |
| `swiss_proximity` | **15** | Canton of Bern site, or Swiss / nearby HQ |
| `signal_depth` | **10** | Usable description, keywords, website |
| **Total** | **100** | `match_rate` = collaboration potential = sum of the five parts |

Capability overlap is the largest part on purpose: sector and country alone
must not push every medtech into the 80–95 band. Each fact counts once
(Bern presence only under `swiss_proximity`).

### How each part is calculated

**Step 0: term credit.** Bern capabilities (`data/bern_expertise.json`) each
have keywords and synonyms. Every one found in the company's profile earns
credit:

| Term type | Credit | Examples |
|---|---:|---|
| Specific phrase (multi-word or hyphenated) | 1.0 | `continuous glucose monitoring`, `robotic surgery` |
| Single word, longer than 3 letters | 0.6 | `diabetes`, `biosensing` |
| Short word / acronym | 0.5 | `cgm`, `mri` |
| Generic term | 0.3 | `sensor`, `diagnostic`, `insulin`, `medtech`, `type 1` |

**Part 1: capability overlap (≤ 40).** Built from capability points
(fit + breadth + focus + evidence), then scaled into 40:

```
capability_overlap = 40 × min(1, cap_points / cap_max)
```

- **fit_points (≤ 35):** the single best capability. Its term credits are added
  up (`raw`) and turned into a 0–1 fit that rises fast, then levels off
  (raw 3 → 63 %, raw 6 → 86 %, raw 9 → 95 %). `capability_weight` (0.65–1.15,
  set in `bern_expertise.json`) reflects how central that capability is to the
  three sources; Diabetes/CGM has the top weight, 1.15.
  ```
  fit = (1 − e^(−raw / 3)) × min(1, capability_weight / 1.15)
  fit_points = 35 × fit(best capability)
  ```
- **breadth (≤ 10):** a 2nd and 3rd matching capability:
  `10 × min(1, (fit₂ + fit₃) / 1.2)`.
- **focus (≤ 10):** `semantics.py` finds the company's main theme (e.g.
  *Glucose sensing / CGM*, with a relevance in %). If it maps to a matched
  capability: `10 × relevance% × (1.0 if best capability, else 0.5)`.
- **evidence (≤ 20):**
  - with teammate Bern records loaded (`data/bern_records/`), the best record
    counts fully and the 2nd and 3rd add support:
    `20 × min(1, score₁ + 0.25 × (score₂ + score₃))`;
  - without records, a stand-in based on distinct matched terms, **capped at 8**:
    `8 × min(1, distinct terms / 10)`. That cap is why capability overlap stops
    at 34/40 without real Bern data.

**Part 2: partnership readiness (≤ 20).** Needs found in the source (only
sentences that express intent, like "we are seeking…"):

| Need | Value |
|---|---:|
| clinical validation, clinical trial | 1.0 |
| hospital partnership, university collaboration | 0.9 |
| device R&D | 0.8 |
| KOL access, talent | 0.7 |
| Swiss hub | 0.5 |
| EU partners | 0.3 |
| anything else | 0.2 |

```
partnership_readiness = 20 × min(1, sum of need values / 2.5)
```

Two or three strong needs are enough for full points.

**Part 3: domain fit (≤ 15).** `15 × sector value`: pharma and biopharma 1.0,
biotech and medtech 0.95, digital health and CDMO 0.85, labtech 0.8, medical
nutrition 0.7, other in-scope life science 0.55.

**Part 4: Swiss proximity (≤ 15).**

| Location | Share | Points |
|---|---:|---:|
| Site or HQ in the Canton of Bern (verified source only) | 100 % | 15 |
| Swiss HQ in a city near Bern (Basel, Zurich, Geneva, Lausanne, Fribourg, Neuchâtel, Solothurn, Biel, Thun, Aarau) | 90 % | 13.5 |
| Other Swiss HQ | 70 % | 10.5 |
| Germany, France, Austria, Italy | 35 % | 5.25 |
| Elsewhere / unknown | 0 % | 0 |

Bern presence needs an HQ line in Bern, Burgdorf, Biel or Thun, an explicit
phrase like "office in Bern", or a verified address (footer, imprint). A bare
mention ("looking for partners in Bern") does **not** count, and an HQ that
comes only from model knowledge never earns points.

**Part 5: signal depth (≤ 10).** `10 × min(1, d)`, where `d` adds 0.45 for a
description of 80+ characters (0.25 for 40+), 0.35 for 4+ keywords (0.2 for
1+), and 0.2 for a website. It keeps a one-line pitch from ranking like a
fully described company.

**Out of scope:** if the life-science check fails (`domain.py`), the match
rate is 0 and no parts are computed.

### Verdicts

| Match rate | Verdict |
|---|---|
| ≥ 70 | Strong potential: prioritise outreach |
| ≥ 50 | Promising: worth exploring with Bern units |
| ≥ 30 | Possible: gather more needs / capability detail |
| < 30 | Weak: low priority for now |

The navigator queue (`priority.py`) adds a P1–P4 rating on top, which also
considers how early the key terms appear in the source.

### Worked example: Helix Glucose (sample `two_companies.txt`)

> *Wearable CGM sensors and biosensing patches for type 1 and type 2 diabetes;
> looking for clinical validation partners, university collaboration, EU market
> entry; roadmap includes closed-loop research with academic hospitals.
> HQ: Zurich, Switzerland.*

| Part | Calculation | Points |
|---|---|---:|
| capability_overlap | Diabetes/CGM fit + breadth + focus + term evidence (no records) | **~26** |
| partnership_readiness | clinical validation + university + EU needs | **~18** |
| domain_fit | medtech → 15 × 0.95 | **14.2** |
| swiss_proximity | HQ Zurich, near Bern → 15 × 0.9 | **13.5** |
| signal_depth | rich description + keywords + website | **10.0** |
| **Match rate** | | **~81 → Strong potential** |

Exact numbers: re-run
`python -m company_match ingest --file src/company_match/samples/two_companies.txt -v`.

### Results on the samples

Offline (no LLM, no web search), after the weight rebalance:

| Company | Profile | Match rate |
|---|---|---:|
| Bern Biosense Labs | glucose sensors, HQ in Burgdorf (BE), 3 needs | 82.6 |
| Helix Glucose | CGM, Zurich, 3 needs | 81.1 |
| Alpine Surgical Systems | surgical navigation, Munich, 3 needs | 70.3 |
| ARKRAY (Japanese source) | blood-glucose diagnostics, Japan, no needs | 46.1 |
| One-line "wearable sensors" pitch | almost no detail | 25.9 |
| Fintech company | not life science | 0.0 |

With teammate Bern records loaded, scores rise ~5 points.

### Bern record matching (teammate data)

Teammates put records (person / unit / group / project / infrastructure /
service) into `data/bern_records/*.json(l)`. Each record needs `id`, `name`,
`type` and a public `source_url`. The company's keywords and matched capability
terms are searched in each record's fields, weighted by how strongly each field
signals real expertise:

| Record field | Weight |
|---|---:|
| expertise | 1.0 |
| projects | 0.8 |
| infrastructure, services | 0.6 |
| description | 0.5 |
| unit, name | 0.3 |
| role | 0.2 |

- **Synonym expansion:** company terms are widened with the synonym groups in
  `semantics.py`, so "glucose sensors" finds a researcher whose page says
  "continuous glucose monitoring". A synonym hit counts at 70 % of an exact hit.
- **One concept, one count:** each company term counts once, through its best
  hit.
- **Record score:** `1 − e^(−raw / 2)`. Records below 0.15 are dropped.

Each match in `bern_matches` lists the record, its score, the matched terms and
fields, a plain-language reason, and the **`source_url`**, so every claim can
be checked.

Record format and validation: see [BACKEND_CONTRACT.md](BACKEND_CONTRACT.md).

### Changing the weights

All maximums live in `scoring.py → DEFAULT_WEIGHTS`. To re-weight without
editing code, create `data/scoring_weights.json` with the parts to change, for
example:

```json
{ "capability_overlap": 35, "swiss_proximity": 20 }
```

Keep the five maximums adding up to 100 so the match rate stays a percentage.

### Limits (stated honestly)

- Term matching is lexical plus synonyms. Concepts phrased in ways no keyword
  or synonym list covers are missed. The Qdrant vector search
  (`qdrant-search`) is the semantic complement for later-stage matching.
- Needs and Bern presence come **only from the company's own source**, never
  from web-search snippets. A company that doesn't state its needs scores 0 on
  partnership readiness even if it has them.
- Domain fit and Swiss proximity describe the company, not the match, so they
  are kept to 30 points together; the ranking among similar companies is
  decided by capability overlap and stated needs.
- The capability taxonomy (`bern_expertise.json`) is a hand-curated seed.
  Teammate records are what turn a "theoretical fit" into verified evidence.

---

## Running it

```bash
export PYTHONPATH=src
pip install -r src/company_match/requirements.txt
cp .env.example .env
# Demo LLM (recommended): install Ollama, then:
#   ollama pull qwen2.5:3b
# Submission LLM: set LLM_NAME / LLM_BASE_URL / LLM_API_KEY (Apertus)

# Command line
python -m company_match ingest --file src/company_match/samples/two_companies.txt -v
python -m company_match ingest https://example.com/about pitch.pdf
python -m company_match bern-records -q "glucose sensors"     # check teammate records

# API + UI
uvicorn company_match.api:app --app-dir src --port 8088
cd src/company_match/web && npm install && npm run dev     # http://127.0.0.1:5173
curl -s localhost:8088/health   # confirms provider, e.g. ollama:qwen2.5:3b
```

| Endpoint | Purpose |
|---|---|
| `POST /ui/analyze` | UI: upload / text / URL → full card with score breakdown and Bern matches |
| `POST /ingest/upload` | multipart files + text + URLs → batch JSON |
| `POST /ingest` | JSON `{text, urls}` → batch JSON (server file paths disabled by default) |
| `POST /match` | already-structured company dict → match result |
| `GET /bern/records/status` | which teammate records are loaded, and any problems |

### Settings (`.env`)

| Variable | Default | Effect |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:3b` | Local demo LLM (no API key; faster than 7b) |
| `LLM_NAME`, `LLM_BASE_URL`, `LLM_API_KEY` | – | Apertus (submission): translation / summaries / profile |
| `LLM_PROFILE_NAME_SEED` | `0` | `1` = heavy JSON medical profile on name-only (slow) |
| `FAST_WEB_SNIPPET` | `0` | `1` = name-only uses Wikipedia snippet, skip LLM rewrite |
| `WEB_ENRICH` | `0` | `1` = always web-search by name (name-only seeds always search) |
| `BERN_RECORDS_PATH` | `data/bern_records/` | teammate records file or folder |
| `ALLOW_LOCAL_PATHS` | `0` | `1` = `POST /ingest` may read server file paths (local dev only) |
| `ALLOW_PRIVATE_URLS` | `0` | `1` = allow fetching localhost / private-network URLs |

## Output for the navigator backend

Every run writes `outbox/companies/latest_batch.json` (`schema_version 2.0`).
Per company you get `profile`, `website_info` (source type and reference) and
`match`:

- `match_rate`, `tier`
- `score_breakdown.components` / `component_max`: the five parts above
- `why_not_higher`
- `bern_matches`: verified records with `source_url`
- `capability_matches`, `reasons`, `teammate_queries_early` / `teammate_queries_later`

Teammates only read the files; they don't need to import this package.

## Files

| File | Role |
|---|---|
| `extractors.py` | read PDF / HTML / text / JSON, extract the company profile |
| `i18n.py` | language detection and translation to English |
| `semantics.py` | synonym clusters, main themes, relevance % |
| `domain.py` | life-science scope check |
| `engine.py` | capability matching, builds the match result |
| `scoring.py` | **the scoring model described above** |
| `bern_records.py` | load, check and match teammate Bern records |
| `priority.py` | P1–P4 order of which companies the navigator should look at first |
| `company_output.py`, `handoff.py` | JSON / Markdown output for the backend |
| `api.py`, `cli.py`, `web/` | HTTP API, command line, React UI |
| `data/bern_expertise.json` | Bern capability taxonomy (keywords, synonyms, units, weights) |
| `data/bern_records/` | teammate records (example format in `_EXAMPLE_records.json`) |
