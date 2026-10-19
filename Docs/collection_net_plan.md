# Collection Net – Implementation Plan

Oct 18, 2026 · build by 20:00, run overnight, process tomorrow morning.
Extends [Bern Data Collection – Technical Plan](Bern%20Data%20Collection%20%E2%80%93%20Technical%20Plan.md); that plan's processing and search steps stay as they are.

## In one paragraph

We replace the one-pass crawler (300 pages per site, 89 sites) with a **net**: a loop that fetches pages, cleans them, judges whether they matter, and then decides where to fetch next. All state lives in one SQLite file, so the loop can be stopped and restarted at any time, and it runs until every source is exhausted. It collects 14 sections of information a company needs, from experts to funding and regulation. Every record keeps the exact quote and URL it came from. Rules and a small embedding model do the work overnight; Apertus reads the hard pages tomorrow.

## 1. Where we are (measured 17:20)

| Fact | Number | What it means |
|---|---|---|
| Sites crawled | 89 | 42 from the inventory, 2 from sources.json, 45 discovered |
| Pages saved | 15,419 | about 40 KB each |
| Sites stopped by the 300-page cap | 27 | www, artorg, dcberne, dbmr, itp, iee and others still had work left |
| Same-site links never fetched | 13,370 | about 2,760 look like person profiles, 1,680 research pages, 580 service or infrastructure pages |
| `*.unibe.ch` hosts linked but never crawled | 500 (371 linked from 2+ pages) | research-group sites such as cb.iee, terr.iee, the psy and zmk sub-clinics, vetsuisse institutes, bwl, vwi |
| Profile pages already on disk | about 5,000 | all use one CMS template with schema.org Person markup |
| BORIS records | 175,932 | harvested in `oai_dc`, which has no affiliations |
| Free disk | 70 GB | enough; no cleanup needed (see §7) |
| GPU | RTX 5050, 8 GB | enough for the embedding model during the crawl |

The net is small for three reasons, all in our code:

1. **Hard cap.** `MAX_PAGES_PER_SOURCE` stops every site at 300 pages, whatever is left.
2. **Discovery skips sub-sites.** `discover.py` drops any host under a known host, so `cb.iee.unibe.ch` is never added, and the crawler counts it against iee's 300 pages.
3. **www.unibe.ch matches every subdomain.** Its host is `unibe.ch`, so `_same_site` lets it wander into all other sites and spend its budget there.

Two cheap wins also showed up:

- **Profile pages are machine-readable.** They carry `itemprop="name"`, `jobTitle`, `email`, `telephone` and `worksFor`. The CMS path in image URLs (`/unibe/portal/fak_medizin/dept_weitere/ins_artorg/`) and the body class (`client-ins_artorg`) give the unit tree. People can be extracted without the LLM. Emails are HTML-entity encoded, which is why `emails` is empty in pages.jsonl today; `html.unescape` before the regex fixes it.
- **BORIS has a richer format.** `metadataPrefix=dim` returns each author's affiliation in author order, the organisation, PMID and publisher DOI. That links papers to units and people without guessing.

## 2. Taxonomy: what we collect

Fourteen sections. **P0** is what the jury measures (success criteria 1–5) and gets a protected share of the budget. **P1** is what makes the result useful for Bern Economic Development and for a company moving here. **P2** is collected only when budget is left.

