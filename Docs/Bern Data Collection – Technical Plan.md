# Bern Data Collection – Technical Plan

> Historical design for bulk collection. The current focused implementation is documented in [Focused Crawler](Focused%20Crawler.md). It uses local rules without Apertus, retains at most 500 unreviewed research candidates, and does not execute the full-harvest or in-depth-researcher workflow described below.

Oct 18, 2026 · @Sam

## At a glance

Two collectors feed one Bern dictionary. The static collector reads all sources once. The in-depth researcher digs deeper for each request and adds what it finds.

&#91;embedded content: collection architecture · 2 collectors, 1 dictionary\]

Both collectors share the same extraction and verification. Every record in the dictionary keeps the public URL it came from.

## Inputs and targets

Our part ends at the Bern data. The company profile and the website are not designed yet, so the in-depth researcher accepts a small, neutral **research request** that any later frontend can fill.

### Inputs

| Collector | Input | Fields |
| --- | --- | --- |
| Static dictionary | Source registry | One record per site: id, url, institution, hosts, coverage (from the xlsx plus a config file) |
| Static dictionary | Target list | The record types below, and which page types feed each |
| In-depth researcher | Research request | topics\[\] (free terms, any language), labels\[\] (taxonomy, optional), seed\_ids\[\] (dictionary records to dig into, optional), budget (pages, seconds), allow\_external (true or false) |

### Targets: the records we must produce

| Record | Fields | Found on |
| --- | --- | --- |
| Unit | name, type, institution, parent, description, expertise\[\] | Home and "about" pages of each site |
| Person | name, role, units\[\], email, expertise\[\], profile\_url | Team lists and profile pages |
| Publication | title, year, authors\[\], venue, DOI, abstract, topics\[\] | Publication lists on profile and group pages, then publication databases |
| Infrastructure or service | name, kind, description, external access, contact | Facility, platform and service pages |
| Project | title, description, period, units\[\], people\[\] | Project and research pages |
| News item | title, date, summary, units\[\], people\[\] | News pages and mediarelations.unibe.ch |

Every record also carries source\_urls\[\], fetched\_at and a collector tag (static or researcher).

## The toolbox

Data collection combines three kinds of tool. **Crawlers** download web pages. **APIs** return clean, structured data from systems built to share it. **The LLM** (Apertus) reads text that has no structure and turns it into records. The rule is to prefer APIs, crawl what has no API, and use the LLM only where reading is needed. Rows marked "tested" were checked on 2026-10-18.

### How data is fetched

| Tool | What it is | What we use it for | Kind | Status |
| --- | --- | --- | --- | --- |
| HTTP crawler (Python httpx, already in our prototype) | A program that downloads a page, finds its links and downloads those, within one site | The 42 UniBE sites and ARTORG: units, team lists, profiles, facilities, news | Web scraping | Tested on 3 sites |
| robots.txt | Each site's rules for crawlers | UniBE's file forbids search, print, navigation and sitemap pages; we obey it | Rules file | Tested |
| Headless browser (Playwright) | A real browser driven by code, for pages built by JavaScript | Only if a site shows no text to the plain crawler | Web scraping | Not needed so far: UniBE pages are plain HTML |
| WordPress REST API on dcberne.com | Diabetes Center Berne's site serves its content as JSON | Team (11 entries), projects (15), publications (40), news posts | REST API, no key | Tested |
| OAI-PMH on BORIS | The standard protocol libraries use to hand out catalogue records page by page | All 175,932 UniBE publication records, each with title, authors, year, DOI and UniBE unit name | Harvesting API, no key | Tested |
| Europe PMC REST API | Free biomedical literature database | Abstracts for medicine, ARTORG and diabetes papers; 50,443 records with a University of Bern affiliation | REST API, no key | Tested |
| Crossref REST API | The DOI registry | Look up one paper by DOI or title; fill missing year, venue, abstract | REST API, no key | Tested (affiliation search is too fuzzy to use) |
| OpenAlex API | Open database of papers, authors, topics and citations | Topics and co-authors per paper | REST API; free key needed since February 2026, with about $1/day of free use | Optional |

The BORIS REST API answered "Access Restricted". BORIS also lists Person, Instruments and Projects collections, but OAI-PMH returns no records for them. People and facilities must therefore come from the unit websites.

### How data is read and stored

