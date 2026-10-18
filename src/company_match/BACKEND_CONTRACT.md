# Company ↔ Bern backend contract

How the **company layer** (this package) and the **Bern expertise layer**
(teammates' UniBE / ARTORG / Diabetes Center Berne extraction) connect.
Both sides talk through **plain JSON files**, so neither side has to import the
other's code.

```
teammates' extraction ──► data/bern_records/*.json(l) ──┐
                                                        ├─► engine.match_company ──► outbox/companies/*.json
company sources (PDF/URL/text) ──► extractors ──────────┘        (match_rate + bern_matches with source_url)
```

---

## 1. What teammates provide: Bern records

Drop one or more files into `src/company_match/data/bern_records/`
(or point `BERN_RECORDS_PATH` at a file or folder). They are re-read automatically
when the files change. Files whose name starts with `_` are ignored
(`_EXAMPLE_records.json` only shows the format).

Accepted shapes: a JSON array, `{"records": [...]}`, or JSONL (one record per line).

| field | required | type | notes |
|---|---|---|---|
| `id` | ✅ | string | stable + unique (e.g. `artorg-person-jdoe`) |
| `name` | ✅ | string | person / unit / project name as on the page |
| `type` | ✅ | string | `person` · `unit` · `group` · `project` · `infrastructure` · `service` |
| `source_url` | ✅ | http(s) URL | **public page that supports the record** (traceability rule) |
| `expertise` | ◻︎ | list[str] | strongest matching signal: use the page's own terms |
| `projects` | ◻︎ | list[str] | |
| `infrastructure` | ◻︎ | list[str] | labs, platforms, core facilities |
| `services` | ◻︎ | list[str] | testing, consulting, clinical studies… |
| `description` | ◻︎ | string | short text from the page |
| `role` | ◻︎ | string | for persons: function as shown on the page |
| `unit` | ◻︎ | string | group / department / institute |
| `institution` | ◻︎ | string | `University of Bern`, `ARTORG Center`, `Diabetes Center Berne`… |
| `contact` | ◻︎ | string | only public contact info shown on the source page |
| `extra_source_urls` | ◻︎ | list[url] | other pages that support the same record |

At least one of `expertise` / `description` / `projects` must be present.
A list field may also be a `;`- or `,`-separated string. Extra keys are kept untouched.

Minimal example (JSONL):

```json
{"id":"dcb-unit","type":"unit","name":"Diabetes Center Berne","institution":"Diabetes Center Berne","expertise":["diabetes technology","continuous glucose monitoring"],"source_url":"https://www.diabetescenter-berne.ch/"}
```

### Validate before handing over

```bash
export PYTHONPATH=src
python -m company_match bern-records                       # counts + problems per record
python -m company_match bern-records -q "glucose sensors, wearable"   # test a query
python -m company_match bern-records --strict              # exit 1 on any invalid record (CI)
curl localhost:8088/bern/records/status                    # same, from the running API
```

Invalid records are **skipped with a reason**, never silently matched.

---

## 2. What the company layer outputs

`outbox/companies/latest_batch.json` → `companies[]`, one object per company
(`schema_version: "2.0"`). Fields that matter for the backend:

```jsonc
{
  "id": "helix_glucose",
  "name": "Helix Glucose",
  "in_scope": true,
  "website_info": { "source_type": "file", "source_ref": "…/two_companies.txt#part-1", … },
  "profile": { "sector": "medtech", "keywords": [...], "needs": [...], "canton_bern_presence": false, … },
  "match": {
    "match_rate": 86.8,
    "tier": "Strong collaboration potential",
    "score_breakdown": {
      "model": "collaboration-v1",
      "components":    { "capability_overlap": 31.5, "partnership_readiness": 17.6,
                         "domain_fit": 14.2, "swiss_proximity": 13.5, "signal_depth": 10.0 },
      "component_max": { "capability_overlap": 40, "partnership_readiness": 20,
                         "domain_fit": 15, "swiss_proximity": 15, "signal_depth": 10 },
      "details": { "capability_components": { "capability_fit": 28.8, "breadth": 3.1,
                   "focus_synergy": 8.6, "evidence": 18.6, … }, … },
      "why_not_higher": ["Swiss company but no Canton of Bern site yet."]
    },
    "bern_matches": [
      { "record_id": "dcb-unit", "name": "Diabetes Center Berne", "type": "unit",
        "score": 0.63, "matched_terms": ["diabetes","glucose"],
        "matched_fields": {"expertise": ["continuous glucose monitoring", "diabetes"]},
        "reason": "Diabetes Center Berne (unit, …) matches on expertise: …",
        "source_url": "https://www.diabetescenter-berne.ch/" }
    ],
    "capability_matches": [...],      // seed capability taxonomy (data/bern_expertise.json)
    "reasons": [...],                 // human-readable, includes "Verified Bern match … Source: <url>"
    "teammate_queries_early": [...]   // navigator queries to run first
  }
}
```

**Invariant:** `sum(score_breakdown.components) == match_rate` (rounded). Re-weighting
on the backend side is therefore safe and transparent.

---

## 3. Scoring model (`scoring.py`)

| component | max | earns points for |
|---|---|---|
| `capability_overlap` | 40 | overlap with Bern capabilities: best capability (35) + breadth (10) + main-theme focus (10) + **evidence from verified teammate records** (20; at most 8 without records), scaled from 75 to 40 |
| `partnership_readiness` | 20 | stated needs Bern can serve (clinical validation/trials, hospital, university, talent…) |
| `domain_fit` | 15 | life-science sector value (pharma 1.0 … nutrition 0.7) |
| `swiss_proximity` | 15 | Canton of Bern site (15), Swiss HQ near Bern (13.5), other Swiss (10.5), DE/FR/AT/IT (5.25) |
| `signal_depth` | 10 | description, keywords and website present |

Capability terms rise fast for the first few matches, then level off
(`1 − e^(−raw/3)`), so repeating a term cannot max it out. Generic words
("diagnostic", "sensor") count for 0.3 of a specific phrase. Without teammate
records, `capability_overlap` stops at 34/40, so loading real Bern records is
what lifts a company to the top.

Change weights without touching code: create `data/scoring_weights.json`, e.g.
`{"capability_overlap": 35, "swiss_proximity": 20}` (keep the five maximums
summing to 100). The inner capability points (`capability_fit`, `breadth`,
`focus_synergy`, `evidence`, `evidence_without_records`) can be changed the same way.

Tiers: strong ≥ 70 · promising ≥ 50 · possible ≥ 30 · weak < 30. Out-of-domain (non-life-science) = 0.

---

## 4. Runtime switches (`.env`)

| variable | default | effect |
|---|---|---|
| `LLM_NAME` / `LLM_BASE_URL` / `LLM_API_KEY` | – | Apertus endpoint: translation, summaries, `--llm` extraction |
| `WEB_ENRICH` | `0` | `1` = also search DuckDuckGo/Wikipedia by company name (leaves the offline mode) |
| `BERN_RECORDS_PATH` | `data/bern_records/` | teammate records file or folder |
| `ALLOW_LOCAL_PATHS` | `0` | `1` = `POST /ingest` may read server-local `files` (local dev only) |
| `ALLOW_PRIVATE_URLS` | `0` | `1` = allow fetching localhost / private-network URLs |

Security defaults: the HTTP API never opens a server file from a request string
(use `POST /ingest/upload`), and never fetches loopback / private / cloud-metadata
addresses, including via redirects.