| § | Section | The company's question | Record types | Main sources | Priority |
|---|---|---|---|---|---|
| A | People and contact persons | Who is the expert, who do I call? | person | UniBE profiles and team lists, ARTORG, DCB API team, BORIS authors, SNSF applicants, ARAMIS contacts | P0 |
| B | Units | Which faculty, institute, group, clinic or centre does this? | unit | UniBE CMS tree, site home and about pages, BORIS organisations, inventory xlsx | P0 |
| C | Expertise, methods and technologies | Does anyone work on CGM, biosensing, MRI, CRISPR? | topic (term, synonyms, lay terms, EN/DE) | "Research interests" on profiles, group pages, BORIS keywords and abstracts, SNSF keywords, disciplines and lay summaries | P0 |
| D | Projects and activities | What have they done that resembles my problem? | project | unit project pages, SNSF grants, ARAMIS (Innosuisse and federal), DCB API, CORDIS | P0 |
| E | Infrastructure and equipment | Can I use an instrument, lab, clean room, biobank, cohort, HPC? | infrastructure | platform sites (ngs, mic, …), equipment and core-facility pages, DBMR, sitem-insel, Biobank Bern, UBELIX docs | P0 |
| F | Services for companies | Who can test, analyse, run a clinical study, consult, calibrate? | service | CTU and CIU on dcr.unibe.ch (already crawled), ARTORG services, unit service pages, sitem-insel, BFH, METAS | P0 |
| G | Technology transfer and collaboration | How do I license, co-develop, found a spin-off? | service (kind tech_transfer), organisation | Unitectra, UniBE Innovation Office, ARTORG technology transfer, spin-off lists | P1 |
| H | Publications and outputs | Proof that they are good at it | publication | BORIS (dim), DCB API, Europe PMC abstracts, SNSF output data | P1 |
| I | Funding and financial support | What money is there, from whom, on what terms? | funding | Innosuisse, SNSF (e.g. Bridge), Bern Economic Development (berninvest.be.ch), be-advanced, sitem-insel voucher and Startup Club | P1 |
| J | Laws, regulation and authorities | Which rules apply, who approves? | regulation, organisation (authority) | Fedlex (federal law by SR number), BELEX (Bern law), Swissmedic, swissethics, Bern cantonal ethics committee | P1 |
| K | Ecosystem and partner organisations | Who else is here to work with? | organisation | Insel Gruppe and its clinics, BFH, sitem-insel, Switzerland Innovation Park Biel/Bienne, CSEM, Swiss Medtech, Agroscope, federal offices | P1 |
| L | Setting up in Bern | Company registration, permits, tax relief, space | service, funding, regulation | berninvest.be.ch, ggba.swiss, be.ch | P2 |
| M | Talent and education | Can I hire or train people here? | program | UniBE and BFH programmes, continuing education (CAS, DAS, MAS), career services | P2 |
| N | News and events | Is this group active now? | news | mediarelations, unit news, sitem-insel and be-advanced posts | P2 |

"Technology available" is split on purpose. The **method or technology** (for example "mass spectrometry") is a topic in C. The **instrument you can book** is infrastructure in E. A query for one finds the other through the `has_expertise` and `operates` links.

Kinds within types (fixed lists, so results can be filtered):

- **infrastructure.kind:** instrument, facility, lab, platform, core_facility, biobank, cohort, dataset, computing, clinical_unit, workspace
- **service.kind:** contract_research, testing_analysis, clinical_study_support, regulatory_advice, consulting, calibration_certification, tech_transfer, incubation, training, recruiting
- **funding.kind:** grant, voucher, loan, guarantee, tax_relief, equity, prize, in_kind, coaching
- **regulation.kind:** federal_act, federal_ordinance, cantonal_act, guideline, standard
- **organisation.kind:** university, applied_university, hospital, research_institute, federal_office, cantonal_agency, regulator, ethics_committee, innovation_park, incubator, cluster, association, investor, tto
- **unit.kind:** faculty, department, institute, clinic, centre, group, lab, platform, office

## 3. Record format

Every record, of every type, has the same envelope. One rule makes results traceable: **every non-empty field has at least one evidence entry, and its quote must appear verbatim in the stored text of that URL.** Code checks this, and failing fields are blanked, not kept.

```json
{
  "id": "person:7f3a9c21e0",
  "type": "person",
  "sections": ["A", "C"],
  "data": {
    "name": "Dominik Obrist",
    "titles": "Prof. Dr.",
    "roles": [{"role": "Professor for Cardiovascular Engineering", "unit_id": "unit:unibe:ins_artorg"}],
    "email": "dominik.obrist@unibe.ch",
    "phone": "+41 31 684 14 22",
    "profile_urls": ["https://www.artorg.unibe.ch/research/cve/group_members/staff/prof_dr_obrist_dominik/index_eng.html"],
    "expertise": ["Biomedical fluid dynamics", "Cardiovascular Engineering", "Fluid-structure interaction"]
  },
  "evidence": [
    {"field": "roles[0].role", "quote": "Professor for Cardiovascular Engineering",
     "url": "https://www.artorg.unibe.ch/research/cve/group_members/staff/prof_dr_obrist_dominik/index_eng.html",
     "page_id": "3c1e…", "extractor": "schema_org_person@1", "fetched_at": "2026-10-18T14:02:11Z"}
  ],
  "source_ids": ["artorg"],
  "collector": "net", "round": 7,
  "confidence": 0.95,
  "status": "draft"
}
```

For API and bulk records, `url` is the record's public landing page (BORIS handle, SNSF grant page, ARAMIS project page). `quote` is the field value as it appears in the API response, and `api_ref` points to the raw file and record id.

`id` is a hash of the identity key: the email, else the profile URL, else the normalised name plus unit. Rerunning an extractor produces the same id, so stage 3 can be rebuilt at any time.

### Fields per type