| Tool | What it is | What we use it for | Runs where |
| --- | --- | --- | --- |
| HTML-to-text (BeautifulSoup now; trafilatura is an option) | Strips menus and footers, keeps the main text | Every crawled page | Local |
| Apertus v1.5 through an OpenAI-compatible endpoint | The LLM, called with a prompt and returning JSON | Read a page and fill records; classify pages; plan research; judge if two names are the same person | Our own server (vLLM or similar) |
| Embedding model (e.g. BGE-M3 or multilingual-e5) | A small model that turns text into vectors so similar meanings sit close together | Search that finds "CGM" for "glucose sensor", in German and English | Local CPU or GPU |
| PDF reader (PyMuPDF; GROBID for scientific papers) | Extracts text and, for GROBID, title, authors and sections | Only if we decide to read open-access full texts | Local; GROBID runs in Docker |
| SQLite with FTS5 | One database file with built-in keyword search | Store all records, links and pages | Local |
| Self-hosted web search (SearXNG) | A search engine we run ourselves that queries public engines | In-depth researcher level 3 only | Our server, but its queries reach public engines |

## Static dictionary: collection pipeline

The static dictionary is built once, in eight steps. Only steps 5 and 6 use the LLM; the rest is ordinary code. Raw pages are saved to disk after step 3, so later steps can be rerun without downloading again.

| # | Step | How | Tool | LLM? | Output |
| --- | --- | --- | --- | --- | --- |
| 1 | Load sources | Read the xlsx and the config file, merge duplicates (geo/geo2, ARTORG, DCB) | Python, openpyxl | No | Source records |
| 2 | Discover pages | Start at each homepage and follow links on the same site. UniBE has no usable sitemap, so links are the only map. Pages whose URL suggests people, research, services, projects, publications or news are fetched first. | Crawler queue with priorities | No | URL list per site |
| 3 | Fetch | Download each page, obey robots.txt, wait about 1 s between requests to one site, run several sites in parallel, save the raw HTML. For dcberne.com, call the WordPress API instead. | httpx; WordPress REST API | No | Raw pages on disk |
| 4 | Clean | Remove menus and footers; keep title, main text, language, links, emails; hash the text to spot duplicates and German/English twins | BeautifulSoup or trafilatura | No | Page records |
| 5 | Classify | Rules first (URL words such as team, mitarbeitende, forschung, services; number of emails). Ask Apertus only when the rules are unsure. | Rules + Apertus | Sometimes | page\_type per page |
| 6 | Extract | Send each page with a prompt for its type and ask for JSON matching our schema. Split long pages into parts. | Apertus | Yes | Draft Unit, Person, Infrastructure, Project, News records |
| 7 | Verify | Keep a name, project or facility only if it appears in the page text; keep an email only if it is on the page | String matching | No | Verified records |
| 8 | Hand on | Pass verified records and pages to processing (below) | — | — | Dictionary input |

### Example of step 6

Apertus receives the page text and a schema, and returns only what the page says:

```json
{
  "page_type": "team_list",
  "unit": "<group name from the page>",
  "people": [
    {"name": "<as written on the page>", "role": "Professor", "email": "<from the page>",
     "expertise": ["biosensors", "wearable devices"]}
  ],
  "infrastructure": [],
  "projects": ["<project title from the page>"]
}
```

### Size and time

| Item | Estimate | Basis |
| --- | --- | --- |
| Sites | 42 | Inventory |
| Pages per site | 50–150 page budget | To be tuned after a first full run |
| Pages in total | Up to about 4,000–6,000 | Budget × sites |
| Download time | Well under an hour | About 1 page/s per site, 6–8 sites in parallel |
| Apertus extraction time | Unknown | Depends on our endpoint, so measure it on 50 pages first |

## Publications

Use BORIS as the backbone: it already lists every UniBE publication with its authors and unit, so we do not need to find each paper one by one. Publication lists on web pages fill the gaps, mainly Diabetes Center Berne and recent papers. Abstracts are enough to describe expertise; full texts are optional.

### Two routes

|  | Route A: from the web pages | Route B: from BORIS |
| --- | --- | --- |
| Start | Publication list on a profile or group page | OAI-PMH harvest of all 175,932 BORIS records |
| Gives | Papers a person chose to show, already tied to that person | Every paper, with author names, year, DOI and UniBE unit |
| Effort | Parse each list (formats differ per site) | One harvesting loop; filter locally, e.g. to 2019 onwards |
| Weak spot | Lists are often outdated, partial or PDFs | Author names must be matched to people ("Müller, A.") |
| Use for | Diabetes Center Berne (its WordPress API lists 40 publications); people missing in BORIS | Everything at UniBE, ARTORG included |

### Steps