| Type | Fields (all optional except a name or title and one evidence entry) |
|---|---|
| person | name, name_variants[], titles, roles[{role, unit_id}], email, phone, profile_urls[], orcid, expertise[], status (active, emeritus) |
| unit | names{en,de}, kind, parent_id, institution, urls[], cms_code, address, head_person_ids[], description, expertise[] |
| topic | label{en,de}, kind (method, technology, disease_area, application, discipline), synonyms[], lay_terms[], abbreviations[], broader[] |
| project | title, abstract, lay_summary{en,de}, funder, grant_no, amount_chf, start, end, pi_person_ids[], unit_ids[], partner_orgs[], keywords[] |
| infrastructure | name, kind, description, unit_id, equipment[], access{internal, academic, industry}, booking_url, pricing_url, contact_person_ids[], location |
| service | name, kind, provider_id, description, target (startup, sme, industry, researcher), conditions, contact_person_ids[] |
| funding | name, kind, provider_id, target_group, amount_min, amount_max, conditions, deadline_or_rolling, application_url, legal_basis_ids[], contact |
| regulation | sr_number, short_name, title{de,fr,it,en}, kind, domains[], authority_ids[], eli_uri, url |
| organisation | name, kind, roles[], location, url, contact |
| publication | title, year, authors[{name, affiliation, person_id}], doi, pmid, venue, type, abstract, subjects[], unit_ids[] |
| news | title, date, summary, mentions[] |
| program | name, level, unit_id, language |

Relations go in a `link` table, each with its own evidence URL: member_of, heads, part_of, contact_for, operates, offers, works_on, funded_by, author_of, has_expertise, partner_of, regulated_by, administers, provides, mentions.

## 4. Storage in stages

Each stage reads only the stage before it and can be rebuilt from it. Raw data is never edited.

```
data/
  state/net.sqlite                    control: sources, URL frontier, jobs, rounds (the net's memory)
  raw/<source>/pages/<sha1>.html.gz   stage 1: untouched bytes (new pages gzip; old .html files stay)
  raw/<source>/manifest.jsonl         stage 1: one line per request, same format as today
  raw/boris_dim/  raw/snsf/  raw/aramis/  raw/dcberne_api/  raw/sitem_api/  raw/fedlex/
                                      stage 1: APIs and bulk files
  clean/<source>.jsonl                stage 2: one cleaned page per line
  records/<type>.jsonl                stage 3: draft records with evidence
  kb/bern.sqlite  kb/export/*.jsonl   stage 4: merged, verified, linked (schema from the technical plan)
  index/                              stage 5: embeddings (existing embed.py)
  reports/rounds.jsonl  coverage.json  verify.json  gaps.json
```

### Stage 2: clean page

```json
{"page_id": "3c1e…", "url": "…", "source_id": "artorg", "fetched_at": "…", "lang": "en",
 "title": "…", "text": "…", "headings": ["Curriculum Vitae", "Research Interests", "Publications"],
 "emails": ["dominik.obrist@unibe.ch"], "phones": ["+41 31 684 14 22"],
 "microdata": [{"type": "Person", "name": "Prof. Dr. Dominik Obrist",
                "jobTitle": "Professor for Cardiovascular Engineering", "worksFor": "ARTORG Center …"}],
 "cms": {"path": "fak_medizin/dept_weitere/ins_artorg", "client": "ins_artorg",
         "area_title": "ARTORG Center for Biomedical Engineering Research"},
 "links": [{"url": "…", "anchor": "Group Members"}],
 "page_type": "person_profile", "sections": {"A": 0.93, "C": 0.71}, "relevance": 0.93,
 "twin_of": null, "text_hash": "…"}
```

### Control: net.sqlite

```sql
CREATE TABLE source (
  id TEXT PRIMARY KEY, host TEXT UNIQUE, name TEXT, institution TEXT,
  tier INTEGER, sections TEXT, method TEXT,          -- crawl | wordpress_api | bulk | sparql
  status TEXT,                                       -- candidate | probing | active | exhausted | budget | low_yield | blocked | rejected
  budget INTEGER, fetched INTEGER DEFAULT 0, kept INTEGER DEFAULT 0,
  rate_group TEXT, path_allow TEXT, path_deny TEXT,
  added_by TEXT, reason TEXT, updated_at TEXT);
CREATE TABLE url (
  url TEXT PRIMARY KEY, source_id TEXT, status TEXT, -- queued | fetched | robots | skipped | error | dead
  priority REAL, depth INTEGER, section TEXT, found_on TEXT, anchor TEXT,
  reason TEXT,                                       -- why the net went here, e.g. "gap:profile:obrist_dominik"
  attempts INTEGER DEFAULT 0, http_status INTEGER, file TEXT, text_hash TEXT,
  page_type TEXT, relevance REAL, fetched_at TEXT);
CREATE INDEX url_queue ON url(status, source_id, priority DESC);
CREATE TABLE job (id TEXT PRIMARY KEY, kind TEXT, status TEXT, cursor TEXT, done INTEGER, total INTEGER, updated_at TEXT);
CREATE TABLE round (n INTEGER PRIMARY KEY, started TEXT, finished TEXT, fetched INTEGER, kept INTEGER,
  new_records TEXT, frontier INTEGER, free_gb REAL);
CREATE TABLE mention (host TEXT, url TEXT, found_on TEXT, anchor TEXT);  -- external links we record but do not follow
```

Open it in WAL mode with a 30 s busy timeout. The crawler is the only writer of `source`, `url` and `round`; the bulk process writes only `job`.

The `reason` column is the net's audit trail: for every page we can say why it was fetched. It is worth showing in the pitch.

## 5. The net loop

```
   registry (sources.json + taxonomy.json)
            │
            ▼
  ┌──── frontier (net.sqlite) ◄──────────────────────────────────────────┐
  │                                                                       │
  ▼                                                                       │
 CAST ──► CLEAN ──► JUDGE ──► EXTRACT ──► EXPAND ─────────────────────────┘
 fetch    html →     type,      rule        score links, add new hosts,
 next N   page       relevance, records     apply gap boosts
 by       (stage 2)  keep?      (stage 3)
 priority
                       once per round: GAPS + REPORT + stop rules + disk check
```

A **round** is 500 fetches or 10 minutes, whichever comes first. CLEAN, JUDGE, EXTRACT and EXPAND run inline for each page and take milliseconds. GAPS and REPORT run once per round. One asyncio process does all of it.

### 5.1 Seed (once, idempotent)

1. Import every existing `manifest.jsonl` row as `fetched`, so nothing is downloaded twice.
2. Run CLEAN and JUDGE over the 15,419 saved pages (about 5 minutes) and EXPAND their links. This puts the 13,370 unfetched links into the frontier with real priorities.
3. Add the 500 linked `*.unibe.ch` hosts as `candidate` sources, minus the portal exclude list in discover.py.
4. Load the sources.json tiers (§6) and the bulk jobs (§5.7).

### 5.2 Cast: scheduling and politeness

- One request at a time per host, 1.0 s apart. Honour `Crawl-delay`.
- **Rate groups** share a cap. All `*.unibe.ch` hosts run on one CMS, so that group gets 3 requests/s in total (env `UNIBE_RPS`). `*.insel.ch` gets 1/s. Every other host gets 1/s.
- Up to 16 hosts in flight.
- robots.txt through the existing parser. Blocked URLs are recorded, not fetched.
- On 429 or 503, pause that host for 10 minutes, doubling each time. After three network errors a URL is `dead`.
- **Section quotas** per round (should-have): A 30%, B 10%, C+D 20%, E+F+G 20%, I–L 10%, H+M+N 10%. Unused quota flows to the others. Without quotas, news archives eat the budget.

### 5.3 Clean

Upgrade extract.py:

- Run `html.unescape` before the email regex, and decode the `String.fromCharCode(…)` mailto links.
- Parse `itemprop` microdata and JSON-LD.
- Read the UniBE CMS markers: `/unibe/portal/<path>/` in asset URLs, the `client-<code>` body class, `h2.area-title` and the breadcrumb.
- Keep the anchor text of each link (EXPAND needs it) and the headings.
- Take the language from `_eng`/`_ger` in the URL or from `<html lang>`.
- If the text is under 200 characters and the page is mostly scripts, set `page_type=needs_browser`. Playwright handles those later, not tonight.

### 5.4 Judge: is this page important?

Rules first, embeddings second, and Apertus only for the doubtful pages (tomorrow).

| page_type | Rule markers | Base score | Feeds |
|---|---|---|---|
| person_profile | `article.team-detail` with schema.org Person; WordPress `team` post; one name heading plus email plus "Research interests" | 0.9 | A, C |
| people_list | 3+ Person microdata items, or 5+ emails, or URL words team/people/personen/mitarbeitende | 0.8 | A, B |
| infrastructure | equipment, geräte, instrument, facility, platform, core, infrastruktur, lab | 0.7 | E |
| service | services, dienstleistung, angebot, analysis, testing, booking, tarife, prices, for companies | 0.7 | F, G |
| funding | funding, förderung, grant, voucher, cheque, beitrag, darlehen, steuererleichterung | 0.7 | I |
| regulation | gesetz, verordnung, ordinance, approval, bewilligung, ethik, "SR 8…" | 0.7 | J |
| unit_home | site root or section index; `area-title` present | 0.6 | B |
| research_group | `/research/` or `/forschung/` plus group, gruppe or lab | 0.6 | B, C, D |
| project | project or projekt in the URL; headings Duration/Laufzeit, Funding, Partners | 0.6 | D |
| publication_list | publications, publikationen | 0.4 | H |
| news | news, aktuell, medienmitteilung | 0.2 | N |
| event, teaching, admin | events, agenda, studium, lehre, kurs, formulare | 0.1 | M or none |