1. **Harvest.** Page through BORIS with OAI-PMH (`verb=ListRecords`, following the resumption token). Save every record. Keep title, authors, year, type, DOI, unit name and handle URL.
2. **Filter.** Keep recent years and research types (articles, conference papers, patents). Drop administrative entries.
3. **Enrich.** For each DOI, ask Europe PMC (biomedical) or Crossref (all fields) for the abstract and venue. These are simple REST calls, one per paper, with no LLM.
4. **Parse web lists (Route A).** On profile pages, find DOIs with a pattern match first. Ask Apertus to split the remaining reference strings into title, authors and year, then look those up in Crossref by title.
5. **Link to units.** Map the BORIS unit name (e.g. "Institute for the Science of Religion") to our Unit records with a name table.
6. **Link to people.** Compare normalised author names (surname plus first initial) with Person records in the same unit. One clear match is linked; several candidates go to Apertus to judge from the unit and topic; still unclear means the paper stays unlinked.
7. **Describe expertise.** Ask Apertus to summarise each person's recent titles and abstracts into 5–10 expertise terms. Each term keeps the ids of the papers it came from.

### Full texts: levels

| Level | What we collect | Benefits | Downsides |
| --- | --- | --- | --- |
| 1 | Titles only | Instant | Weak evidence of expertise |
| 2 | Titles and abstracts | Enough to describe expertise and match synonyms; small | Abstracts missing for some fields, e.g. humanities |
| 3 | Open-access full texts (BORIS open-access set, Europe PMC), read with GROBID | Methods, equipment and data sets named in papers | Large downloads; licences differ per paper; slow to process |

## In-depth researcher

The researcher starts from a research request, finds the best matches in the dictionary, and then digs deeper into just those matches: full profiles, recent papers, related news, facility details. It returns an **evidence bundle** of extra records, each with its source URL. Recommended: level 2, a fixed recipe, with level 3 shown only on prepared examples.

### The research loop

1. **Plan.** Apertus turns topics\[\] into search terms in English and German, and picks the record types that matter for the labels.
2. **Search the dictionary.** Keyword and embedding search returns candidate units, people and facilities.
3. **Find gaps.** For each of the top candidates, list what is missing: no recent papers, no facility access details, a profile too thin to support a claim.
4. **Deep fetch.** Fill those gaps:
   - the full profile page and pages linked from it, beyond the static crawl's page budget;
   - the person's BORIS records, from our local harvest;
   - recent papers by author name and topic from the Europe PMC API;
   - news items in the dictionary that mention the unit or person.
5. **Extract and verify.** Same as static steps 4–7: clean, extract with Apertus, keep only what the page contains.
6. **Check.** Stop when every gap is filled or the budget (pages, seconds) is spent. At level 3, Apertus decides whether another round is worth it.
7. **Return.** The evidence bundle. It can also be saved into the dictionary, so the next request on the same topic is faster.

### What "agent" means here

At level 3 the researcher is an **agent**: Apertus is given a list of tools (search\_dictionary, fetch\_page, search\_europepmc, web\_search). It answers with which tool to call and with what input; our code runs the tool and returns the result to Apertus; this repeats until it stops or the budget ends. At level 2, our code follows the fixed recipe above and Apertus only reads and extracts.

### Levels

| Level | Method | Benefits | Downsides |
| --- | --- | --- | --- |
| 1 | No researcher; answer from the dictionary | Fast, predictable | Only as deep as the static crawl |
| 2 | Fixed recipe for the top 5–10 matches: profile and linked pages, BORIS records, Europe PMC recent papers | Predictable time (seconds); no web search; easy to trace | Cannot find facts outside known sites and APIs |
| 3 | Agent loop with tools, including self-hosted web search, within a budget of e.g. 30 pages or 2 minutes | Finds news, partners and facts we never crawled | Slower; can loop or wander; search queries leave our server; more to verify |

### Guard rails

- The researcher only fetches URLs that appeared in a fetched page, an API result or a search result. Apertus may not invent URLs.
- Search queries hold only topic terms, never text from a company's private document.
- Every record is tagged collector=researcher with the request id, so it can be traced or deleted.

## Processing

Processing turns verified records from both collectors into one linked, searchable Bern dictionary: a single SQLite file (bern.sqlite) plus a JSON export for the rest of the team. It has seven steps. The LLM is used only to judge unclear merges and to write expertise terms.

| # | Step | What happens | Tool | LLM? |
| --- | --- | --- | --- | --- |
| 1 | Normalise | Strip titles (Prof. Dr.), unify spellings (ü and ue), map German and English unit names to one form, parse dates | Python | No |
| 2 | Deduplicate pages | Same text hash = same page; link German and English twins | Python | No |
| 3 | Merge entities | Same email = same person. Otherwise, the same normalised name in an overlapping unit = probably the same person, sent to Apertus to confirm. Unit names from BORIS and from websites map through a name table | Python + Apertus | For unclear cases |
| 4 | Link | Store relations: person member\_of unit, person author\_of publication, unit operates infrastructure, person works\_on project, news mentions unit or person. Each link keeps the URL that shows it | Python | No |
| 5 | Describe | Write 5–10 expertise terms per person and unit from their pages and abstracts, plus English and German synonyms. Each term keeps the ids of its evidence | Apertus | Yes |
| 6 | Index | Keyword index on all text (SQLite FTS5). One embedding vector per record, built from its summary and expertise terms | SQLite, embedding model | No |
| 7 | Check quality | Count records per source and per unit. Find records without a source URL (must be 0) and people without a unit. Flag thin units so small units are not invisible | Python | No |