Then:

- **Rule score** = min(1, base score + 0.1 × section keyword hits in URL, title and headings). The words per section live in taxonomy.json, in English, German and French.
- **Embedding score** (should-have tonight): after each round, embed the title, headings and first 300 words of the new pages with the existing multilingual-e5-small on the GPU (a few seconds per round). Compare them with 2–3 prototype sentences per section and take the best. e5 cosines sit between about 0.7 and 0.9, so rescale: `score = clip((cos − 0.75) / 0.15, 0, 1)`, and tune the numbers on the dry run.
- `relevance = max(rule score, embedding score)`. A page is **kept** if relevance ≥ 0.35 or its type feeds a P0 section. Pages that are not kept are still stored, since raw is cheap, but their links get low priority.

### 5.5 Extract (rules, inline)

| Extractor | Input | Output |
|---|---|---|
| schema_org_person | person_profile pages | person: name, titles, role, affiliation chain, email, phone, address, the list under "Research interests"; ORCID and Scholar links as identifiers |
| people_list | people_list pages | person stubs (name, function, profile URL); each profile URL is queued at top priority |
| unit_cms | every UniBE page | unit tree from the CMS path and client code; names from the area title and breadcrumb |
| block_candidates | infrastructure, service, funding and regulation pages | heading plus list items under headings such as Equipment, Geräte, Services, Angebot, Access, Prices; marked `needs_llm` for tomorrow |

Apertus extraction (the existing enrich.py prompt, split per record type) runs tomorrow, only on `needs_llm` pages with relevance ≥ 0.5. We expect 5,000–15,000 such pages. If an endpoint is up tonight, a second worker can start on them.

### 5.6 Expand: where to go next

Each outgoing link gets a priority, and higher goes first. The weights live in taxonomy.json, so they can be tuned without code changes.

```
priority =  1.0 × tier weight of its source         (tier 0: 3, tier 1: 2, tier 2: 1)
         +  1.5 × relevance of the page it was found on
         +  0.6 × keyword hits in URL + anchor       (capped at 3)
         +  2.5 × gap boost                          (0–1, from the gap engine)
         +  2.0 × new-unit bonus                     (first 25 pages of every newly accepted unit)
         −  0.35 × depth
         −  3.0 if it is the German twin of an English page we already have
         −  2.0 × trap score                         (calendar, pagination past 20, >2 query parameters, template over its cap)
```

The new-unit bonus applies the fairness rule from the challenge's ethics section. Every unit gets its home, about, people, research and services pages fetched, however small it is.

Before scoring, each URL is normalised: lower-case host, `www.` removed, fragments and `utm_*` dropped, query sorted, length capped at 300. A "template" is the host plus the path with digits replaced; each template is capped at 200 URLs.

Links to new hosts:

| Host | Action |
|---|---|
| `*.unibe.ch`, not yet a source | add as `candidate`. Once it is linked from 2+ kept pages, probe its homepage (1 request). Accept it if it looks like a unit (area title, research or people words) and is not a portal; otherwise mark it `rejected` with the reason |
| host of a tier-1 or tier-2 registry entry | queue, within that entry's `path_allow` and budget |
| any other host | store in `mention` only, never followed. Tomorrow `net status` lists the most-mentioned `.ch` hosts for a person to add |

Social networks, Outlook, DOI resolvers and publisher sites are always `mention` only.

### 5.7 Bulk jobs (separate process, resumable)

| Job | Endpoint | What we keep | Feeds |
|---|---|---|---|
| BORIS re-harvest in `dim` | `boris-portal.unibe.ch/server/oai/request?verb=ListRecords&metadataPrefix=dim` | title, authors in order, per-author affiliation, organisation, DOI, PMID, publisher DOI, abstract, subjects, type, year; each response gzipped | A, B, C, H |
| SNSF grants | `data.snf.ch/datasets/grants_with_abstracts.csv` (432 MB) | rows whose `InstituteCity`, `ResearchInstitution` or `Institute` points to Bern; applicant, keywords, abstract, EN/DE lay summaries | D, A, C |
| SNSF outputs | `data.snf.ch/datasets/output_data_knowledgetransfer.csv`, `output_data_collaborations.csv` | rows belonging to the Bern grants | D, G |
| ARAMIS | `datenausgabe.aramis.admin.ch/full_export.json` | federal and Innosuisse projects that name a Bern institution or contact | D, I |
| Diabetes Center Berne | existing dcb_api.py | team, projects, publications | A, D, H |
| sitem-insel | `sitem-insel.ch/wp-json/wp/v2/` (types listed at `/wp-json/`) | pages and posts | E, F, I, K |
| Fedlex | `fedlex.data.admin.ch/sparqlendpoint` | title in four languages and ELI URI for each SR number in the regulation seed list | J |
| PDFs (last) | existing pdfs.py | only PDFs linked from kept E, F, I and J pages; at most 20 MB each | E, F, I, J |

The SNSF lay summaries matter for success criterion 2. They describe each project in plain English and German, which is the vocabulary a company uses in its query. Log the distinct values of the institution columns on the first run, so the Bern filter can be checked by eye.

**Regulation seed list.** Each number is resolved through SPARQL, so a wrong number is flagged rather than guessed: HMG 812.21, MepV 812.213 (tested), IvDV 812.219, HFG 810.30, HFV 810.301, KlinV 810.305, KlinV-Mep 810.306, DSG 235.1, TSchG 455, TSchV 455.1, ESV 814.912, FrSV 814.911, FIFG 420.1, PatG 232.14, AIG 142.20, VZAE 142.201, HRegV 221.411. For the canton, the economic development law (WFG) and the innovation promotion law (IFG) are looked up in BELEX. We store titles, scope and the responsible authority, and link to the official text. We do not summarise or interpret law.

### 5.8 Gaps: the net looks for what is missing

At the end of each round:

| Gap | How we detect it | What the net does |
|---|---|---|
| A known person has no profile | a BORIS author with a UniBE affiliation, an SNSF applicant or a people-list stub that matches no person_profile | boost frontier URLs whose slug contains the name (UniBE slugs look like `prof_dr_obrist_dominik`); people-list stubs queue their own link directly |
| A unit has no people | unit home fetched, 0 person records | boost that unit's links whose anchors say team, people, personen, mitarbeitende, staff, members or about us |
| A unit has no research or services page | same | boost links with research/forschung or services/angebot/infrastructure anchors |
| An organisation name has no unit | a BORIS or SNSF organisation that matches no unit | find links whose anchor matches the name (fuzzy ≥ 0.85); a `*.unibe.ch` host is promoted to candidate |
| A section starves | fewer than 2 new records per 100 fetches for 3 rounds while its queue is not empty | raise its quota; if its queue is empty, report the section as exhausted |

### 5.9 Stop rules

- A **source** stops when no queued URL has priority ≥ 1.0, when its budget is reached, or when its keep ratio stays under 3% for 200 fetches (`low_yield`).
- The **net** stops with exit code 0 when all tier-0 and tier-1 sources have stopped and all bulk jobs are done.
- **Safety:** it stops with exit code 3 when free disk falls under 15 GB, and also stops at the `--hours` limit.

Every source status change is written with its reason, so the morning report shows why each site ended.

## 6. Source registry

Adding an institution is one entry in sources.json (success criterion 6). The new fields are optional: `tier`, `sections`, `budget`, `method`, `path_allow`, `path_deny`, `rate_group`.

```json
{"id": "sitem", "name": "sitem-insel", "url": "https://sitem-insel.ch/", "institution": "sitem-insel",
 "tier": 1, "sections": ["E", "F", "I", "K"], "budget": 400, "method": "wordpress_api+crawl",
 "path_deny": ["/fr/"], "rate_group": "sitem"}
```

| Tier | Sources | Budget per source |
|---|---|---|
| 0 | the 42 inventory sites, ARTORG, Diabetes Center Berne | 3,000 pages (www.unibe.ch 5,000; mediarelations 800) |
| 1 | discovered `*.unibe.ch` sites; Insel clinics relevant to the demo (udem, kardiologie, neurologie); sitem-insel; Unitectra; berninvest.be.ch; be-advanced; Innosuisse funding pages; Swissmedic medical-device and clinical-trial paths; swissethics; BFH research pages; Biobank Bern | 800 (Insel and federal sites 300, with `path_allow`) |
| 2 | Switzerland Innovation Park Biel/Bienne, CSEM (Bern pages only), METAS, IPI (ige.ch), Swiss Medtech, ggba.swiss, Agroscope, UBELIX docs | 150–300, with `path_allow` |

All of these hosts answered on 2026-10-18. The Bern cantonal ethics committee's own page has not been found yet; the net should reach it from swissethics.ch.

## 7. Size, time and safety