### Storage

```sql
CREATE TABLE source  (id TEXT PRIMARY KEY, name TEXT, url TEXT, institution TEXT, coverage TEXT);
CREATE TABLE page    (id TEXT PRIMARY KEY, source_id TEXT, url TEXT, title TEXT, lang TEXT,
                      page_type TEXT, text TEXT, hash TEXT, fetched_at TEXT);
CREATE TABLE record  (id TEXT PRIMARY KEY, type TEXT,          -- unit, person, publication, ...
                      data JSON, collector TEXT, request_id TEXT);
CREATE TABLE evidence(record_id TEXT, page_id TEXT, url TEXT);  -- every record → its pages
CREATE TABLE link    (from_id TEXT, relation TEXT, to_id TEXT, evidence_url TEXT);
```

The link table makes the dictionary a light knowledge graph. A search can walk from a topic to people, from people to their papers, and from their unit to its facilities, without a separate graph database.

### Levels

| Level | Method | Benefits | Downsides |
| --- | --- | --- | --- |
| 1 | JSON files and keyword search (the current prototype) | Nothing to set up | No merging or links; synonyms missed |
| 2 | SQLite with the tables above, merging, links, keyword and embedding search | Traceable graph in one file; handles wording differences | Merge rules need tuning on real data |
| 3 | Graph database (e.g. Neo4j) with a formal ontology | Complex graph questions | Setup time; little gain for a 24-hour demo |

## Running it

Start the slow, unattended jobs first (the BORIS harvest and the full crawl), and measure Apertus extraction speed on 50 pages before committing to a full run.

### Rules for every collector

- Obey robots.txt, identify our crawler by name in the User-Agent, and wait about 1 s between requests to one site.
- Public pages and open APIs only; no logins and no bypassing of access blocks (e.g. the restricted BORIS REST API).
- Keep only professional contact data the institution publishes (Swiss data protection law, nDSG).
- Cache everything we download, so reruns and demos need no network.

### Build order

1. Start the BORIS OAI-PMH harvest in the background.
2. Run the full static crawl of the 42 sites with raw pages cached; pull Diabetes Center Berne through its WordPress API.
3. Write the extraction prompts and test them on 50 pages; measure speed.
4. Run the full extraction and verification.
5. Enrich publications through Europe PMC and Crossref; link papers to people and units.
6. Build bern.sqlite with links and both search indexes; run the quality checks.
7. Build the level 2 researcher on top of the dictionary.
8. Export JSON for the teammates building the input and output parts.

### Workstreams to assign

| Workstream | Covers | Depends on |
| --- | --- | --- |
| Crawler | Steps 1–4 of the static pipeline; the WordPress API | Nothing |
| Publications | BORIS harvest, Europe PMC and Crossref enrichment, linking papers to people | Person records for the linking step |
| Extraction | Apertus prompts, JSON schemas, verification | Apertus endpoint; cleaned pages |
| Processing and search | SQLite, merging, links, indexes, quality checks | Extraction output |
| Researcher | Research loop, budgets, guard rails | Processing and search |

### Open questions

- [ ] Which Apertus endpoint (8B or 70B, where hosted), and how many pages per minute does it extract?
- [ ] Page budget per site: 50, 100 or 150?
- [ ] Publication years to keep: from 2019, or all of them?
- [ ] Do we need OpenAlex (and its free key), or are BORIS, Europe PMC and Crossref enough?
- [ ] Do we read open-access full texts, or stay with abstracts?
- [ ] Who owns each workstream?

### Sources

The endpoints in the toolbox were tested directly on 2026-10-18: BORIS OAI-PMH (`boris-portal.unibe.ch/server/oai/request`), the dcberne.com WordPress API (`/wp-json/wp/v2/`), the Europe PMC and Crossref search APIs, and UniBE's robots.txt.

- [OpenAlex changelog: API keys required from February 2026](https://help.openalex.org/hc/en-us/articles/38868153578263-Changelog)
- [BORIS Portal project page, University Library Bern](https://ub.unibe.ch/about_us/projects/boris_portal/index_eng.html)
- [BORIS entry in the COAR repository registry](https://ird.coar-repositories.org/systems/8b426b6c-5945-49f9-9c29-341003dea977?lang=en)