| Item | Estimate |
|---|---|
| Throughput | UniBE group at 3/s ≈ 10,800 pages/hour, plus other hosts in parallel |
| Pages tonight | 80,000–130,000 in 12 hours; tier 0 should be exhausted first |
| Raw HTML, gzip | about 1–1.5 GB (40 KB per page, about 5× compression) |
| Clean JSONL | about 1–1.5 GB |
| BORIS dim | about 1.5 GB of XML, about 0.3 GB gzipped |
| SNSF and ARAMIS | about 0.5 GB |
| PDFs | capped at 3 GB |
| Embeddings | about 0.6 GB |
| **Total** | **about 8 GB.** The guard stops at 15 GB free; 70 GB is free now, so no cleanup is needed |

The rules from the technical plan still hold. Obey robots.txt. Identify the crawler in the User-Agent and add a team contact address. Use public pages only, with no logins. Keep only the professional contact data an institution publishes (nDSG). Raw data stays in `data/`, which git ignores. Social profiles are recorded as mentions and never fetched.

## 8. Code plan

New package `src/navigator/net/`. The existing modules stay and are reused.

| File | Job | Reuses | Needed tonight? |
|---|---|---|---|
| net/db.py | net.sqlite schema and helpers (enqueue, pick next, mark) | – | yes |
| net/fetch.py | async fetch with rate groups and backoff; gzip raw; manifest line | crawl.py, robots.py | yes |
| net/runner.py | round loop, reports, stop rules, disk guard, `--hours` | crawl.Reporter | yes |
| net/clean.py | html → stage-2 page (entities, emails, microdata, CMS markers, anchors, language) | extract.py | yes |
| net/judge.py | page_type rules and section keyword scores; embedding scorer per round | embed.encode | rules yes, embeddings should |
| net/expand.py | URL normalisation, traps, priority formula, new-host handling | – | yes |
| net/extractors.py | schema_org_person, people_list, unit_cms, block_candidates | – | person and list yes |
| net/seed.py | import manifests, saved pages, candidate hosts, registry | discover.HOST_RE | yes |
| net/bulk.py | BORIS dim, SNSF, ARAMIS, DCB, sitem, Fedlex as resumable jobs | boris.py, dcb_api.py | yes |
| net/gaps.py | gap engine (§5.8) | – | profile and unit gaps should |
| src/taxonomy.json | sections, words in EN/DE/FR, prototypes, weights, quotas, thresholds | – | yes |
| src/sources.json | tier-1 and tier-2 entries | – | yes |

Also make pages.py and discover.py read `.html.gz`, so embed.py keeps working until it reads from `clean/`.

CLI, in `__main__.py`:

```
python -m navigator net seed                # §5.1, idempotent
python -m navigator net run --hours 14      # the loop; resumable; exit 0 = done, 3 = disk guard
python -m navigator net bulk                # §5.7 jobs, resumable
python -m navigator net status              # sources by status, frontier by section, records by type, top gaps, top mentions
python -m navigator net process             # tomorrow: extract-all → merge → verify → kb → index
```

Two existing bugs get fixed on the way: each URL maps to the source of its exact host (this stops www.unibe.ch wandering), and entities are decoded before emails are collected.

## 9. Tonight: 17:45 – 20:00

Three workstreams. With fewer people, work in this order: W1, then the bulk part of W3, then W2, seed, expand. Skip gaps and quotas.

| Time | W1 (net core) | W2 (clean, judge, extract) | W3 (bulk, seed, registry) |
|---|---|---|---|
| 17:45–18:45 | db.py, fetch.py, runner.py | clean.py, judge.py rules, taxonomy.json | bulk.py; **start the BORIS dim harvest as soon as it runs** |
| 18:45–19:25 | expand.py, wiring in runner | extractors.py (person, list, unit) | seed.py; tier-1 and tier-2 entries in sources.json |
| 19:25–19:45 | dry run together: 15 minutes, all tiers | | |
| 19:45–20:00 | launch (§10) | | |

Done-when tests:

- **W1:** `net run --hours 0.05` fetches from 3 sites. After Ctrl+C and a restart, nothing is fetched twice.
- **W2:** on 20 saved pages, the page types look right, emails are decoded, and profile pages give person records whose quotes are found in the text.
- **W3:** BORIS dim pages are landing in `raw/boris_dim/`, and `net status` shows the frontier by section.

Go/no-go before launch:

- [ ] A restart after Ctrl+C refetches nothing.
- [ ] The UniBE group stays at or under 3 requests/s (check rounds.jsonl).
- [ ] robots.txt blocks are counted, not fetched.
- [ ] The disk guard fires when its threshold is set above the current free space.
- [ ] Tier-2 `path_allow` is respected.
- [ ] Each round writes a report line.

**Fallback if the net is not running by 19:15.** About 30 minutes of changes to the existing code:

1. Fix the www host bug, let `discover.py` keep sub-subdomains, and run `discover --min-links 2`.
2. Run `crawl --max-pages 3000` for all sources; it resumes from the manifests.
3. Give boris.py an `out_dir` and `prefix="dim"`, and start it.
4. Download the SNSF and ARAMIS files.

That still collects most of the raw data tonight. Cleaning, judging and gaps then run offline tomorrow on the cached pages, because every stage reads from disk.

## 10. Overnight runbook (Windows)

```powershell
# keep the laptop awake on mains power, also with the lid closed
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; powercfg /setactive SCHEME_CURRENT
# then: Settings > Windows Update > Pause updates, so there is no reboot tonight
```

Terminal 1, bulk jobs:

```powershell
$env:PYTHONPATH = "src"; python -m navigator net bulk
```

Terminal 2, the net, restarted after any crash (safe because it resumes):

```powershell
$env:PYTHONPATH = "src"
while ($true) { python -m navigator net run --hours 14; if ($LASTEXITCODE -in 0, 3) { break }; Start-Sleep 30 }
```

Tomorrow, undo the power settings: `powercfg /change standby-timeout-ac 30`, and set the lid action back to sleep.

## 11. Tomorrow morning

1. `net status`: what was fetched, why each source stopped, the top gaps, and the most-mentioned hosts worth adding.
2. `net process`, in this order:
   1. Extract all records from stage 2 and the bulk files.
   2. Run Apertus on the `needs_llm` pages.
   3. Normalise and merge on email, profile URL, then name plus unit; BORIS dim affiliations link authors to people.
   4. Build the links.
   5. Write expertise terms and EN/DE/lay synonyms per topic with Apertus, cached per term.
   6. Run the **verify gate**.
   7. Build bern.sqlite with FTS5, then embeddings per record.
3. Check the success criteria:

| Criterion | Where the data supports it | Check |
|---|---|---|
| 1. Right people in the top 10 | person records from all profiles and lists; BORIS links authors to units | recall@10 on a gold set of expected experts per bench query, written by hand from the sites |
| 2. Different wording | research-interest terms, SNSF keywords and EN/DE lay summaries, topic synonyms, multilingual embeddings | the same experts for "glucose sensors", "CGM" and "biosensing" |
| 3. Traceable | field-level evidence with verbatim quotes | verify.json: 100% of kept fields have a matching quote |
| 4. Structured | typed records with required fields | coverage.json: share of filled fields per type and source |
| 5. Three sources | tier 0 with a protected budget; DCB API plus crawl | record counts for UniBE, ARTORG and DCB |
| 6. Easy to extend | one sources.json entry; sections in taxonomy.json | add a new site live in the demo |

## Open questions

- [ ] Is an Apertus endpoint available overnight? If yes, start the `needs_llm` worker tonight.
- [ ] How many of us code tonight, and who takes W1, W2 and W3?
- [ ] Insel clinics as tier 1 (recommended, for the clinical-validation demo query) or tier 2?
- [ ] Gold set for criterion 1: who writes the expected experts for each bench query?

## Sources

Endpoints and hosts were checked directly on 2026-10-18: BORIS OAI-PMH formats (`dim` tested), the Fedlex SPARQL endpoint (tested with SR 812.213), the SNSF and ARAMIS downloads, the sitem-insel WordPress API, and the homepages in §6.

- [SNSF Data Portal exports on opendata.swiss](https://opendata.swiss/en/dataset/snsf-data-portal-exports)
- [ARAMIS on opendata.swiss](https://opendata.swiss/en/dataset/aramis)
- [Innosuisse: innovation projects](https://www.innosuisse.ch/inno/en/home/start-your-innovation-project/innovation-projects.html)
- [University of Bern: innovation ecosystem](https://www.unibe.ch/innovation/innovationunibe/ecosystem/index_eng.html)
- [University of Bern: Unitectra technology transfer](https://www.unibe.ch/research/advisory_services/technology_transfer/unitectra/index_eng.html)
- [CTU Bern](https://ctu.unibe.ch/about_us/index_eng.html)
- [Swissmedic: clinical investigations with medical devices](https://www.swissmedic.ch/swissmedic/en/home/medical-devices/klinische-versuche/klinische-pruefungen.html)
- [GGBa: Bern's ecosystem for life-sciences innovation](https://ggba.swiss/en/berns-thriving-ecosystem-for-life-sciences-innovation/)
- [Bern Economic Development: Bern Capital Area](https://www.berninvest.be.ch/de/start/berncapital-area.html)
- [CORDIS services and bulk downloads](https://www.cordis.europa.eu/about/services)
